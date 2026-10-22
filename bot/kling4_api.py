"""Authenticated Kling4 facade; administrator gate precedes all work."""

from __future__ import annotations

import logging

from aiohttp import web

from bot.services.kling4_contract import Kling4Error, require_admin
from bot.services.kling4_lifecycle import kling4_lifecycle
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycleError
from bot.services.wan3_prime_media import Wan3PrimeValidationError

logger = logging.getLogger(__name__)


async def _actor(request, body):
    # Reject nonadmins before channel probes or user creation. Cryptographic
    # Telegram verification must precede reading the claimed user ID.
    from bot import miniapp
    from bot.config import config
    from bot.wan3_prime_api import _actor_from_request

    init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or body.get("init_data")
        or body.get("initData")
        or ""
    )
    try:
        verified = miniapp._validate_init_data(str(init_data), config.BOT_TOKEN)
        telegram_id = int(verified["user"]["id"])
    except (ValueError, TypeError, KeyError) as exc:
        raise Kling4Error("Откройте Mini App заново из Telegram.", status=401) from exc
    if not config.is_admin(telegram_id):
        raise Kling4Error("Kling 4 доступен только администратору.", status=403)
    actor = await _actor_from_request(request, body)
    require_admin(actor)
    return actor


async def route(request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise Kling4Error("Нужен JSON объект.")
        actor = await _actor(request, body)
        engine = request.app.get("kling4_lifecycle", kling4_lifecycle)
        action = request.match_info["action"]
        if action == "quote":
            result = await engine.quote(actor, body.get("recipe"))
        elif action == "generate":
            result = await engine.launch(
                actor,
                body.get("recipe"),
                body.get("quote_hash"),
                body.get("idempotency_key"),
            )
        elif action == "status":
            result = await engine.status(actor, body.get("task_id"))
        elif action == "history":
            result = {"tasks": await engine.history(actor)}
        elif action == "recipe":
            result = {"recipe": await engine.owner_recipe(actor, body.get("task_id"))}
        elif action == "adopt":
            result = await engine.adopt(
                actor, body.get("task_id"), body.get("provider_task_id")
            )
        elif action == "settings":
            if "settings" in body:
                if type(body.get("revision")) is not int:
                    raise Kling4Error("Нужна ревизия настроек.")
                result = await engine.update_settings(
                    actor, body["settings"], body["revision"]
                )
            else:
                settings, revision = await engine.settings()
                result = {
                    "settings": settings,
                    "revision": revision,
                    "admin_only": True,
                }
        else:
            raise Kling4Error("Неизвестный запрос.", status=404)
        return web.json_response(
            {"ok": True, **result}, headers={"Cache-Control": "no-store"}
        )
    except (Wan3PrimeValidationError, Wan3PrimeLifecycleError) as exc:
        return web.json_response(
            {"ok": False, "error": str(exc)},
            status=exc.status,
            headers={"Cache-Control": "no-store"},
        )
    except web.HTTPException:
        raise
    except (ValueError, TypeError):
        return web.json_response(
            {"ok": False, "error": "Некорректный запрос."}, status=400
        )
    except Exception as exc:  # noqa: BLE001 - isolate boundary failures; persist uncertain outcomes
        logger.error("Kling4 API error_type=%s", type(exc).__name__)
        return web.json_response(
            {
                "ok": False,
                "error": "Не удалось выполнить запрос. Сохраните ключ запуска и проверьте историю.",
            },
            status=503,
        )


def setup_kling4_routes(app, miniapp_root):
    app["kling4_lifecycle"] = app.get("kling4_lifecycle", kling4_lifecycle)

    async def startup(application):
        application["kling4_lifecycle"].telegram_bot = application.get("bot")
        await application["kling4_lifecycle"].start()

    async def cleanup(application):
        await application["kling4_lifecycle"].close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_post(
        miniapp_root
        + "/api/kling4/{action:quote|generate|status|history|recipe|adopt|settings}",
        route,
    )
    app.router.add_post(
        miniapp_root + "/api/kling4/media/{action:init|chunk|complete|cancel|import}",
        media_route,
    )


def catalog_entry():
    return {
        "id": "kling_4",
        "label": "Kling 4",
        "description": "Админ · референсы, персонажи, голоса и ключевые кадры",
        "durations": list(range(3, 31)),
        "ratios": ["auto", "16:9", "9:16", "1:1", "21:9"],
        "supports": ["text", "imgtxt"],
        "max_image_references": 10,
        "max_video_references": 5,
        "costs": {},
        "quality_costs": {},
        "admin_only": True,
    }


async def media_route(request):
    from bot import wan3_prime_api as media
    from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycleError

    try:
        body = (
            await request.json() if request.content_type == "application/json" else {}
        )
        await _actor(request, body)
        handlers = {
            "init": media._upload_init_route,
            "chunk": media._upload_chunk_route,
            "complete": media._upload_complete_route,
            "cancel": media._upload_cancel_route,
            "import": media._import_route,
        }
        return await handlers[request.match_info["action"]](request)
    except (Wan3PrimeValidationError, Wan3PrimeLifecycleError) as exc:
        return web.json_response(
            {"ok": False, "error": str(exc)},
            status=exc.status,
            headers={"Cache-Control": "no-store"},
        )
