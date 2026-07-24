from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_direct_script_path_can_import_real_bot_package():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from bot.env import load_project_env; "
                "from bot import db; "
                "print(callable(load_project_env), db.backend_name())"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("True ")
