from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiohttp import web

from bot.config import config
from bot.services.lava_service import lava_service, normalize_lava_customer_email

_TREND_TAGS = {"trend", "trend-video"}
_REQUEST_LAVA_EMAIL: ContextVar[str | None] = ContextVar(
    "miniapp_lava_customer_email",
    default=None,
)

_INSTALLED = False
_MINIAPP_MODULE: Any = None
_ORIGINAL_PROMPT_SUBMIT: Callable[[web.Request], Awaitable[web.Response]] | None = None
_ORIGINAL_CREATE_PAYMENT: Callable[[web.Request], Awaitable[web.Response]] | None = None
_ORIGINAL_LAVA_CREATE_INVOICE: Callable[..., Awaitable[dict[str, Any]]] | None = None


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


async def _secure_prompt_submit(request: web.Request) -> web.Response:
    if _ORIGINAL_PROMPT_SUBMIT is None or _MINIAPP_MODULE is None:
        raise RuntimeError("Mini App regression safety is not installed")

    body = await _MINIAPP_MODULE._miniapp_payload(request)
    if _requests_trend_publication(body):
        telegram_id, _ctx = await _MINIAPP_MODULE._get_user_context(
            request.app,
            body.get("init_data", ""),
            body.get("start_param_fallback"),
        )
        if not config.is_admin(telegram_id):
            return web.json_response(
                {"ok": False, "error": "Добавлять тренды может только администратор"},
                status=403,
            )

    return await _ORIGINAL_PROMPT_SUBMIT(request)


async def _secure_create_payment(request: web.Request) -> web.Response:
    if _ORIGINAL_CREATE_PAYMENT is None:
        raise RuntimeError("Mini App regression safety is not installed")

    body = await request.json()
    if not _is_lava_payment(body):
        return await _ORIGINAL_CREATE_PAYMENT(request)

    customer_email = normalize_lava_customer_email(body.get("customer_email"))
    if not customer_email:
        return web.json_response(
            {
                "ok": False,
                "error": "Укажите действующую почту для оплаты картой или через СБП",
            },
            status=400,
        )

    token = _REQUEST_LAVA_EMAIL.set(customer_email)
    try:
        return await _ORIGINAL_CREATE_PAYMENT(request)
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


def install_miniapp_regression_safety() -> None:
    """Install request-local guards before aiohttp Mini App routes are registered."""

    global _INSTALLED
    global _MINIAPP_MODULE
    global _ORIGINAL_PROMPT_SUBMIT
    global _ORIGINAL_CREATE_PAYMENT
    global _ORIGINAL_LAVA_CREATE_INVOICE

    if _INSTALLED:
        return

    from bot import miniapp as miniapp_module

    _MINIAPP_MODULE = miniapp_module
    _ORIGINAL_PROMPT_SUBMIT = miniapp_module.miniapp_prompt_submit
    _ORIGINAL_CREATE_PAYMENT = miniapp_module.miniapp_create_payment
    _ORIGINAL_LAVA_CREATE_INVOICE = lava_service.create_invoice

    miniapp_module.miniapp_prompt_submit = _secure_prompt_submit
    miniapp_module.miniapp_create_payment = _secure_create_payment
    lava_service.create_invoice = _create_invoice_with_request_email

    _INSTALLED = True
