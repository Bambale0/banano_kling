"""Register curated trend routes before Mini App's API catch-all route."""

from __future__ import annotations

from functools import wraps

from aiohttp import web

from bot.config import config
from bot.pinterest_trend_api import _ensure_pinterest_tool, setup_pinterest_trend_routes
from bot.pinterest_trend_catalog import ensure_pinterest_trend_catalog
from bot.trend_api import setup_trend_routes
from bot.trend_preview_admin import setup_trend_preview_admin_routes


def _miniapp_root() -> str:
    value = str(getattr(config, "MINI_APP_PATH", "") or "/mini-app").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/") or "/mini-app"


def install_trend_route_compat() -> None:
    """Patch Mini App setup so exact trend routes cannot be swallowed.

    Curated trend endpoints must be registered before ``setup_miniapp_routes``
    because Mini App owns a generic API catch-all route. The strict Pinterest
    catalog verifier replaces the legacy best-effort seed: unlike the old seed,
    it preserves admin-managed promo preview metadata and cannot fail silently.
    """

    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_trend_route_compat_installed", False):
        return

    current_setup = miniapp_module.setup_miniapp_routes

    @wraps(current_setup)
    def setup_with_trend_route(app: web.Application) -> None:
        root = _miniapp_root()
        setup_pinterest_trend_routes(app, root)
        # setup_pinterest_trend_routes still registers its historical best-effort
        # seed. Production uses the strict catalog verifier below instead, so an
        # admin-selected photo/video preview is never overwritten on restart.
        while _ensure_pinterest_tool in app.on_startup:
            app.on_startup.remove(_ensure_pinterest_tool)
        setup_trend_preview_admin_routes(app, root)
        if ensure_pinterest_trend_catalog not in app.on_startup:
            app.on_startup.append(ensure_pinterest_trend_catalog)
        setup_trend_routes(app, root)
        current_setup(app)

    miniapp_module.setup_miniapp_routes = setup_with_trend_route
    miniapp_module._trend_route_compat_installed = True
