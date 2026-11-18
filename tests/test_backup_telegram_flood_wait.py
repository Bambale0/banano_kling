"""Telegram backup delivery retries only authoritative rate-limit rejections."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _executable(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize(
    ("mode", "expected_attempts", "expected_sleeps", "succeeds"),
    [
        ("flood400_then_success", 2, ["9"], True),
        ("flood429_then_success", 2, ["4"], True),
        ("always_flood", 4, ["2", "2", "2"], False),
        ("unsupported400", 1, [], False),
        ("transport_timeout", 1, [], False),
        ("success", 1, [], True),
    ],
)
def test_telegram_backup_rate_limits_have_bounded_safe_retries(
    tmp_path: Path,
    mode: str,
    expected_attempts: int,
    expected_sleeps: list[str],
    succeeds: bool,
) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh",
        scripts / "backup_db.sh",
    )
    db = project / "data" / "bot.db"
    db.parent.mkdir()
    db.write_bytes(b"fake SQLite test input" * 500)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin / "sqlite3",
        """#!/usr/bin/env python3
import re
import shutil
import sys
if len(sys.argv) > 2:
    print("ok")
    raise SystemExit(0)
match = re.search(r"\\.backup '([^']+)'", sys.stdin.read())
if match is None:
    raise SystemExit("missing backup target")
shutil.copyfile(sys.argv[1], match.group(1))
""",
    )
    _executable(
        fake_bin / "curl",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys
args = sys.argv[1:]
output = Path(args[args.index("-o") + 1])
log = Path(os.environ["MOCK_CURL_LOG"])
n = len(log.read_text().splitlines()) if log.exists() else 0
with log.open("a") as fp:
    fp.write("attempt\\n")
mode = os.environ["MOCK_MODE"]
if mode == "success" or (mode.endswith("_then_success") and n > 0):
    output.write_text('{"ok":true}', encoding="utf-8")
    raise SystemExit(0)
if mode == "flood400_then_success":
    data = '{"ok":false,"error_code":400,"description":"Bad Request: too Many Requests: retry after 8"}'
elif mode == "flood429_then_success":
    data = '{"ok":false,"error_code":429,"description":"Too Many Requests","parameters":{"retry_after":3}}'
elif mode == "always_flood":
    data = '{"ok":false,"error_code":400,"description":"Bad Request: too Many Requests: retry after 1"}'
elif mode == "unsupported400":
    data = '{"ok":false,"error_code":400,"description":"Bad Request: unsupported media"}'
elif mode == "transport_timeout":
    raise SystemExit(28)
else:
    raise SystemExit("Unknown mock mode")
output.write_text(data, encoding="utf-8")
raise SystemExit(22)
""",
    )
    _executable(
        fake_bin / "sleep",
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys
with Path(os.environ["MOCK_SLEEP_LOG"]).open("a") as fp:
    fp.write(sys.argv[1] + "\\n")
""",
    )
    calls = tmp_path / "curl-calls.txt"
    sleeps = tmp_path / "sleep-calls.txt"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DATABASE_URL": "",
        "DATABASE_PATH": str(db),
        "DB_BACKUP_DIR": str(project / "backups"),
        "SEND_BACKUP_TO_ADMINS": "1",
        "BOT_TOKEN": "fake-token",
        "ADMIN_IDS": "12345",
        "TELEGRAM_DOCUMENT_MAX_BYTES": "1000000",
        "MOCK_MODE": mode,
        "MOCK_CURL_LOG": str(calls),
        "MOCK_SLEEP_LOG": str(sleeps),
    }
    completed = subprocess.run(
        ["bash", str(scripts / "backup_db.sh")],
        cwd=project, env=env, capture_output=True, text=True, timeout=35,
        check=False,
    )
    assert (completed.returncode == 0) is succeeds, completed.stderr
    assert len(calls.read_text().splitlines()) == expected_attempts
    assert (
        sleeps.read_text().splitlines() if sleeps.exists() else []
    ) == expected_sleeps
    assert "fake-token" not in completed.stderr
    if "flood" in mode:
        assert "rate limited" in completed.stderr
    if mode == "unsupported400":
        assert "Bad Request: unsupported media" in completed.stderr
    if mode == "transport_timeout":
        assert "rate limited" not in completed.stderr
