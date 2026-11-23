"""Telegram authenticated showcase API. All catalog cards are public-only DTOs."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from aiohttp import web

from bot import trend_catalog, trend_catalog_audit
from bot.config import config

logger = logging.getLogger(__name__)


class TrendCatalogReadCache:
    """Short-lived, role/tariff-scoped catalog; coalesce bursty identical reads.

    The cache contains only sanitized public DTOs, never initData, private
    prompts or actor identity. Admin writes invalidate it immediately.
    """

    def __init__(self, *, ttl_seconds: float | None = None):
        if ttl_seconds is None:
            ttl_seconds = float(os.getenv("TREND_CATALOG_CACHE_TTL_SECONDS", "12"))
        if not 0 <= ttl_seconds <= 120:
            raise ValueError("Invalid trends catalog cache TTL")
        self.ttl_seconds = ttl_seconds
        self._entries: dict[tuple[bool, str, int], tuple[float, list]] = {}
        self._lock = asyncio.Lock()
        self._revision = 0

    def invalidate(self) -> None:
        self._revision += 1
        self._entries.clear()

    async def get(
        self, *, is_admin: bool, tariff: str, limit: int,
    ) -> list:
        key = (is_admin, tariff, max(1, min(12, int(limit))))
        cached = self._entries.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with self._lock:
            cached = self._entries.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            revision = self._revision
            result = await trend_catalog.list_catalog(
                is_admin=is_admin, tariff=tariff, per_category=key[2],
            )
            if self.ttl_seconds and revision == self._revision:
                self._entries[key] = (time.monotonic() + self.ttl_seconds, result)
            return result


_CATALOG_CACHE = web.AppKey("trend_catalog_read_cache", TrendCatalogReadCache)


async def _context(request: web.Request, payload: dict):
    from bot import miniapp

    actor_id, context = await miniapp._get_user_context(
        request.app,
        str(payload.get("init_data") or ""),
        payload.get("start_param_fallback"),
    )
    return actor_id, context


async def _request(request: web.Request) -> dict:
    from bot import miniapp

    value = await miniapp._miniapp_payload(request)
    if not isinstance(value, dict):
        raise trend_catalog.CatalogValidationError("Ожидается JSON-объект")
    return value


def _failure(exc: Exception) -> web.Response:
    if isinstance(exc, trend_catalog.CatalogConflict):
        status, code = 409, "catalog_conflict"
    elif isinstance(exc, trend_catalog.CatalogNotFound):
        status, code = 404, "catalog_not_found"
    elif isinstance(exc, (trend_catalog.CatalogValidationError, TypeError, ValueError)):
        status, code = 400, "catalog_validation_error"
    elif isinstance(exc, PermissionError):
        status, code = 403, "catalog_auth_error"
    elif isinstance(exc, web.HTTPException):
        status, code = int(exc.status), "catalog_auth_error"
    else:
        logger.exception("Trend catalog request failed")
        return web.json_response(
            {
                "ok": False,
                "code": "catalog_unavailable",
                "error": "Не удалось получить каталог. Попробуйте позже.",
            },
            status=500,
        )
    return web.json_response(
        {"ok": False, "code": code, "error": str(exc)}, status=status
    )


async def miniapp_trend_catalog(request: web.Request) -> web.Response:
    try:
        from bot.creator_tariff import get_actor_tariff

        payload = await _request(request)
        actor_id, _ = await _context(request, payload)
        is_admin = config.is_admin(actor_id)
        # A just-saved admin trend must be immediately visible even while the
        # public read cache is warm. Viewers cannot invalidate shared caches.
        if is_admin and payload.get("force_refresh") is True:
            request.app[_CATALOG_CACHE].invalidate()
        catalog = await request.app[_CATALOG_CACHE].get(
            is_admin=is_admin,
            limit=payload.get("limit", 6),
            tariff=await get_actor_tariff(actor_id),
        )
        return web.json_response(
            {"ok": True, "categories": catalog}, headers={"Cache-Control": "no-store"}
        )
    except Exception as exc:  # noqa: BLE001 - API boundary catches unexpected provider/DB errors safely
        return _failure(exc)


async def miniapp_trend_category(request: web.Request) -> web.Response:
    try:
        from bot.creator_tariff import get_actor_tariff

        payload = await _request(request)
        actor_id, _ = await _context(request, payload)
        category = await trend_catalog.category_page(
            payload.get("category_id"),
            is_admin=config.is_admin(actor_id),
            page=payload.get("page", 1),
            limit=payload.get("limit", 24),
            tariff=await get_actor_tariff(actor_id),
        )
        return web.json_response(
            {"ok": True, **category}, headers={"Cache-Control": "no-store"}
        )
    except Exception as exc:  # noqa: BLE001 - API boundary catches unexpected provider/DB errors safely
        return _failure(exc)


async def miniapp_admin_trend_categories(request: web.Request) -> web.Response:
    try:
        payload = await _request(request)
        actor_id, _ = await _context(request, payload)
        if not config.is_admin(actor_id):
            raise web.HTTPForbidden(
                text="Управление витриной доступно только администратору"
            )
        op = str(payload.get("op") or "").strip().lower()
        if op == "history":
            result = await trend_catalog_audit.list_history(
                limit=payload.get("limit", 30)
            )
        elif op == "create":
            result = await trend_catalog.create_category(
                payload.get("title"),
                payload.get("emoji", ""),
                actor_id=actor_id,
            )
        elif op == "update":
            result = await trend_catalog.update_category(
                payload.get("category_id"),
                payload.get("revision"),
                title=payload.get("title"),
                emoji=payload.get("emoji"),
                is_visible=payload.get("is_visible"),
                actor_id=actor_id,
            )
        elif op == "delete":
            await trend_catalog.delete_category(
                payload.get("category_id"),
                payload.get("revision"),
                actor_id=actor_id,
            )
            result = {"deleted": True}
        elif op == "reorder":
            result = await trend_catalog.reorder_categories(
                payload.get("categories"),
                actor_id=actor_id,
            )
        elif op == "set_items":
            result = await trend_catalog.replace_category_items(
                payload.get("category_id"),
                payload.get("trend_ids"),
                revision=payload.get("revision"),
                actor_id=actor_id,
            )
        elif op == "set_trend_categories":
            await trend_catalog.set_trend_categories(
                payload.get("trend_id"),
                payload.get("category_ids"),
                actor_id=actor_id,
            )
            result = {"saved": True}
        elif op == "move_item":
            await trend_catalog.move_trend_between_categories(
                payload.get("trend_id"),
                payload.get("source_id"),
                payload.get("target_id"),
                source_revision=payload.get("source_revision"),
                target_revision=payload.get("target_revision"),
                actor_id=actor_id,
            )
            result = {"moved": True}
        elif op == "set_badge":
            result = await trend_catalog.set_badge(
                payload.get("category_id"),
                payload.get("trend_id"),
                payload.get("revision"),
                badge=payload.get("badge", ""),
                badge_until=payload.get("badge_until"),
                actor_id=actor_id,
            )
        elif op == "search_trends":
            result = await trend_catalog.search_admin_trends(
                payload.get("query", ""),
                page=payload.get("page", 1),
                limit=payload.get("limit", 24),
            )
        else:
            raise trend_catalog.CatalogValidationError(
                "Неизвестное действие редактора витрины"
            )
        if op not in {"search_trends", "history"}:
            request.app[_CATALOG_CACHE].invalidate()
            logger.info(
                "Trend showcase admin mutation: op=%s actor=%s category=%s trend=%s",
                op,
                actor_id,
                payload.get("category_id"),
                payload.get("trend_id"),
            )
        return web.json_response(
            {"ok": True, "result": result}, headers={"Cache-Control": "no-store"}
        )
    except Exception as exc:  # noqa: BLE001 - API boundary catches unexpected provider/DB errors safely
        return _failure(exc)


def setup_trend_catalog_routes(app: web.Application, miniapp_root: str) -> None:
    app[_CATALOG_CACHE] = TrendCatalogReadCache()
    base = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(f"{base}/api/trends/catalog", miniapp_trend_catalog)
    app.router.add_post(f"{base}/api/trends/category", miniapp_trend_category)
    app.router.add_post(
        f"{base}/api/admin/trends/categories", miniapp_admin_trend_categories
    )
