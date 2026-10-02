from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_successful_backup_removes_stale_and_current_telegram_parts(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    source_script = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh"
    backup_script = scripts / "backup_db.sh"
    shutil.copy2(source_script, backup_script)

    database = project / "data" / "bot.db"
    database.parent.mkdir()
    database.write_bytes(os.urandom(220_000))

    backup_dir = project / "backups"
    parts_dir = backup_dir / "telegram-parts"
    parts_dir.mkdir(parents=True)
    stale_part = parts_dir / "bot-db-20260101_000000.tar.gz.part-000"
    stale_part.write_bytes(b"stale")
    unrelated_file = parts_dir / "keep.txt"
    unrelated_file.write_text("keep", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "sqlite3",
        """#!/usr/bin/env python3
import re
import shutil
import sys

source = sys.argv[1]
if len(sys.argv) > 2:
    print("ok")
    raise SystemExit(0)

sql = sys.stdin.read()
match = re.search(r"\\.backup '([^']+)'", sql)
if not match:
    raise SystemExit("missing .backup target")
shutil.copyfile(source, match.group(1))
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env python3
from pathlib import Path
import sys

output = None
args = iter(sys.argv[1:])
for arg in args:
    if arg == "-o":
        output = next(args)
if output is None:
    raise SystemExit("curl stub requires -o")
Path(output).write_text('{"ok":true}', encoding="utf-8")
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "DATABASE_URL": "",
            "DATABASE_PATH": str(database),
            "DB_BACKUP_DIR": str(backup_dir),
            "SEND_BACKUP_TO_ADMINS": "1",
            "BOT_TOKEN": "test-token",
            "ADMIN_IDS": "123456",
            "TELEGRAM_DOCUMENT_MAX_BYTES": "50000",
        }
    )
    completed = subprocess.run(
        ["bash", str(backup_script)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert list(parts_dir.glob("*.part-*")) == []
    assert unrelated_file.read_text(encoding="utf-8") == "keep"

    stale_part.write_bytes(b"stale-again")
    env["TELEGRAM_DOCUMENT_MAX_BYTES"] = "1000000"
    direct_send = subprocess.run(
        ["bash", str(backup_script)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert direct_send.returncode == 0, direct_send.stderr
    assert list(parts_dir.glob("*.part-*")) == []
    assert unrelated_file.read_text(encoding="utf-8") == "keep"
