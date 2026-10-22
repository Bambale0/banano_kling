from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_PROJECT_ENV_VAR = "BANANO_SKIP_PROJECT_ENV"
DEFAULT_MINI_APP_URL = "https://neuromixbot.com/mini-app/"


def _apply_runtime_defaults() -> None:
    """Use the public frontend unless the runtime explicitly configures one."""

    os.environ.setdefault("MINI_APP_URL", DEFAULT_MINI_APP_URL)


def load_project_env(project_root: Path | None = None) -> None:
    """Load project env files with Postgres overriding local SQLite defaults.

    Real process environment variables keep highest priority, including the
    public Mini App URL. The canonical production URL is only a fallback.
    """

    if os.getenv(SKIP_PROJECT_ENV_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        _apply_runtime_defaults()
        return

    root = project_root or PROJECT_ROOT
    original_keys = set(os.environ)

    load_dotenv(root / ".env")

    for key, value in dotenv_values(root / ".env.postgres").items():
        if value is None or key in original_keys:
            continue
        os.environ[key] = value

    _apply_runtime_defaults()
