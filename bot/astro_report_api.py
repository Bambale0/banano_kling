"""Owner-scoped admin Astro report queue API (no credits or user billing).

Requests contain only birth facts to *calculate* on the server, not LLM
instructions or self-reported celestial positions. Every call requires
signed Telegram initData. No reports are generated inside HTTP requests.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from aiohttp import web

from bot.config import config
from bot.services.astro_encrypted_checkpoint import EncryptedCheckpointStore
from bot.services.astro_kie_gpt6 import KieSectionProvider
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_pipeline import AstroReportError, load_report_plan
from bot.services.astro_report_store import AstroReportSqlStore

logger = logging.getLogger(__name__)
ASTRO_REPORT_JOBS = web.AppKey("astro_report_jobs", AstroReportJobs)
_VALID_SERVICES = frozenset({"natal", "compatibility", "karma", "year", "month", "solar", "lunar"})


def _place_id(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("Выберите город из справочника GeoNames.")
    return value


def _birth_profile(raw: dict, location: dict) -> dict:
    if not isinstance(raw, dict):
        raise TypeError("Нет проверенных данных рождения.")
    return {
        "date": raw.get("date"), "time": raw.get("time"),
        "latitude": location["latitude"], "longitude": location["longitude"],
        "timezone": location["timezone"],
        **({"fold": raw["fold"]} if "fold" in raw else {}),
    }


async def calculate_verified_facts(service: str, values: dict) -> dict:
    """Return facts from existing ephemeris/GEO contracts, never from client text."""
    from bot.astro_extended_api import _period
    from bot.services.astro_chart_core import (
        build_karma_indicators,
        build_natal_facts,
        build_solar_return_facts,
        build_synastry_facts,
        build_transit_snapshots,
    )
    from bot.services.astro_lunar import build_lunar_calendar, parse_period
    from bot.services.astro_places import get_place
    from bot.services.astro_report_periods import build_solar_report_periods

    if service not in _VALID_SERVICES or not isinstance(values, dict):
        raise ValueError("Неизвестная услуга Astro.")
    if service == "lunar":
        period = values.get("period")
        parse_period(period)
        zone = await asyncio.to_thread(get_place, _place_id(values.get("place_id")))
        return await asyncio.to_thread(build_lunar_calendar, period, zone["timezone"])
    if service == "compatibility":
        first_raw, second_raw = values.get("person_a"), values.get("person_b")
        if not isinstance(first_raw, dict) or not isinstance(second_raw, dict):
            raise ValueError("Нужно заполнить данные обоих людей.")
        a_id, b_id = _place_id(first_raw.get("place_id")), _place_id(second_raw.get("place_id"))
        first, second = await asyncio.gather(
            asyncio.to_thread(get_place, a_id), asyncio.to_thread(get_place, b_id),
        )
        return await asyncio.to_thread(
            build_synastry_facts, _birth_profile(first_raw, first),
            _birth_profile(second_raw, second),
        )
    place = await asyncio.to_thread(get_place, _place_id(values.get("place_id")))
    profile = _birth_profile(values, place)
    if service == "natal":
        return await asyncio.to_thread(build_natal_facts, profile)
    if service == "karma":
        return await asyncio.to_thread(build_karma_indicators, profile)
    if service in ("year", "month"):
        year, month = _period(values.get("period"), kind=service)
        return await asyncio.to_thread(build_transit_snapshots, profile, year=year, month=month)
    year, _ = _period(values.get("period"), kind="solar")
    ret = await asyncio.to_thread(get_place, _place_id(values.get("return_place_id")))
    location = {name: ret[name] for name in ("latitude", "longitude", "timezone")}
    facts = await asyncio.to_thread(build_solar_return_facts, profile, target_year=year,
                                    return_location=location)
    return build_solar_report_periods(facts)


async def _admin_actor(request: web.Request, body: dict) -> int:
    from bot.astro_api import assert_admin_astro_access
    from bot.miniapp import _get_user_context

    token = body.get("init_data")
    if not isinstance(token, str) or not token or token.startswith("vk_session:"):
        raise web.HTTPUnauthorized()
    try:
        owner_id, context = await _get_user_context(request.app, token)
    except (PermissionError, ValueError) as exc:
        raise web.HTTPUnauthorized() from exc
    assert_admin_astro_access(token, owner_id, str(context.get("platform") or "telegram"))
    return owner_id


async def _body(request: web.Request) -> dict:
    if request.content_length is not None and request.content_length > 8192:
        raise web.HTTPRequestEntityTooLarge(max_size=8192, actual_size=request.content_length)
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise web.HTTPBadRequest() from exc
    if not isinstance(value, dict):
        raise web.HTTPBadRequest()
    return value


def _response(result: dict, status: int = 200) -> web.Response:
    return web.json_response(result, status=status, headers={"Cache-Control": "no-store"})


async def astro_report_start(request: web.Request) -> web.Response:
    request_id = uuid4().hex
    body = await _body(request)
    owner_id = await _admin_actor(request, body)
    jobs = request.app.get(ASTRO_REPORT_JOBS)
    if jobs is None:
        return _response({"ok": False, "error": "reports_not_enabled"}, 503)
    kind = body.get("service_id")
    if kind not in _VALID_SERVICES:
        return _response({"ok": False, "error": "unknown_service"}, 400)
    if body.get("consent") is not True:
        return _response({"ok": False, "error": "storage_consent_required"}, 400)
    inputs = body.get("input")
    if not isinstance(inputs, dict):
        return _response({"ok": False, "error": "invalid_input"}, 400)
    try:
        plan = load_report_plan(kind)
        facts = await asyncio.wait_for(calculate_verified_facts(kind, inputs), timeout=90)
        if not config.is_admin(owner_id):
            raise web.HTTPForbidden()
        job_id = await jobs.enqueue(
            owner_id=owner_id, plan=plan, facts=facts, consent=True,
        )
        logger.info("astro_report_queued request_id=%s job_id=%s owner_id=%s kind=%s",
                    request_id, job_id, owner_id, kind)
        return _response({"ok": True, "job_id": job_id, "status": "queued",
                          "request_id": request_id}, 202)
    except web.HTTPException:
        raise
    except (ValueError, TypeError, AstroReportError):
        logger.info("astro_report_invalid request_id=%s kind=%s", request_id, kind)
        return _response({"ok": False, "error": "invalid_input"}, 400)
    except TimeoutError:
        return _response({"ok": False, "error": "calculation_timeout"}, 503)
    except Exception:  # noqa: BLE001 -- never expose birth data or kernel paths
        logger.error("astro_report_start_unavailable request_id=%s kind=%s", request_id, kind)
        return _response({"ok": False, "error": "engine_unavailable"}, 503)


async def astro_report_status(request: web.Request) -> web.Response:
    body = await _body(request)
    owner_id = await _admin_actor(request, body)
    jobs = request.app.get(ASTRO_REPORT_JOBS)
    if jobs is None:
        return _response({"ok": False, "error": "reports_not_enabled"}, 503)
    job_id = body.get("job_id")
    if not isinstance(job_id, str) or len(job_id) != 32:
        return _response({"ok": False, "error": "invalid_job_id"}, 400)
    status = await jobs.status(owner_id=owner_id, job_id=job_id)
    if status is None:
        return _response({"ok": False, "error": "job_not_found"}, 404)
    if not config.is_admin(owner_id):
        raise web.HTTPForbidden()
    return _response({"ok": True, **status})


async def astro_report_retry(request: web.Request) -> web.Response:
    """Admin-only explicit retry of a terminally failed job with renewed consent."""
    request_id = uuid4().hex
    body = await _body(request)
    owner_id = await _admin_actor(request, body)
    jobs = request.app.get(ASTRO_REPORT_JOBS)
    if jobs is None:
        return _response({"ok": False, "error": "reports_not_enabled"}, 503)
    job_id = body.get("job_id")
    if not isinstance(job_id, str) or len(job_id) != 32 or any(
        c not in "0123456789abcdef" for c in job_id
    ):
        return _response({"ok": False, "error": "invalid_job_id"}, 400)
    if body.get("consent") is not True:
        return _response({"ok": False, "error": "storage_consent_required"}, 400)
    if not config.is_admin(owner_id):
        raise web.HTTPForbidden()
    try:
        accepted = await jobs.retry_failed(
            owner_id=owner_id, job_id=job_id, consent=True,
        )
    except ValueError:
        logger.error("astro_report_retry_invalid_config request_id=%s", request_id)
        return _response({"ok": False, "error": "retry_configuration_invalid"}, 503)
    except Exception:
        logger.error("astro_report_retry_unavailable request_id=%s", request_id)
        return _response({"ok": False, "error": "retry_unavailable"}, 503)
    if not accepted:
        return _response({"ok": False, "error": "job_not_retryable"}, 409)
    logger.info("astro_report_manual_retry request_id=%s job_id=%s owner_id=%s",
                request_id, job_id, owner_id)
    return _response({"ok": True, "job_id": job_id, "status": "queued",
                      "request_id": request_id}, 202)


async def astro_report_history(request: web.Request) -> web.Response:
    """Admin-only job metadata; never list decrypted birth facts or report text."""
    body = await _body(request)
    owner_id = await _admin_actor(request, body)
    jobs = request.app.get(ASTRO_REPORT_JOBS)
    if jobs is None:
        return _response({"ok": False, "error": "reports_not_enabled"}, 503)
    service_id = body.get("service_id")
    if service_id is not None and service_id not in _VALID_SERVICES:
        return _response({"ok": False, "error": "unknown_service"}, 400)
    try:
        limit = int(os.getenv("ASTRO_REPORT_HISTORY_LIMIT", "30"))
        history = await jobs.list_owner(
            owner_id=owner_id, service_id=service_id, limit=limit,
        )
    except (TypeError, ValueError):
        return _response({"ok": False, "error": "invalid_history_config"}, 503)
    if not config.is_admin(owner_id):
        raise web.HTTPForbidden()
    return _response({"ok": True, "jobs": history})


async def _astro_report_retention_loop(jobs, checkpoints, stop: asyncio.Event):
    """Enforce configured privacy TTL even when no new jobs are submitted."""
    interval = int(os.getenv("ASTRO_REPORT_CLEANUP_INTERVAL_SECONDS", "3600"))
    if not 60 <= interval <= 86400:
        raise ValueError("Invalid Astro retention cleanup interval")
    while not stop.is_set():
        try:
            await jobs.purge_expired()
            await checkpoints.purge_expired()
        except Exception:  # noqa: BLE001 -- transient database outage
            logger.error("astro_report_expiry_cleanup_unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


@asynccontextmanager
async def _astro_report_runtime(app: web.Application):
    try:
        jobs = AstroReportJobs.from_env()
        provider = KieSectionProvider.from_config()
        await jobs.initialize()
        checkpoints = EncryptedCheckpointStore(AstroReportSqlStore(), key=jobs.data_key)
    except (ValueError, RuntimeError):
        logger.error("astro_reports_disabled configuration_missing_or_invalid")
        yield
        return
    from bot.services.astro_report_worker import AstroReportWorker

    stop = asyncio.Event()
    count = int(os.getenv("ASTRO_REPORT_WORKERS", "1"))
    if not 1 <= count <= 4:
        logger.error("astro_reports_disabled invalid_worker_count")
        yield
        return
    app[ASTRO_REPORT_JOBS] = jobs
    tasks = [asyncio.create_task(AstroReportWorker(
        jobs=jobs, provider=provider, checkpoints=checkpoints,
        is_admin=config.is_admin,
    ).run_forever(stop), name=f"astro-report-worker-{index}")
        for index in range(count)]
    tasks.append(asyncio.create_task(
        _astro_report_retention_loop(jobs, checkpoints, stop),
        name="astro-report-retention-cleanup",
    ))
    logger.info("astro_report_queue_started workers=%s", count)
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("astro_report_queue_stopped")


def setup_astro_report_routes(
    app: web.Application, miniapp_root: str, *, initialize_worker: bool = True,
) -> None:
    app.router.add_post(miniapp_root + "/api/astro/reports/start", astro_report_start)
    app.router.add_post(miniapp_root + "/api/astro/reports/status", astro_report_status)
    app.router.add_post(miniapp_root + "/api/astro/reports/history", astro_report_history)
    app.router.add_post(miniapp_root + "/api/astro/reports/retry", astro_report_retry)
    if initialize_worker and os.getenv("ASTRO_REPORTS_ENABLED", "0") == "1":
        app.cleanup_ctx.append(_astro_report_runtime)
