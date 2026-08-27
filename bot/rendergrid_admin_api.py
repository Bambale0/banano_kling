from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from aiohttp import web

from bot.config import config
from bot.services.rendergrid_service import RenderGridClient, RenderGridError, rendergrid_client

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _init_data_from_request(request: web.Request) -> str:
    return str(request.headers.get("X-Telegram-Init-Data") or "").strip()


def _rendergrid_error_response(error: RenderGridError) -> web.Response:
    status = error.status if error.status and 400 <= error.status <= 599 else 502
    return web.json_response(
        {
            "ok": False,
            "error": str(error),
            "provider_status": error.status,
            "provider_code": error.code,
            "retry_after": error.retry_after,
        },
        status=status,
    )


async def _require_admin(request: web.Request) -> int:
    # Runtime import avoids a module cycle: miniapp imports several services while
    # the app entrypoint imports this route module before miniapp is fully loaded.
    from bot.miniapp import _validate_init_data

    init_data = _init_data_from_request(request)
    try:
        payload = _validate_init_data(init_data, config.BOT_TOKEN)
        user = payload.get("user") or {}
        telegram_id = int(user.get("id") or 0)
    except (TypeError, ValueError) as exc:
        raise web.HTTPUnauthorized(text="Invalid Telegram Mini App session") from exc

    if not telegram_id or not config.is_admin(telegram_id):
        raise web.HTTPForbidden(text="Admin access required")
    return telegram_id


def rendergrid_admin_endpoint(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            telegram_id = await _require_admin(request)
            request["rendergrid_admin_id"] = telegram_id
            return await handler(request)
        except RenderGridError as exc:
            logger.warning(
                "RenderGrid admin request failed path=%s status=%s code=%s",
                request.path,
                exc.status,
                exc.code,
            )
            return _rendergrid_error_response(exc)
        except web.HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception:
            logger.exception("RenderGrid admin endpoint failed: %s", request.path)
            return web.json_response(
                {"ok": False, "error": "RenderGrid request failed"},
                status=500,
            )

    return wrapped


def _client() -> RenderGridClient:
    # Use a fresh instance so env changes applied at process restart are reflected
    # and so route tests can replace the module singleton without leaking sessions.
    if rendergrid_client.configured:
        return rendergrid_client
    return RenderGridClient()


@rendergrid_admin_endpoint
async def rendergrid_health(_request: web.Request) -> web.Response:
    client = _client()
    return web.json_response(
        {
            "ok": True,
            "configured": client.configured,
            "base_url": client.base_url,
        }
    )


@rendergrid_admin_endpoint
async def rendergrid_models(_request: web.Request) -> web.Response:
    data = await _client().list_models()
    return web.json_response({"ok": True, "data": data})


@rendergrid_admin_endpoint
async def rendergrid_balance(_request: web.Request) -> web.Response:
    data = await _client().get_balance()
    return web.json_response({"ok": True, "data": data})


@rendergrid_admin_endpoint
async def rendergrid_generate_image(request: web.Request) -> web.Response:
    payload = await request.json()
    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "JSON body must be an object"},
            status=400,
        )

    idempotency_key = str(request.headers.get("Idempotency-Key") or "").strip() or None
    data = await _client().generate_image(payload, idempotency_key=idempotency_key)
    return web.json_response({"ok": True, "data": data}, status=202)


@rendergrid_admin_endpoint
async def rendergrid_creation(request: web.Request) -> web.Response:
    creation_id = str(request.match_info.get("creation_id") or "").strip()
    data = await _client().get_creation(creation_id)
    return web.json_response({"ok": True, "data": data})


def setup_rendergrid_admin_routes(app: web.Application) -> None:
    """Register admin-only RenderGrid routes before Mini App's catch-all route."""

    root = "/api/admin/rendergrid"
    app.router.add_get(root + "/health", rendergrid_health)
    app.router.add_get(root + "/models", rendergrid_models)
    app.router.add_get(root + "/balance", rendergrid_balance)
    app.router.add_post(root + "/images/generate", rendergrid_generate_image)
    app.router.add_get(root + "/creations/{creation_id}", rendergrid_creation)
