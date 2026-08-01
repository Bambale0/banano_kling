from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKIP_PROJECT_ENV_VAR = "BANANO_SKIP_PROJECT_ENV"
DEFAULT_MINI_APP_URL = "https://cdn.chillcreative.ru/mini-app/"


def _normalized_url(value: str) -> str:
    value = str(value or "").strip()
    return f"{value.rstrip('/')}/" if value else ""


def _legacy_backend_mini_app_url() -> str:
    host = str(os.getenv("WEBHOOK_HOST", "") or "").strip().rstrip("/")
    if not host:
        return ""

    path = str(os.getenv("MINI_APP_PATH", "/mini-app") or "/mini-app").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{host}{path.rstrip('/')}/"


def _apply_runtime_defaults() -> None:
    """Keep Telegram WebApp buttons on the public frontend, not the API host."""

    configured = _normalized_url(os.getenv("MINI_APP_URL", ""))
    legacy_backend_url = _normalized_url(_legacy_backend_mini_app_url())

    # Older deployments derived MINI_APP_URL from WEBHOOK_HOST. That opens the
    # backend HTML fallback instead of the separately deployed Mini App frontend.
    if not configured or (legacy_backend_url and configured == legacy_backend_url):
        os.environ["MINI_APP_URL"] = DEFAULT_MINI_APP_URL
        return

    os.environ["MINI_APP_URL"] = configured


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
