#!/usr/bin/env python3
"""Add only VK's missing upload route; preserve the provisioned TLS/API vhost."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    previous = path.stat() if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if previous and hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, timeout=30)


def _server_span(text: str, position: int) -> tuple[int, int]:
    """Find the enclosing server, respecting Nginx comments and quoted braces."""
    tokens = re.finditer(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*|[{};]|[^\s{};]+''', text)
    stack = []
    header = []
    servers = []
    for token in tokens:
        value = token[0]
        if value.startswith("#"):
            continue
        if value == "{":
            stack.append((header[0] if header else "", token.start()))
            header = []
        elif value == "}":
            if not stack:
                raise ValueError("Unbalanced Nginx blocks")
            kind, start = stack.pop()
            if kind == "server" and start < position < token.start():
                servers.append((start, token.start()))
            header = []
        elif value == ";":
            header = []
        else:
            header.append(value)
    if stack or len(servers) != 1:
        raise ValueError("Expected one enclosing Nginx server")
    return servers[0]


def configure(site: Path, snippet: Path, *, run=_run) -> None:
    # sites-enabled is normally a symlink; replace its target, never the link.
    site = site.resolve(strict=True)
    snippet = snippet.resolve()
    original = site.read_bytes()
    text = original.decode("utf-8")
    # Mask comments in place so regex offsets still identify the original bytes.
    active = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*''',
                    lambda match: " " * len(match[0]) if match[0].startswith("#") else match[0], text)
    if any(character in snippet.as_posix() for character in ('"', "\n", "\r", ";")):
        raise ValueError("Unsafe Nginx snippet path")
    upstream_matches = list(re.finditer(
        r"location\s+\^~\s+/mini-app/api/\s*\{\s*proxy_pass\s+([^;\s]+)\s*;",
        active,
    ))
    if len(upstream_matches) != 1:
        raise ValueError("Expected existing Mini App API proxy")
    upstream = upstream_matches[0]
    server_start, server_end = _server_span(text, upstream.start())
    origin = urlsplit(upstream[1])
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
        or "$" in upstream[1]
    ):
        raise ValueError("Expected a literal API upstream origin")
    if re.search(r"location[^\n{]*/uploads", active):
        raise ValueError("Existing custom upload route requires review")
    include = f'    include "{snippet.as_posix()}";\n'
    if include.strip() not in active:
        # HTTP redirect may also have location /. Only the SPA after the API
        # block is eligible; ambiguous layouts fail without modifying anything.
        candidates = list(re.finditer(r"(?m)^([ \t]*)location\s+/\s*\{", active[upstream.end():server_end]))
        if len(candidates) != 1:
            raise ValueError("Expected one SPA fallback after the API proxy")
        position = upstream.end() + candidates[0].start()
        text = text[:position] + include + text[position:]
    elif active.count(include.strip()) != 1 or include.strip() not in active[server_start:server_end]:
        raise ValueError("Duplicate managed media include")
    fragment = (
        "# Managed by scripts/configure_vk_media_route.py.\n"
        "# Keep Range, response type and access/cache policy owned by aiohttp.\n"
        "location ^~ /uploads/ {\n"
        f"    proxy_pass {upstream[1].rstrip('/')};\n"
        "    proxy_http_version 1.1;\n"
        "    proxy_set_header Host $host;\n"
        "    proxy_set_header X-Real-IP $remote_addr;\n"
        "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "    proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    proxy_set_header X-Forwarded-Host $host;\n"
        "    proxy_set_header X-Forwarded-Port $server_port;\n"
        "    proxy_connect_timeout 5s;\n"
        "    proxy_send_timeout 60s;\n"
        "    proxy_read_timeout 120s;\n"
        "    proxy_request_buffering off;\n"
        "    proxy_buffering off;\n"
        "}\n"
    ).encode()
    old_fragment = snippet.read_bytes() if snippet.exists() else None
    old_mode = stat.S_IMODE(snippet.stat().st_mode) if snippet.exists() else 0o644
    site_mode = stat.S_IMODE(site.stat().st_mode)
    updated = text.encode()
    if updated == original and old_fragment == fragment:
        print("VK media route already current")
        return
    reload_attempted = False
    try:
        _atomic_write(snippet, fragment, old_mode)
        _atomic_write(site, updated, site_mode)
        run(["nginx", "-t"])
        reload_attempted = True
        run(["systemctl", "reload", "nginx"])
    except Exception:
        _atomic_write(site, original, site_mode)
        if old_fragment is None:
            snippet.unlink(missing_ok=True)
        else:
            _atomic_write(snippet, old_fragment, old_mode)
        if reload_attempted:
            run(["nginx", "-t"])
            run(["systemctl", "reload", "nginx"])
        raise
    print("VK media route validated and reloaded")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--snippet", type=Path, required=True)
    args = parser.parse_args()
    configure(args.site, args.snippet)


if __name__ == "__main__":
    main()
