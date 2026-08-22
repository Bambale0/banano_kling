"""Register curated trend routes before Mini App's API catch-all route."""

from __future__ import annotations

from functools import wraps

from aiohttp import web

from bot.config import config
from bot.pinterest_trend_api import _ensure_pinterest_tool, setup_pinterest_trend_routes
from bot.pinterest_trend_catalog import ensure_pinterest_trend_catalog
from bot.pinterest_trend_flow_contract import install_pinterest_trend_flow_contract
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

    The prompts-list wrapper is a second product guarantee: every request for
    the Trends catalog repairs a missing/deactivated Pinterest system row before
    the list query runs. This covers accidental DB deletion and deployments that
    started before the system row existed without inventing a synthetic trend id.
    """

    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_trend_route_compat_installed", False):
        return

    current_setup = miniapp_module.setup_miniapp_routes
    current_prompts = miniapp_module.miniapp_prompts

    @wraps(current_prompts)
    async def prompts_with_required_system_trends(request: web.Request) -> web.Response:
        payload = await miniapp_module._miniapp_payload(request)
        source = (
            "my"
            if request.path.endswith("/prompts/my")
            else str(payload.get("source", "catalog") or "catalog")
        )
        tag = str(payload.get("tag", "") or "").strip().lower()
        if source == "tag" and tag == "trend":
            await ensure_pinterest_trend_catalog(request.app)
        return await current_prompts(request)

    @wraps(current_setup)
    def setup_with_trend_route(app: web.Application) -> None:
        root = _miniapp_root()
        install_pinterest_trend_flow_contract()
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
        miniapp_module.miniapp_prompts = prompts_with_required_system_trends
        current_setup(app)

    miniapp_module.setup_miniapp_routes = setup_with_trend_route
    miniapp_module._trend_route_compat_installed = True
