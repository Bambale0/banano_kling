from __future__ import annotations

import importlib
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from functools import wraps
from typing import Any

from aiohttp import web

from bot.config import config
from bot.services.lava_service import lava_service, normalize_lava_customer_email
from bot.services.payment_email_store import (
    get_payment_email,
    has_payment_email,
    save_payment_email,
)

RequestHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_TREND_TAGS = {"trend", "trend-video"}
_TREND_SUBMIT_PATHS = {
    "/api/v1/prompts",
}
_REQUEST_LAVA_EMAIL: ContextVar[str | None] = ContextVar(
    "miniapp_lava_customer_email",
    default=None,
)

_INSTALLED = False
_ORIGINAL_ADD_POST: Callable[..., Any] | None = None
_ORIGINAL_LAVA_CREATE_INVOICE: Callable[..., Awaitable[dict[str, Any]]] | None = None


async def _get_saved_payment_email(telegram_id: int) -> str | None:
    """Read the address from the Mini App host's local payment database."""

    return normalize_lava_customer_email(await get_payment_email(telegram_id))


async def _save_payment_email(telegram_id: int, email: str) -> str:
    """Persist a normalized address without exposing it back to the browser."""

    normalized = normalize_lava_customer_email(email)
    if not normalized:
        raise ValueError("Invalid Lava customer email")
    return await save_payment_email(telegram_id, normalized)


def _normalized_tags(raw_tags: Any) -> set[str]:
    if not isinstance(raw_tags, (list, tuple, set)):
        return set()
    return {
        str(tag).strip().lower()
        for tag in raw_tags
        if str(tag).strip()
    }


def _requests_trend_publication(body: dict[str, Any]) -> bool:
    return bool(_normalized_tags(body.get("tags")) & _TREND_TAGS)


def _is_lava_payment(body: dict[str, Any]) -> bool:
    return str(body.get("provider") or "").strip().lower() == "lava"


def _get_miniapp_module() -> Any:
    """Import lazily after bot.miniapp has completed initialization."""

    return importlib.import_module("bot.miniapp")


async def _secure_prompt_submit(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    miniapp_module = _get_miniapp_module()
    body = await miniapp_module._miniapp_payload(request)
    if _requests_trend_publication(body):
        try:
            telegram_id, _ctx = await miniapp_module._get_user_context(
                request.app,
                body.get("init_data", ""),
                body.get("start_param_fallback"),
            )
        except ValueError as error:
            return web.json_response(
                {"ok": False, "error": str(error) or "Telegram auth failed"},
                status=401,
            )
        if not config.is_admin(telegram_id):
            return web.json_response(
                {"ok": False, "error": "Добавлять тренды может только администратор"},
                status=403,
            )

    return await original_handler(request)


async def _secure_bootstrap(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    """Expose only a boolean; the saved personal data stays on the server."""

    response = await original_handler(request)
    if not isinstance(response, web.Response) or response.status >= 400:
        return response

    try:
        payload = json.loads(response.text)
    except (TypeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response

    try:
        telegram_id = int(payload.get("telegram_id") or 0)
    except (TypeError, ValueError):
        telegram_id = 0
    if not telegram_id:
        return response

    payload["payment_email_saved"] = await has_payment_email(telegram_id)
    payload.pop("payment_email", None)
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return web.json_response(payload, status=response.status, headers=headers)


async def _secure_create_payment(
    original_handler: RequestHandler,
    request: web.Request,
) -> web.StreamResponse:
    body = await request.json()
    if not _is_lava_payment(body):
        return await original_handler(request)

    raw_customer_email = str(body.get("customer_email") or "").strip()
    submitted_email = None
    if raw_customer_email:
        submitted_email = normalize_lava_customer_email(raw_customer_email)
        if not submitted_email:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Укажите действующую почту для оплаты картой или через СБП",
                },
                status=400,
            )

    miniapp_module = _get_miniapp_module()
    payload = miniapp_module._validate_init_data(
        body.get("init_data", ""),
        config.BOT_TOKEN,
    )
    telegram_id = int(payload["user"]["id"])

    customer_email = submitted_email or await _get_saved_payment_email(telegram_id)
    if not customer_email:
        return web.json_response(
            {
                "ok": False,
                "error": "Укажите действующую почту для оплаты картой или через СБП",
            },
            status=400,
        )

    if submitted_email:
        customer_email = await _save_payment_email(telegram_id, submitted_email)

    token = _REQUEST_LAVA_EMAIL.set(customer_email)
    try:
        return await original_handler(request)
    finally:
        _REQUEST_LAVA_EMAIL.reset(token)


async def _create_invoice_with_request_email(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if _ORIGINAL_LAVA_CREATE_INVOICE is None:
        raise RuntimeError("Mini App regression safety is not installed")

    customer_email = _REQUEST_LAVA_EMAIL.get()
    if customer_email:
        if args:
            args = (customer_email, *args[1:])
        else:
            kwargs["email"] = customer_email

    return await _ORIGINAL_LAVA_CREATE_INVOICE(*args, **kwargs)


def _is_trend_submit_path(path: Any) -> bool:
    normalized = str(path or "").rstrip("/")
    return normalized.endswith("/api/prompts/submit") or normalized in _TREND_SUBMIT_PATHS


def _is_bootstrap_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/bootstrap")


def _is_payment_path(path: Any) -> bool:
    return str(path or "").rstrip("/").endswith("/api/create-payment")


def _wrap_post_handler(path: Any, handler: RequestHandler) -> RequestHandler:
    if _is_trend_submit_path(path):

        @wraps(handler)
        async def guarded_trend_submit(request: web.Request) -> web.StreamResponse:
            return await _secure_prompt_submit(handler, request)

        return guarded_trend_submit

    if _is_bootstrap_path(path):

        @wraps(handler)
        async def guarded_bootstrap(request: web.Request) -> web.StreamResponse:
            return await _secure_bootstrap(handler, request)

        return guarded_bootstrap

    if _is_payment_path(path):

        @wraps(handler)
        async def guarded_create_payment(request: web.Request) -> web.StreamResponse:
            return await _secure_create_payment(handler, request)

        return guarded_create_payment

    return handler


def _guarded_add_post(
    dispatcher: web.UrlDispatcher,
    path: Any,
    handler: RequestHandler,
    **kwargs: Any,
) -> Any:
    if _ORIGINAL_ADD_POST is None:
        raise RuntimeError("Mini App route safety is not installed")
    return _ORIGINAL_ADD_POST(
        dispatcher,
        path,
        _wrap_post_handler(path, handler),
        **kwargs,
    )


def install_miniapp_regression_safety() -> None:
    """Install import-safe route guards before Mini App routes are registered."""

    global _INSTALLED
    global _ORIGINAL_ADD_POST
    global _ORIGINAL_LAVA_CREATE_INVOICE

    if _INSTALLED:
        return

    _ORIGINAL_ADD_POST = web.UrlDispatcher.add_post
    _ORIGINAL_LAVA_CREATE_INVOICE = lava_service.create_invoice

    web.UrlDispatcher.add_post = _guarded_add_post
    lava_service.create_invoice = _create_invoice_with_request_email

    _INSTALLED = True
