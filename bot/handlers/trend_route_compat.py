"""Register curated trend routes before Mini App's API catch-all route."""

from __future__ import annotations

from functools import wraps

from aiohttp import web

from bot.config import config
from bot.pinterest_trend_api import setup_pinterest_trend_routes
from bot.pinterest_trend_catalog import ensure_pinterest_trend_catalog
from bot.trend_api import setup_trend_routes


def _miniapp_root() -> str:
    value = str(getattr(config, "MINI_APP_PATH", "") or "/mini-app").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/") or "/mini-app"


def install_trend_route_compat() -> None:
    """Patch Mini App setup so exact trend routes cannot be swallowed.

    Curated trend endpoints must be registered before ``setup_miniapp_routes``
    because Mini App owns a generic API catch-all route. The Pinterest catalog
    verifier is a strict startup requirement so production cannot become healthy
    without the built-in Pinterest tool visible in Trends.
    """

    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_trend_route_compat_installed", False):
        return

    current_setup = miniapp_module.setup_miniapp_routes

    @wraps(current_setup)
    def setup_with_trend_route(app: web.Application) -> None:
        root = _miniapp_root()
        setup_pinterest_trend_routes(app, root)
        if ensure_pinterest_trend_catalog not in app.on_startup:
            app.on_startup.append(ensure_pinterest_trend_catalog)
        setup_trend_routes(app, root)
        current_setup(app)

    miniapp_module.setup_miniapp_routes = setup_with_trend_route
    miniapp_module._trend_route_compat_installed = True
