from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_INSTALLED = False


def _runtime_revision() -> str:
    value = str(os.getenv("BANANO_APP_REVISION") or "").strip()
    if not value or value.lower() == "unknown":
        return ""
    return value[:64]


def _with_runtime_revision(url: str) -> str:
    revision = _runtime_revision()
    value = str(url or "").strip()
    if not value or not revision:
        return value

    parts = urlsplit(value)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["revision"] = revision
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def install_miniapp_launch_revision_compat(common_module: Any) -> None:
    """Version only Telegram WebApp launch URLs, never the API/base URL.

    Telegram clients and intermediary caches may retain an older Mini App entry
    document. The Docker image revision is immutable, so adding it to WebApp
    buttons gives every deployed image a distinct launch URL while preserving
    referral/startapp query parameters. ``config.mini_app_url`` itself remains
    unchanged because backend redirect and asset routing treat it as a base URL.
    """

    global _INSTALLED
    if _INSTALLED:
        return

    import bot.keyboards as keyboards

    original: Callable[..., str] = keyboards._mini_app_url_with_start_param

    def versioned_url(
        start_param: str | None = None,
        referral_code: str | None = None,
    ) -> str:
        return _with_runtime_revision(
            original(start_param=start_param, referral_code=referral_code)
        )

    keyboards._mini_app_url_with_start_param = versioned_url

    # common.py imports the helper directly, so update that bound reference too.
    if hasattr(common_module, "_mini_app_url_with_start_param"):
        common_module._mini_app_url_with_start_param = versioned_url

    _INSTALLED = True
