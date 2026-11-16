"""Admin-only Astro API: authenticated Telegram actor, no debits or birth-data storage."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from aiohttp import web

from bot.config import config
from bot.services.astro_lunar import (
    AstroEngineUnavailable,
    AstroInputError,
    build_lunar_calendar,
    parse_period,
    resolve_timezone,
)

logger = logging.getLogger(__name__)


def assert_admin_astro_access(init_data: object, telegram_id: int, platform: str) -> None:
    """Backend authorization, independent of client-side isAdmin and tab state."""
    if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
        raise web.HTTPUnauthorized()
    if platform != "telegram" or not config.is_admin(telegram_id):
        raise web.HTTPForbidden()


async def astro_lunar_calendar(request: web.Request) -> web.Response:
    request_id = uuid4().hex
    started = time.monotonic()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        # Reject foreign platform credentials before touching the database.
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()

        # Import lazily: bot.miniapp registers this route and owns authentication.
        from bot.miniapp import _get_user_context

        actor_id, ctx = await _get_user_context(request.app, init_data)
        assert_admin_astro_access(
            init_data, actor_id, str(ctx.get("platform") or "telegram")
        )

        period = body.get("period")
        zone = body.get("timezone")
        parse_period(period)
        resolve_timezone(zone)
        result = await asyncio.wait_for(
            asyncio.to_thread(build_lunar_calendar, period, zone),
            timeout=20.0,
        )
        logger.info(
            "astro_lunar_complete request_id=%s actor_id=%s period=%s latency_ms=%.1f",
            request_id, actor_id, period, (time.monotonic() - started) * 1000,
        )
        return web.json_response(
            {"ok": True, "result": result, "request_id": request_id},
            headers={"Cache-Control": "no-store"},
        )
    except web.HTTPException:
        raise
    except AstroInputError as exc:
        return web.json_response(
            {"ok": False, "error": "invalid_input", "message": str(exc)},
            status=400, headers={"Cache-Control": "no-store"},
        )
    except AstroEngineUnavailable:
        logger.warning("astro_lunar_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "engine_unavailable"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except (PermissionError, ValueError) as exc:
        logger.warning(
            "astro_lunar_auth_rejected request_id=%s error=%s",
            request_id, type(exc).__name__,
        )
        raise web.HTTPUnauthorized() from None
    except asyncio.TimeoutError:
        logger.error("astro_lunar_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_lunar_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )


def setup_astro_routes(app: web.Application, miniapp_root: str) -> None:
    app.router.add_post(miniapp_root + "/api/astro/lunar", astro_lunar_calendar)
