#!/usr/bin/env python3
"""Production watchdog for Катин бот (banano_kling).

Checks:
- systemd service state
- exact python process count
- localhost port 8443
- /health endpoint
- upload/log disk usage
- recent application error patterns

On critical process/health failures it tries one controlled systemd restart and
re-checks. Output is safe for cron/systemd logs and does not include secrets.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(os.getenv('BOT_PROJECT_DIR', '/root/bot/banano_kling'))
SERVICE = os.getenv('BOT_SERVICE_NAME', 'bot.service')
HOST = os.getenv('BOT_HEALTH_HOST', '127.0.0.1')
PORT = int(os.getenv('BOT_HEALTH_PORT', '8443'))
HEALTH_URL = f'http://{HOST}:{PORT}/health'
LOG_FILE = PROJECT_DIR / 'logs' / 'watchdog.log'
APP_LOG = PROJECT_DIR / 'logs' / 'bot.log'
UPLOADS_DIR = PROJECT_DIR / 'static' / 'uploads'
ERROR_RE = re.compile(r'(Traceback|\bERROR\b|NameError|Unhandled|Exception)', re.I)
IGNORE_RE = re.compile(r'(aiohttp\.access.*\s404\s|Cannot edit message: Telegram server says)', re.I)


def now() -> str:
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def emit(level: str, message: str) -> None:
    line = f'{now()} [{level}] {message}'
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(line + '\n')


def run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def service_active() -> tuple[bool, str]:
    cp = run(['systemctl', 'is-active', SERVICE])
    state = cp.stdout.strip()
    return state == 'active', state or f'exit={cp.returncode}'


def process_count() -> tuple[int, str]:
    cp = run(['pgrep', '-af', r'python[0-9.]* .* -m bot\.main|python[0-9.]* -m bot\.main'])
    lines = [l for l in cp.stdout.splitlines() if l.strip()]
    return len(lines), '; '.join(lines[:5])


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=3):
            return True
    except OSError:
        return False


def health_ok() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            body = resp.read(128).decode('utf-8', errors='replace').strip()
            return resp.status == 200 and body == 'OK', f'{resp.status} {body!r}'
    except Exception as exc:  # noqa: BLE001 - watchdog must never crash on probe errors
        return False, repr(exc)


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob('*'):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if n < 1024:
            return f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}P'


def recent_error_count(minutes: int = 15) -> int:
    if not APP_LOG.exists():
        return 0
    cutoff = dt.datetime.now() - dt.timedelta(minutes=minutes)
    count = 0
    # Read tail only; bot.log can be large.
    with APP_LOG.open('rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 512_000))
        text = f.read().decode('utf-8', errors='ignore')
    current_ts: dt.datetime | None = None
    for line in text.splitlines():
        m = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if m:
            try:
                current_ts = dt.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                current_ts = None
        if current_ts and current_ts >= cutoff and ERROR_RE.search(line) and not IGNORE_RE.search(line):
            count += 1
    return count


def restart_bot(reason: str) -> bool:
    emit('ERROR', f'critical health failure: {reason}; restarting {SERVICE}')
    cp = run(['systemctl', 'restart', SERVICE], timeout=30)
    if cp.returncode != 0:
        emit('ERROR', f'systemctl restart failed: {cp.stdout.strip()[:500]}')
        return False
    time.sleep(5)
    ok, detail = health_ok()
    emit('INFO' if ok else 'ERROR', f'post-restart health: {detail}')
    return ok


def check_once(auto_restart: bool = True) -> int:
    exit_code = 0
    active, state = service_active()
    count, procs = process_count()
    p_open = port_open()
    h_ok, h_detail = health_ok()
    errors = recent_error_count(15)
    uploads_bytes = dir_size(UPLOADS_DIR)
    log_bytes = APP_LOG.stat().st_size if APP_LOG.exists() else 0
    disk = shutil.disk_usage(str(PROJECT_DIR))

    emit('INFO', f'service={state} process_count={count} port_{PORT}={p_open} health={h_detail} recent_errors_15m={errors}')
    emit('INFO', f'uploads_size={human(uploads_bytes)} bot_log_size={human(log_bytes)} disk_free={human(disk.free)}')

    critical = []
    if not active:
        critical.append(f'service state is {state}')
    if count != 1:
        critical.append(f'expected one bot process, found {count}: {procs}')
    if not p_open:
        critical.append(f'port {PORT} closed')
    if not h_ok:
        critical.append(f'health failed: {h_detail}')

    if critical:
        exit_code = 2
        reason = ' | '.join(critical)
        if auto_restart:
            if restart_bot(reason):
                return 0
        else:
            emit('ERROR', reason)
    if errors:
        emit('WARNING', f'{errors} app error-like log lines in last 15m')
        exit_code = max(exit_code, 1)
    if disk.free < 2 * 1024**3:
        emit('WARNING', f'low disk free: {human(disk.free)}')
        exit_code = max(exit_code, 1)
    return exit_code


def self_test() -> int:
    assert human(1024) == '1.0K'
    assert isinstance(port_open(), bool)
    assert PROJECT_DIR.exists()
    assert isinstance(recent_error_count(1), int)
    print('SELF_TEST_OK')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-restart', action='store_true', help='Only report, do not restart service')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return check_once(auto_restart=not args.no_restart)


if __name__ == '__main__':
    raise SystemExit(main())
