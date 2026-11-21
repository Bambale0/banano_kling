"""Pre-deploy backups must keep a restorable DB without doubling disk use."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


def _prepare(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "backup_db.sh"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / "backup_db.sh", script)
    source = root / "data" / "bot.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"database-snapshot" * 5000)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sqlite = fake_bin / "sqlite3"
    sqlite.write_text(
        "#!/usr/bin/env python3\n"
        "import re, shutil, sys\n"
        "if len(sys.argv) > 2:\n"
        "    print('ok')\n"
        "    raise SystemExit(0)\n"
        "match=re.search(r\"\\\\.backup '([^']+)'\", sys.stdin.read())\n"
        "if not match: raise SystemExit('missing backup target')\n"
        "shutil.copyfile(sys.argv[1],match.group(1))\n",
        encoding="utf-8",
    )
    sqlite.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env['PATH']}",
        "DATABASE_URL": "",
        "DATABASE_PATH": str(source),
        "DB_BACKUP_DIR": str(root / "backups"),
        "SEND_BACKUP_TO_ADMINS": "0",
    })
    return script, source, root / "backups", env


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True,
        text=True, timeout=25, check=False,
    )


def test_predeploy_raw_only_keeps_full_db_without_duplicate_archive(tmp_path: Path) -> None:
    script, source, target, env = _prepare(tmp_path)
    env["BACKUP_RAW_ONLY"] = "1"
    result = _run(script, env)
    assert result.returncode == 0, result.stderr
    assert (target / "bot-latest.db").read_bytes() == source.read_bytes()
    assert not (target / "bot-latest.tar.gz").exists()
    assert "archive intentionally omitted" in result.stdout


def test_default_behavior_still_creates_recoverable_telegram_archive(tmp_path: Path) -> None:
    script, source, target, env = _prepare(tmp_path)
    result = _run(script, env)
    assert result.returncode == 0, result.stderr
    with tarfile.open(target / "bot-latest.tar.gz", "r:gz") as archive:
        assert archive.getnames() == ["bot-latest.db"]
        assert archive.extractfile("bot-latest.db").read() == source.read_bytes()


@pytest.mark.parametrize("value", ["invalid", "-1", "true"])
def test_raw_only_invalid_flag_rejected_before_backup(tmp_path: Path, value: str) -> None:
    script, _, target, env = _prepare(tmp_path)
    env["BACKUP_RAW_ONLY"] = value
    result = _run(script, env)
    assert result.returncode != 0
    assert not (target / "bot-latest.db").exists()


def test_raw_only_cannot_skip_archive_for_telegram_delivery(tmp_path: Path) -> None:
    script, _, target, env = _prepare(tmp_path)
    env.update({"BACKUP_RAW_ONLY": "1", "SEND_BACKUP_TO_ADMINS": "1"})
    result = _run(script, env)
    assert result.returncode != 0
    assert "requires SEND_BACKUP_TO_ADMINS=0" in result.stderr
    assert not (target / "bot-latest.db").exists()


def test_raw_only_refuses_stale_archive_in_reused_backup_directory(tmp_path: Path) -> None:
    script, _, target, env = _prepare(tmp_path)
    target.mkdir()
    archive = target / "bot-latest.tar.gz"
    archive.write_bytes(b"keep-this-archive")
    env["BACKUP_RAW_ONLY"] = "1"
    result = _run(script, env)
    assert result.returncode != 0
    assert archive.read_bytes() == b"keep-this-archive"
    assert not (target / "bot-latest.db").exists()


def test_backend_deploy_explicitly_opts_in_without_skipping_backup() -> None:
    deploy = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_backend_docker.sh").read_text()
    assert 'SEND_BACKUP_TO_ADMINS=0 BACKUP_RAW_ONLY=1' in deploy
    assert 'SKIP_BACKUP=1' not in deploy.split("backup_database() {", 1)[1].split("container_health() {", 1)[0]
