#!/usr/bin/env python3
"""Restart bot.service when project code or .env changes.

This is intentionally dependency-free: it polls mtimes with a small debounce
instead of requiring watchdog/watchfiles packages on the server.

Optimisations (2026-07-01):
- Checks /health endpoint before restarting; skips restart if bot is healthy
  and no recent errors in bot logs, avoiding unnecessary downtime.
- Increased default debounce to 8 seconds to batch rapid edit sessions.
- Will force restart after MAX_HOLD_SECONDS even if health is OK, to ensure
  code changes eventually take effect.
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
POLL_SECONDS = float(os.getenv("BOT_RELOAD_POLL_SECONDS", "2.0"))
DEBOUNCE_SECONDS = float(os.getenv("BOT_RELOAD_DEBOUNCE_SECONDS", "8.0"))
MAX_HOLD_SECONDS = float(os.getenv("BOT_RELOAD_MAX_HOLD_SECONDS", "1800.0"))  # 30 min
HEALTH_URL = os.getenv(
    "BOT_HEALTH_URL", "http://127.0.0.1:8443/health"
)
BOT_LOG = PROJECT_DIR / "logs" / "bot.log"
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


def changed_paths(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def check_health() -> tuple[bool, str]:
    """Returns (healthy, reason). Healthy=True means /health returned 200."""
    try:
        import urllib.request

        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "health_ok"
            return False, f"health_status_{resp.status}"
    except Exception as exc:
        return False, f"health_error:{exc}"


def has_recent_log_errors(minutes: int = 5) -> tuple[bool, str]:
    """Check bot log for recent ERROR/CRITICAL messages."""
    if not BOT_LOG.exists():
        return False, "no_log_file"
    try:
        cutoff = dt.datetime.now() - dt.timedelta(minutes=minutes)
        recent_errors = 0
        with BOT_LOG.open("r", encoding="utf-8", errors="replace") as f:
            # Read last 200 lines (fast, no tail dependency)
            lines = f.readlines()
            for line in lines[-200:]:
                try:
                    # Format: 2026-06-30 12:27:00,123 - module - LEVEL - message
                    ts_str = line[:23].strip()
                    if not ts_str:
                        continue
                    ts = dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                if " - ERROR - " in line or " - CRITICAL - " in line:
                    recent_errors += 1
        if recent_errors > 0:
            return True, f"{recent_errors}_recent_errors"
        return False, "no_recent_errors"
    except Exception as exc:
        return False, f"log_check_error:{exc}"


def restart_service(paths: list[str], *, forced: bool = False) -> bool:
    preview = ", ".join(paths[:8])
    if len(paths) > 8:
        preview += f", +{len(paths) - 8} more"
    tag = "forced restart" if forced else "restart"
    emit("INFO", f"change detected: {preview}; {tag} of {SERVICE}")
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


def should_restart() -> tuple[bool, str]:
    """Decide whether a restart is needed based on health and log state.

    Returns (should_restart, reason).
    - If health is down → restart immediately (True)
    - If health is OK but recent errors in logs → restart (True)
    - If health is OK and no recent errors → skip (False) — bot is handling traffic fine
    """
    healthy, health_reason = check_health()
    if not healthy:
        return True, f"unhealthy:{health_reason}"

    has_errors, error_reason = has_recent_log_errors(minutes=5)
    if has_errors:
        return True, f"recent_errors:{error_reason}"

    return False, f"healthy:{health_reason}_no_errors:{error_reason}"


def watch_once() -> int:
    files = snapshot()
    print(f"WATCH_FILES={len(files)}")
    return 0 if files else 1


def watch_loop() -> int:
    previous = snapshot()
    emit("INFO", f"watching {len(previous)} files under {PROJECT_DIR}")
    pending: list[str] = []
    last_change_at: float | None = None
    first_change_at: float | None = None

    while True:
        time.sleep(POLL_SECONDS)
        current = snapshot()
        changes = changed_paths(previous, current)
        if changes:
            pending = sorted(set(pending) | set(changes))
            last_change_at = time.time()
            if first_change_at is None:
                first_change_at = last_change_at
            previous = current
            continue

        if not pending:
            first_change_at = None
            continue

        if last_change_at and time.time() - last_change_at < DEBOUNCE_SECONDS:
            continue

        # Debounce elapsed — decide whether to restart
        hold_duration = time.time() - (first_change_at or last_change_at)
        do_restart, reason = should_restart()

        if do_restart:
            restart_service(pending)
        elif hold_duration >= MAX_HOLD_SECONDS:
            emit(
                "INFO",
                f"Max hold time ({MAX_HOLD_SECONDS}s) reached, forcing restart despite {reason}",
            )
            restart_service(pending, forced=True)
        else:
            emit(
                "INFO",
                f"Skipping restart ({reason}), holding changes for {hold_duration:.0f}s "
                f"(max {MAX_HOLD_SECONDS}s): {', '.join(pending[:5])}",
            )
            # Don't reset pending — wait for max hold or health degradation
            previous = current
            continue

        pending = []
        last_change_at = None
        first_change_at = None
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