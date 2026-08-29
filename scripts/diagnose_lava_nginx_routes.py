#!/usr/bin/env python3
"""Read-only diagnostics for Tanya Lava nginx routing.

The script does not edit nginx files, reload services, or touch the database.
It prints active nginx server blocks, listeners, and local IPv4/IPv6 probes.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TARGETS = (
    "tanyapi.chillcreative.ru",
    "devtanyapi.chillcreative.ru",
    "tanyavk.chillcreative.ru",
)

CONFIG_MARKER_RE = re.compile(r"^# configuration file (?P<path>.+):$")
SERVER_START_RE = re.compile(r"(?m)^[ \t]*server[ \t]*\{")
SERVER_NAME_RE = re.compile(r"(?m)^[ \t]*server_name[ \t]+([^;]+);")
LOCATION_RE = re.compile(
    r"(?m)^[ \t]*location[ \t]+(?P<modifier>=|\^~|~\*|~)?[ \t]*(?P<path>[^ \t\{]+)[ \t]*\{"
)
DIRECTIVE_RE = re.compile(
    r"(?m)^[ \t]*(listen|server_name|proxy_pass|add_header|proxy_set_header)[ \t]+[^;]+;"
)


@dataclass
class ConfigChunk:
    path: str
    text: str


def run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )


def matching_brace(source: str, opening_index: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False

    for index in range(opening_index, len(source)):
        char = source[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#":
            in_comment = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index

    raise RuntimeError("Unbalanced nginx braces")


def split_config_dump(dump: str) -> list[ConfigChunk]:
    chunks: list[ConfigChunk] = []
    current_path = "<nginx output>"
    current_lines: list[str] = []

    for line in dump.splitlines(keepends=True):
        marker = CONFIG_MARKER_RE.match(line.rstrip("\n"))
        if marker:
            if current_lines:
                chunks.append(ConfigChunk(current_path, "".join(current_lines)))
            current_path = marker.group("path")
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append(ConfigChunk(current_path, "".join(current_lines)))
    return chunks


def iter_server_blocks(text: str) -> Iterable[str]:
    cursor = 0
    while True:
        match = SERVER_START_RE.search(text, cursor)
        if not match:
            return
        opening = text.find("{", match.start(), match.end())
        if opening == -1:
            return
        closing = matching_brace(text, opening)
        yield text[match.start() : closing + 1]
        cursor = closing + 1


def iter_location_blocks(server_block: str) -> Iterable[tuple[str, str]]:
    cursor = 0
    while True:
        match = LOCATION_RE.search(server_block, cursor)
        if not match:
            return
        opening = server_block.find("{", match.start(), match.end())
        if opening == -1:
            return
        closing = matching_brace(server_block, opening)
        label = " ".join(
            part for part in (match.group("modifier") or "", match.group("path")) if part
        )
        yield label, server_block[match.start() : closing + 1]
        cursor = closing + 1


def relevant_directives(block: str) -> list[str]:
    return [" ".join(match.group(0).split()) for match in DIRECTIVE_RE.finditer(block)]


def print_active_blocks(dump: str) -> None:
    print("\n=== Активные server-блоки Tanya из nginx -T ===")
    found = 0
    for chunk in split_config_dump(dump):
        for index, block in enumerate(iter_server_blocks(chunk.text), start=1):
            names: set[str] = set()
            for match in SERVER_NAME_RE.finditer(block):
                names.update(match.group(1).split())
            matched = sorted(names.intersection(TARGETS))
            if not matched:
                continue

            found += 1
            print(f"\n[{found}] source={chunk.path} server_block={index}")
            print("domains=" + ", ".join(matched))
            for directive in relevant_directives(block):
                if directive.startswith(("listen ", "server_name ")):
                    print("  " + directive)

            locations = list(iter_location_blocks(block))
            lava_locations = [item for item in locations if item[0].endswith("/lava/webhook")]
            if not lava_locations:
                print("  LAVA LOCATION: отсутствует")
            for label, location in lava_locations:
                print(f"  location {label}")
                for directive in relevant_directives(location):
                    print("    " + directive)

            root_locations = [item for item in locations if item[0] == "/"]
            for label, location in root_locations:
                print(f"  fallback location {label}")
                for directive in relevant_directives(location):
                    if directive.startswith("proxy_pass "):
                        print("    " + directive)

    if found == 0:
        print("Активные server-блоки Tanya не найдены.")


def print_conflicts(dump: str) -> None:
    print("\n=== Конфликты Tanya-доменов ===")
    lines = [
        line
        for line in dump.splitlines()
        if "conflicting server name" in line and any(domain in line for domain in TARGETS)
    ]
    if lines:
        print("\n".join(lines))
    else:
        print("Конфликтов Tanya-доменов в активной конфигурации нет.")


def print_listeners() -> None:
    print("\n=== Слушающие сокеты 443 / 1888 / 1777 ===")
    result = run(["ss", "-ltnp"])
    if result.returncode != 0:
        print(result.stdout.strip() or f"ss завершился с кодом {result.returncode}")
        return
    lines = [line for line in result.stdout.splitlines() if re.search(r":(443|1888|1777)\b", line)]
    print("\n".join(lines) if lines else "Нужные порты не найдены в выводе ss.")


def parse_headers(raw: str) -> tuple[str, str, str]:
    statuses = re.findall(r"^HTTP/\S+\s+(\d+)", raw, flags=re.MULTILINE | re.IGNORECASE)
    routes = re.findall(r"^x-lava-route:\s*(.+?)\r?$", raw, flags=re.MULTILINE | re.IGNORECASE)
    servers = re.findall(r"^server:\s*(.+?)\r?$", raw, flags=re.MULTILINE | re.IGNORECASE)
    return (
        statuses[-1] if statuses else "000",
        routes[-1].strip() if routes else "missing",
        servers[-1].strip() if servers else "missing",
    )


def curl_probe(domain: str, address: str, label: str) -> None:
    resolve_address = f"[{address}]" if ":" in address else address
    command = [
        "curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--insecure",
        "--connect-timeout",
        "4",
        "--max-time",
        "10",
        "--resolve",
        f"{domain}:443:{resolve_address}",
        "-D",
        "-",
        "-o",
        "/dev/null",
        "-X",
        "POST",
        f"https://{domain}/lava/webhook",
        "-H",
        "Content-Type: application/json",
        "--data",
        f'{{"test":"diagnostic-{label}"}}',
    ]
    result = run(command, timeout=15)
    status, route, server = parse_headers(result.stdout)
    print(
        f"{label:<5} {domain:<33} rc={result.returncode} "
        f"HTTP={status} route={route} server={server}"
    )
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-5:])
        if tail:
            print("      " + tail.replace("\n", "\n      "))


def print_probes() -> None:
    print("\n=== Локальные HTTPS-пробы без DNS и proxy env ===")
    for domain in ("tanyapi.chillcreative.ru", "tanyavk.chillcreative.ru"):
        curl_probe(domain, "127.0.0.1", "IPv4")
        curl_probe(domain, "::1", "IPv6")


def main() -> int:
    if not Path("/etc/nginx/nginx.conf").exists():
        print("nginx.conf не найден", file=sys.stderr)
        return 2

    result = run(["nginx", "-T"], timeout=30)
    dump = result.stdout
    print(f"nginx -T exit_code={result.returncode}")
    print_conflicts(dump)
    print_active_blocks(dump)
    print_listeners()
    print_probes()
    print("\nДиагностика завершена. Конфигурация не изменялась.")
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
