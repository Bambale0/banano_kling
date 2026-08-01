from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_PROJECT_ENV_VAR = "BANANO_SKIP_PROJECT_ENV"
DEFAULT_MINI_APP_URL = "https://cdn.chillcreative.ru/mini-app/"


def _apply_runtime_defaults() -> None:
    """Apply safe public defaults after explicit environment files are loaded."""

    # The Telegram webhook host is a backend API endpoint and must never be used
    # as the implicit Mini App frontend. Keep an explicit MINI_APP_URL override,
    # otherwise point Telegram buttons at the separately deployed CDN frontend.
    os.environ.setdefault("MINI_APP_URL", DEFAULT_MINI_APP_URL)


def load_project_env(project_root: Path | None = None) -> None:
    """Load project env files with Postgres overriding local SQLite defaults.

    Real process environment variables keep highest priority. This lets tests or
    one-off maintenance commands force a different database explicitly.
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
