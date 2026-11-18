"""Regression test: failed Telegram uploads must keep their diagnostic body."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def test_backup_reports_telegram_http_400_description(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh",
        scripts / "backup_db.sh",
    )

    database = project / "data" / "bot.db"
    database.parent.mkdir()
    database.write_bytes(b"SQLite test data " * 512)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin / "sqlite3",
        """#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import sys
if len(sys.argv) > 2:
    print("ok")
    sys.exit(0)
script = sys.stdin.read()
match = re.search(r"\\.backup '([^']+)'", script)
if match is None:
    sys.exit("missing backup target")
shutil.copyfile(sys.argv[1], match.group(1))
""",
    )
    _executable(
        fake_bin / "curl",
        """#!/usr/bin/env python3
from pathlib import Path
import sys
args = sys.argv[1:]
output = args[args.index("-o") + 1]
# curl -f discards HTTP error bodies; --fail-with-body retains them.
old_fail = any(
    arg == "-f" or (arg.startswith("-") and not arg.startswith("--") and "f" in arg)
    for arg in args
)
if not old_fail:
    Path(output).write_text(
        '{"ok":false,"error_code":400,"description":"Bad Request: unsupported media"}',
        encoding="utf-8",
    )
raise SystemExit(22)
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "DATABASE_URL": "",
            "DATABASE_PATH": str(database),
            "DB_BACKUP_DIR": str(project / "backups"),
            "SEND_BACKUP_TO_ADMINS": "1",
            "BOT_TOKEN": "fake-token-for-tests-only",
            "ADMIN_IDS": "12345",
        }
    )
    completed = subprocess.run(
        ["bash", str(scripts / "backup_db.sh")],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=35,
        check=False,
    )
    assert completed.returncode != 0
    assert "Bad Request: unsupported media" in completed.stderr
    assert "fake-token-for-tests-only" not in completed.stderr
