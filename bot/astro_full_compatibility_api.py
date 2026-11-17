"""Signed, admin-only two-person JPL synastry with server-resolved GeoNames IDs.

No user birth data stored, no wallet debit and no inference from free-text cities.
Legacy compatibility API remains unchanged for backward compatibility.
"""

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
    build_synastry_facts as build_full_synastry_facts,
)
from bot.services.astro_lunar import AstroInputError
from bot.services.astro_places import AstroPlacesUnavailable, get_place

logger = logging.getLogger(__name__)


def _person(raw: object) -> tuple[int, dict]:
    if not isinstance(raw, dict):
        raise AstroInputError("Нужно заполнить данные рождения обоих людей.")
    place_id = raw.get("place_id")
    if type(place_id) is not int or not 1 <= place_id <= 2_147_483_647:
        raise AstroInputError("Выберите город рождения каждого человека из списка.")
    # Rejects untrusted client longitude, latitude, timezone and admin flags.
    profile = {"date": raw.get("date"), "time": raw.get("time")}
    if "fold" in raw:
        profile["fold"] = raw["fold"]
    return place_id, profile


async def astro_full_compatibility_facts(request: web.Request) -> web.Response:
    request_id = uuid4().hex
    start = time.monotonic()
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

        from bot.astro_api import assert_admin_astro_access
        from bot.miniapp import _get_user_context

        try:
            actor_id, context = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(init_data, actor_id, str(context.get("platform") or "telegram"))

        a_id, first = _person(body.get("person_a"))
        b_id, second = _person(body.get("person_b"))
        city_a, city_b = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(get_place, a_id),
                asyncio.to_thread(get_place, b_id),
            ),
            timeout=5.0,
        )
        first.update({key: city_a[key] for key in ("latitude", "longitude", "timezone")})
        second.update({key: city_b[key] for key in ("latitude", "longitude", "timezone")})
        result = await asyncio.wait_for(
            asyncio.to_thread(build_full_synastry_facts, first, second),
            timeout=55.0,
        )
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()
        response = web.json_response(
            {"ok": True, "result": result, "request_id": request_id},
            headers={"Cache-Control": "no-store"},
        )
        logger.info(
            "astro_full_compatibility_complete request_id=%s actor_id=%s latency_ms=%.1f",
            request_id, actor_id, (time.monotonic() - start) * 1000,
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
        logger.warning("astro_full_compatibility_unavailable request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "engine_unavailable",
             "message": "Расчёт сейчас недоступен. Баланс не списан."},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.warning("astro_full_compatibility_timeout request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception("astro_full_compatibility_error request_id=%s", request_id)
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )
