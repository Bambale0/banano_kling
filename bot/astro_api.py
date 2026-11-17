"""Admin-only Astro API: authenticated Telegram actor, no debits or birth-data storage."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from aiohttp import web

from bot.config import config
from bot.services.astro_chart_core import (
    AstroChartInputError,
    AstroChartUnavailable,
)
from bot.services.astro_chart_core import (
    build_natal_facts as build_full_natal_facts,
)
from bot.services.astro_lunar import (
    AstroEngineUnavailable,
    AstroInputError,
    build_lunar_calendar,
    parse_period,
    resolve_timezone,
)
from bot.services.astro_natal import build_natal_facts
from bot.services.astro_places import AstroPlacesUnavailable, get_place, search_places
from bot.services.astro_synastry import build_compatibility_facts

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
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        # Reject foreign platform credentials before touching the database.
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()

        # Import lazily: bot.miniapp registers this route and owns authentication.
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
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
        # An administrator can lose access while calculation is running.
        # Fail closed before returning any personal astronomical facts.
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()
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
    except TimeoutError:
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



async def astro_natal_facts(request: web.Request) -> web.Response:
    """Calculate genuine planet positions, never interpret or persist birth data."""
    request_id = uuid4().hex
    started = time.monotonic()
    try:
        if request.content_length is not None and request.content_length > 4096:
            raise web.HTTPRequestEntityTooLarge(max_size=4096, actual_size=request.content_length)
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(init_data, actor_id, str(ctx.get("platform") or "telegram"))

        result = await asyncio.wait_for(
            asyncio.to_thread(
                build_natal_facts,
                date=body.get("date"),
                time=body.get("time"),
                timezone_name=body.get("timezone"),
                fold=body.get("fold"),
            ),
            timeout=20.0,
        )
        # An administrator can lose access while calculation is running.
        # Fail closed before returning any personal astronomical facts.
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()
        logger.info(
            "astro_natal_complete request_id=%s actor_id=%s time_known=%s latency_ms=%.1f",
            request_id, actor_id, result["birth_time_known"],
            (time.monotonic() - started) * 1000,
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
        logger.warning("astro_natal_engine_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "engine_unavailable"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.error("astro_natal_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_natal_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )



async def astro_compatibility_facts(request: web.Request) -> web.Response:
    """Two birth profiles: authenticated per request, no charges or persistence."""
    request_id = uuid4().hex
    started = time.monotonic()
    try:
        if request.content_length is not None and request.content_length > 8192:
            raise web.HTTPRequestEntityTooLarge(max_size=8192, actual_size=request.content_length)
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(init_data, actor_id, str(ctx.get("platform") or "telegram"))
        result = await asyncio.wait_for(
            asyncio.to_thread(
                build_compatibility_facts,
                body.get("person_a"),
                body.get("person_b"),
            ),
            timeout=25.0,
        )
        # An administrator can lose access while calculation is running.
        # Fail closed before returning any personal astronomical facts.
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()
        logger.info(
            "astro_compatibility_complete request_id=%s actor_id=%s latency_ms=%.1f",
            request_id, actor_id, (time.monotonic() - started) * 1000,
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
        logger.warning("astro_compatibility_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "engine_unavailable"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.error("astro_compatibility_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_compatibility_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )



async def astro_search_places(request: web.Request) -> web.Response:
    """Bounded offline city lookup, Telegram-admin only, no birth data or billing."""
    request_id = uuid4().hex
    started = time.monotonic()
    try:
        if request.content_length is not None and request.content_length > 4096:
            raise web.HTTPRequestEntityTooLarge(
                max_size=4096, actual_size=request.content_length,
            )
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()

        # Use the existing signed Telegram context; the client cannot grant itself admin.
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(
            init_data, actor_id, str(ctx.get("platform") or "telegram"),
        )
        result = await asyncio.wait_for(
            asyncio.to_thread(search_places, body.get("query"), limit=10),
            timeout=4.0,
        )
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()
        logger.info(
            "astro_places_complete request_id=%s actor_id=%s results=%s latency_ms=%.1f",
            request_id, actor_id, len(result), (time.monotonic() - started) * 1000,
        )
        return web.json_response(
            {"ok": True, "results": result, "attribution": "© GeoNames (CC BY 4.0)",
             "request_id": request_id},
            headers={"Cache-Control": "no-store"},
        )
    except web.HTTPException:
        raise
    except AstroInputError as exc:
        return web.json_response(
            {"ok": False, "error": "invalid_input", "message": str(exc)},
            status=400, headers={"Cache-Control": "no-store"},
        )
    except AstroPlacesUnavailable:
        logger.warning("astro_places_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "places_unavailable"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.error("astro_places_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_places_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )


async def astro_full_natal_facts(request: web.Request) -> web.Response:
    """Precise Placidus natal from a SERVER-RESOLVED GeoNames place ID.

    No client coordinates/timezone accepted, no birth data stored, Telegram
    admin authorization checked before and after the CPU-bound calculation.
    """
    request_id = uuid4().hex
    started = time.monotonic()
    try:
        if request.content_length is not None and request.content_length > 8192:
            raise web.HTTPRequestEntityTooLarge(max_size=8192, actual_size=request.content_length)
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")

        init_data = body.get("init_data")
        if not isinstance(init_data, str) or not init_data or init_data.startswith("vk_session:"):
            raise web.HTTPUnauthorized()
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(
            init_data, actor_id, str(ctx.get("platform") or "telegram"),
        )

        place_id = body.get("place_id")
        if type(place_id) is not int or not 1 <= place_id <= 2_147_483_647:
            raise AstroInputError("Выберите город из справочника.")
        # Never trust coordinates, date offsets or IANA names in client POST.
        place = await asyncio.wait_for(asyncio.to_thread(get_place, place_id), timeout=4.0)
        profile = {
            "date": body.get("date"),
            "time": body.get("time"),
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place["timezone"],
        }
        if "fold" in body:
            profile["fold"] = body["fold"]

        chart = await asyncio.wait_for(
            asyncio.to_thread(build_full_natal_facts, profile),
            timeout=25.0,
        )
        # An administrator can lose access while a report is processing.
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()

        response = web.json_response(
            {
                "ok": True, "result": chart,
                "place": {
                    "place_id": place["place_id"],
                    "name": place["name"],
                    "country_code": place["country_code"],
                    "timezone": place["timezone"],
                },
                "request_id": request_id,
            },
            headers={"Cache-Control": "no-store"},
        )
        logger.info(
            "astro_full_natal_complete request_id=%s actor_id=%s "
            "houses_available=%s latency_ms=%.1f",
            request_id, actor_id, chart["accuracy"]["houses_available"],
            (time.monotonic() - started) * 1000,
        )
        return response
    except web.HTTPException:
        raise
    except (AstroInputError, AstroChartInputError) as exc:
        return web.json_response(
            {"ok": False, "error": "invalid_input", "message": str(exc)},
            status=400, headers={"Cache-Control": "no-store"},
        )
    except (AstroPlacesUnavailable, AstroChartUnavailable):
        logger.warning("astro_full_natal_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "engine_unavailable",
             "message": "Полный расчёт сейчас недоступен. Баланс не списан."},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.warning("astro_full_natal_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_full_natal_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )

def setup_astro_routes(app: web.Application, miniapp_root: str) -> None:
    app.router.add_post(miniapp_root + "/api/astro/places", astro_search_places)
    app.router.add_post(miniapp_root + "/api/astro/lunar", astro_lunar_calendar)
    app.router.add_post(miniapp_root + "/api/astro/natal", astro_natal_facts)
    app.router.add_post(miniapp_root + "/api/astro/natal/full", astro_full_natal_facts)
    app.router.add_post(miniapp_root + "/api/astro/compatibility", astro_compatibility_facts)

    from bot.astro_extended_api import setup_astro_extended_routes
    setup_astro_extended_routes(app, miniapp_root)
    from bot.astro_report_api import setup_astro_report_routes

    setup_astro_report_routes(app, miniapp_root)
