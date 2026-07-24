from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_direct_script_can_import_bot_package(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from bot.env import load_project_env\n"
        "from bot import db\n"
        "print(callable(load_project_env), db.backend_name())\n",
        encoding="utf-8",
    )

    # Put the probe into scripts/ semantics by executing a temporary copy there.
    direct_probe = repo_root / "scripts" / ".bootstrap_probe.py"
    try:
        direct_probe.write_text(probe.read_text(encoding="utf-8"), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(direct_probe)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        direct_probe.unlink(missing_ok=True)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("True ")
