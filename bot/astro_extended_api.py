"""Authenticated Astro facts for symbolic karma, year/month transits, solar return.

Admin-only. The server resolves all coordinates and IANA timezones by verified
GeoNames place IDs. No birth data is logged, cached, saved, or sent to an LLM.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from functools import partial
from uuid import uuid4

from aiohttp import web

from bot.config import config
from bot.services.astro_chart_core import (
    AstroChartInputError,
    AstroChartUnavailable,
    build_karma_indicators,
    build_solar_return_facts,
    build_transit_snapshots,
)
from bot.services.astro_lunar import AstroInputError
from bot.services.astro_places import AstroPlacesUnavailable, get_place

logger = logging.getLogger(__name__)

_SUPPORTED_KINDS = frozenset({"karma", "year", "month", "solar"})
_VALID_YEAR = re.compile(r"^(?:19|20)[0-9]{2}$|^2100$")
_VALID_MONTH = re.compile(r"^(?:19|20)[0-9]{2}-(?:0[1-9]|1[0-2])$|^2100-(?:0[1-9]|1[0-2])$")


def _verified_place_id(value: object) -> int:
    if type(value) is not int or not (1 <= value <= 2_147_483_647):
        raise AstroInputError("Выберите город из списка результатов поиска.")
    return value


def _period(value: object, *, kind: str) -> tuple[int, int | None]:
    if not isinstance(value, str):
        raise AstroInputError("Выберите год или месяц расчёта.")
    if kind == "month":
        if not _VALID_MONTH.fullmatch(value):
            raise AstroInputError("Месяц должен быть в формате ГГГГ-ММ.")
        year, month = (int(part) for part in value.split("-"))
        return year, month
    if not _VALID_YEAR.fullmatch(value):
        raise AstroInputError("Год должен быть в диапазоне 1900–2100.")
    return int(value), None


def _profile(body: dict, place: dict) -> dict:
    return {
        "date": body.get("date"),
        "time": body.get("time"),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": place["timezone"],
        **({"fold": body["fold"]} if "fold" in body else {}),
    }


async def astro_extended_facts(request: web.Request, *, kind: str | None = None) -> web.Response:
    """A narrowly scoped signed API, never a generic arbitrary engine executor."""
    kind = kind or request.match_info.get("kind")
    if kind not in _SUPPORTED_KINDS:
        raise web.HTTPNotFound()

    request_id = uuid4().hex
    started = time.monotonic()
    try:
        if request.content_length is not None and request.content_length > 8192:
            raise web.HTTPRequestEntityTooLarge(
                max_size=8192, actual_size=request.content_length,
            )
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AstroInputError("Некорректный JSON-запрос.") from exc
        if not isinstance(body, dict):
            raise AstroInputError("Ожидается JSON-объект.")
        init_data = body.get("init_data")
        if (
            not isinstance(init_data, str)
            or not init_data
            or init_data.startswith("vk_session:")
        ):
            raise web.HTTPUnauthorized()

        from bot.astro_api import assert_admin_astro_access
        from bot.miniapp import _get_user_context

        try:
            actor_id, ctx = await _get_user_context(request.app, init_data)
        except (PermissionError, ValueError):
            raise web.HTTPUnauthorized() from None
        assert_admin_astro_access(
            init_data, actor_id, str(ctx.get("platform") or "telegram"),
        )

        # Validate IDs and period before opening expensive data resources.
        birth_id = _verified_place_id(body.get("place_id"))
        year, month = (None, None)
        if kind != "karma":
            year, month = _period(body.get("period"), kind=kind)
        return_id = None
        if kind == "solar":
            return_id = _verified_place_id(body.get("return_place_id"))

        birth_place = await asyncio.wait_for(
            asyncio.to_thread(get_place, birth_id), timeout=4.0,
        )
        profile = _profile(body, birth_place)

        if kind == "solar":
            location = await asyncio.wait_for(
                asyncio.to_thread(get_place, return_id), timeout=4.0,
            )
            location_data = {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "timezone": location["timezone"],
            }
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    build_solar_return_facts,
                    profile, target_year=year, return_location=location_data,
                ),
                timeout=55.0,
            )
        elif kind in ("year", "month"):
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    build_transit_snapshots,
                    profile, year=year, month=month,
                ),
                timeout=55.0,
            )
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(build_karma_indicators, profile),
                timeout=30.0,
            )

        # Revocation during a long calculation must never expose results.
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden()

        response = web.json_response(
            {"ok": True, "result": result, "request_id": request_id},
            headers={"Cache-Control": "no-store"},
        )
        logger.info(
            "astro_extended_complete request_id=%s actor_id=%s kind=%s latency_ms=%.1f",
            request_id, actor_id, kind, (time.monotonic() - started) * 1000,
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
        logger.warning(
            "astro_extended_unavailable request_id=%s kind=%s", request_id, kind,
        )
        return web.json_response(
            {
                "ok": False, "error": "engine_unavailable",
                "message": "Расчёт сейчас недоступен. Баланс не списан.",
            },
            status=503, headers={"Cache-Control": "no-store"},
        )
    except TimeoutError:
        logger.warning(
            "astro_extended_timeout request_id=%s kind=%s", request_id, kind,
        )
        return web.json_response(
            {"ok": False, "error": "calculation_timeout"},
            status=503, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.exception(
            "astro_extended_error request_id=%s kind=%s", request_id, kind,
        )
        return web.json_response(
            {"ok": False, "error": "internal_error"},
            status=500, headers={"Cache-Control": "no-store"},
        )


def setup_astro_extended_routes(app: web.Application, miniapp_root: str) -> None:
    # Separate explicit routes avoid shadowing existing natal/lunar API.
    for kind in ("karma", "year", "month", "solar"):
        app.router.add_post(
            miniapp_root + "/api/astro/" + kind,
            partial(astro_extended_facts, kind=kind),
        )
