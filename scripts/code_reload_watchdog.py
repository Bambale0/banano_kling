#!/usr/bin/env python3
"""Restart bot.service when project code or .env changes.

This is intentionally dependency-free: it polls mtimes with a small debounce
instead of requiring watchdog/watchfiles packages on the server.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(os.getenv("BOT_PROJECT_DIR", "/root/bot/banano_kling")).resolve()
SERVICE = os.getenv("BOT_SERVICE_NAME", "bot.service")
POLL_SECONDS = float(os.getenv("BOT_RELOAD_POLL_SECONDS", "1.0"))
DEBOUNCE_SECONDS = float(os.getenv("BOT_RELOAD_DEBOUNCE_SECONDS", "2.0"))
LOG_FILE = PROJECT_DIR / "logs" / "code_reload_watchdog.log"

WATCH_DIRS = [
    "bot",
    "tbank_payment",
    "scripts",
]
WATCH_FILES = [
    ".env",
    "requirements.txt",
    "data/price.json",
    "bot.service",
]
WATCH_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".sh", ".service"}
IGNORE_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "logs",
    "static",
}


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def emit(level: str, message: str) -> None:
    line = f"{now()} [{level}] {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def should_ignore(path: Path) -> bool:
    rel_parts = set(path.relative_to(PROJECT_DIR).parts)
    return bool(rel_parts & IGNORE_PARTS)


def iter_watched_files():
    for rel in WATCH_FILES:
        path = PROJECT_DIR / rel
        if path.exists() and path.is_file():
            yield path

    for rel_dir in WATCH_DIRS:
        root = PROJECT_DIR / rel_dir
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or should_ignore(path):
                continue
            if path.suffix in WATCH_SUFFIXES:
                yield path


def snapshot() -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    for path in iter_watched_files():
        try:
            stat = path.stat()
        except OSError:
            continue
        files[str(path.relative_to(PROJECT_DIR))] = (stat.st_mtime_ns, stat.st_size)
    return files


def changed_paths(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def restart_service(paths: list[str]) -> bool:
    preview = ", ".join(paths[:8])
    if len(paths) > 8:
        preview += f", +{len(paths) - 8} more"
    emit("INFO", f"change detected: {preview}; restarting {SERVICE}")
    cp = subprocess.run(
        ["systemctl", "restart", SERVICE],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    if cp.returncode != 0:
        emit("ERROR", f"restart failed: {cp.stdout.strip()[:800]}")
        return False
    emit("INFO", f"restart requested successfully for {SERVICE}")
    return True


def watch_once() -> int:
    files = snapshot()
    print(f"WATCH_FILES={len(files)}")
    return 0 if files else 1


def watch_loop() -> int:
    previous = snapshot()
    emit("INFO", f"watching {len(previous)} files under {PROJECT_DIR}")
    pending: list[str] = []
    last_change_at: float | None = None

    while True:
        time.sleep(POLL_SECONDS)
        current = snapshot()
        changes = changed_paths(previous, current)
        if changes:
            pending = sorted(set(pending) | set(changes))
            last_change_at = time.time()
            previous = current
            continue

        if pending and last_change_at and time.time() - last_change_at >= DEBOUNCE_SECONDS:
            restart_service(pending)
            pending = []
            last_change_at = None
            previous = snapshot()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return watch_once()
    return watch_loop()


if __name__ == "__main__":
    raise SystemExit(main())
