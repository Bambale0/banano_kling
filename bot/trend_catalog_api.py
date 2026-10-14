"""Telegram authenticated showcase API. All catalog cards are public-only DTOs."""

from __future__ import annotations

import logging

from aiohttp import web

from bot import trend_catalog
from bot.config import config

logger = logging.getLogger(__name__)


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
        catalog = await trend_catalog.list_catalog(
            is_admin=config.is_admin(actor_id),
            per_category=payload.get("limit", 6),
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
        if op == "create":
            result = await trend_catalog.create_category(
                payload.get("title"), payload.get("emoji", "")
            )
        elif op == "update":
            result = await trend_catalog.update_category(
                payload.get("category_id"),
                payload.get("revision"),
                title=payload.get("title"),
                emoji=payload.get("emoji"),
                is_visible=payload.get("is_visible"),
            )
        elif op == "delete":
            await trend_catalog.delete_category(
                payload.get("category_id"), payload.get("revision")
            )
            result = {"deleted": True}
        elif op == "reorder":
            result = await trend_catalog.reorder_categories(payload.get("categories"))
        elif op == "set_items":
            result = await trend_catalog.replace_category_items(
                payload.get("category_id"),
                payload.get("trend_ids"),
                revision=payload.get("revision"),
            )
        elif op == "set_trend_categories":
            await trend_catalog.set_trend_categories(
                payload.get("trend_id"),
                payload.get("category_ids"),
            )
            result = {"saved": True}
        elif op == "move_item":
            await trend_catalog.move_trend_between_categories(
                payload.get("trend_id"),
                payload.get("source_id"),
                payload.get("target_id"),
                source_revision=payload.get("source_revision"),
                target_revision=payload.get("target_revision"),
            )
            result = {"moved": True}
        elif op == "set_badge":
            result = await trend_catalog.set_badge(
                payload.get("category_id"),
                payload.get("trend_id"),
                payload.get("revision"),
                badge=payload.get("badge", ""),
                badge_until=payload.get("badge_until"),
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
        if op != "search_trends":
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
    base = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(f"{base}/api/trends/catalog", miniapp_trend_catalog)
    app.router.add_post(f"{base}/api/trends/category", miniapp_trend_category)
    app.router.add_post(
        f"{base}/api/admin/trends/categories", miniapp_admin_trend_categories
    )
