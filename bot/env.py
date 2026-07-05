from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_env(project_root: Path | None = None) -> None:
    """Load project env files with Postgres overriding local SQLite defaults.

    Real process environment variables keep highest priority. This lets tests or
    one-off maintenance commands force a different database explicitly.
    """

    root = project_root or PROJECT_ROOT
    original_keys = set(os.environ)

    load_dotenv(root / ".env")

    for key, value in dotenv_values(root / ".env.postgres").items():
        if value is None or key in original_keys:
            continue
        os.environ[key] = value
