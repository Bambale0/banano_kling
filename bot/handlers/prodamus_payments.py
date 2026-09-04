from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any
from urllib.parse import urlencode, urlparse

from aiogram import F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from bot.database import (
    create_transaction,
    get_or_create_user,
    get_transaction_by_order,
    update_transaction_status,
)
from bot.payment_utils import package_bonus_credits, total_package_credits
from bot.services.preset_manager import preset_manager

logger = logging.getLogger(__name__)

PRODAMUS_WEBHOOK_PATH = "/prodamus/webhook"
DEFAULT_PRODAMUS_WEBHOOK_URL = "https://api.chillcreative.ru/prodamus/webhook"
_FORM_KEY_RE = re.compile(r"^([^\[]+)((?:\[[^\]]*\])*)$")
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_CALLBACK_REGISTERED = False


class ProdamusConfigurationError(RuntimeError):
    pass


class ProdamusPayloadError(ValueError):
    pass


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _payform_url() -> str:
    return _env("PRODAMUS_PAYFORM_URL").rstrip("/") + "/"


def _secret_key() -> str:
    return _env("PRODAMUS_SECRET_KEY")


def _sys_code() -> str:
    return _env("PRODAMUS_SYS")


def _webhook_url() -> str:
    return _env("PRODAMUS_WEBHOOK_URL") or DEFAULT_PRODAMUS_WEBHOOK_URL


def prodamus_enabled() -> bool:
    return bool(_env("PRODAMUS_PAYFORM_URL") and _secret_key() and _sys_code())


def _stringify_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def _normalize_for_hmac(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_for_hmac(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hmac(item) for item in value]
    return _stringify_scalar(value)


def canonical_hmac_json(payload: dict[str, Any]) -> str:
    normalized = _normalize_for_hmac(payload)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return encoded.replace("/", "\\/")


def sign_prodamus_payload(
    payload: dict[str, Any],
    secret_key: str | None = None,
) -> str:
    key = (secret_key if secret_key is not None else _secret_key()).strip()
    if not key:
        raise ProdamusConfigurationError("PRODAMUS_SECRET_KEY is not configured")
    message = canonical_hmac_json(payload).encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_prodamus_signature(
    payload: dict[str, Any],
    signature: str,
    secret_key: str | None = None,
) -> bool:
    supplied = str(signature or "").strip().lower()
    if not supplied:
        return False
    try:
        expected = sign_prodamus_payload(payload, secret_key).lower()
    except ProdamusConfigurationError:
        return False
    return hmac.compare_digest(expected, supplied)


def _flatten_query(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            rows.extend(_flatten_query(item, child))
        return rows
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            rows.extend(_flatten_query(item, child))
        return rows
    rows.append((prefix, _stringify_scalar(value)))
    return rows


def _validate_payform_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProdamusConfigurationError(
            "PRODAMUS_PAYFORM_URL must be a valid https:// payment form URL"
        )
    return url.rstrip("/") + "/"


def build_prodamus_payment_url(
    *,
    order_id: str,
    package_id: str,
    package_name: str,
    credits: int,
    amount_rub: float | Decimal,
    telegram_id: int,
    success_url: str | None = None,
) -> str:
    payform_url = _validate_payform_url(_env("PRODAMUS_PAYFORM_URL"))
    secret = _secret_key()
    sys_code = _sys_code()
    if not secret:
        raise ProdamusConfigurationError("PRODAMUS_SECRET_KEY is not configured")
    if not sys_code:
        raise ProdamusConfigurationError("PRODAMUS_SYS is not configured")

    amount = Decimal(str(amount_rub)).quantize(Decimal("0.01"))
    payload: dict[str, Any] = {
        "order_id": str(order_id),
        "products": [
            {
                "name": f"{package_name} — {int(credits)} бананов",
                "price": f"{amount:.2f}",
                "quantity": "1",
                "sku": str(package_id),
                "type": "service",
            }
        ],
        "do": "pay",
        "sys": sys_code,
        "currency": "rub",
        "callbackType": "json",
        "payments_limit": "1",
        "urlNotification": _webhook_url(),
        "_param_telegram_id": str(int(telegram_id)),
        "_param_package_id": str(package_id),
    }
    if success_url:
        payload["urlSuccess"] = str(success_url)
        payload["urlReturn"] = str(success_url)

    payload["signature"] = sign_prodamus_payload(payload, secret)
    query = urlencode(_flatten_query(payload), doseq=True)
    return f"{payform_url}?{query}"


def _parse_form_key(key: str) -> list[str | int]:
    match = _FORM_KEY_RE.match(str(key))
    if not match:
        return [str(key)]
    tokens: list[str | int] = [match.group(1)]
    for raw in _BRACKET_RE.findall(match.group(2) or ""):
        if raw.isdigit():
            tokens.append(int(raw))
        elif raw:
            tokens.append(raw)
    return tokens


def _assign_nested(root: dict[str, Any], tokens: list[str | int], value: Any) -> None:
    current: Any = root
    for index, token in enumerate(tokens):
        last = index == len(tokens) - 1
        next_token = None if last else tokens[index + 1]

        if isinstance(current, dict):
            key = str(token)
            if last:
                current[key] = value
                return
            if key not in current or current[key] is None:
                current[key] = [] if isinstance(next_token, int) else {}
            current = current[key]
            continue

        if isinstance(current, list):
            if not isinstance(token, int):
                raise ProdamusPayloadError("Invalid Prodamus form nesting")
            while len(current) <= token:
                current.append(None)
            if last:
                current[token] = value
                return
            if current[token] is None:
                current[token] = [] if isinstance(next_token, int) else {}
            current = current[token]
            continue

        raise ProdamusPayloadError("Invalid Prodamus form payload")


def parse_prodamus_form(items: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in items:
        _assign_nested(payload, _parse_form_key(str(key)), str(value))
    return payload


async def _read_webhook_payload(request: web.Request) -> dict[str, Any]:
    content_type = str(request.content_type or "").lower()
    if content_type == "application/json" or content_type.endswith("+json"):
        try:
            payload = await request.json()
        except Exception as exc:
            raise ProdamusPayloadError("Invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProdamusPayloadError("Invalid JSON payload")
        return payload

    try:
        post = await request.post()
    except Exception as exc:
        raise ProdamusPayloadError("Invalid form payload") from exc
    items = [(str(key), value) for key, value in post.items()]
    if not items:
        raise ProdamusPayloadError("Empty webhook payload")
    return parse_prodamus_form(items)


def _merchant_order_id(payload: dict[str, Any]) -> str:
    for key in ("order_num", "order_number", "merchant_order_id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()

    # Some webhook profiles mirror the original merchant order as order_id.
    value = payload.get("order_id")
    return str(value or "").strip()


def _money(value: Any) -> Decimal:
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ProdamusPayloadError("Invalid payment amount") from exc


def _validate_success_payload(payload: dict[str, Any], transaction: Any) -> None:
    status = str(payload.get("payment_status") or "").strip().lower()
    if status != "success":
        raise ProdamusPayloadError("Payment is not successful")

    if payload.get("sum") not in (None, ""):
        expected = _money(getattr(transaction, "amount_rub", 0))
        received = _money(payload.get("sum"))
        if received != expected:
            raise ProdamusPayloadError("Payment amount mismatch")

    currency = str(payload.get("currency") or "").strip().upper()
    if currency and currency not in {"RUB", "RUR"}:
        raise ProdamusPayloadError("Payment currency mismatch")


async def handle_prodamus_webhook(request: web.Request) -> web.Response:
    secret = _secret_key()
    if not secret:
        logger.error("Prodamus webhook rejected: secret is not configured")
        return web.Response(text="error: prodamus not configured", status=503)

    try:
        payload = await _read_webhook_payload(request)
    except ProdamusPayloadError as exc:
        return web.Response(text=f"error: {exc}", status=400)

    signature = request.headers.get("Sign", "")
    if not verify_prodamus_signature(payload, signature, secret):
        logger.warning("Prodamus webhook rejected: invalid signature")
        return web.Response(text="error: invalid signature", status=401)

    status = str(payload.get("payment_status") or "").strip().lower()
    order_id = _merchant_order_id(payload)
    if not order_id:
        return web.Response(text="error: missing merchant order id", status=400)

    transaction = await get_transaction_by_order(order_id)
    if transaction is None:
        logger.warning("Prodamus webhook references unknown order=%s", order_id)
        return web.Response(text="error: unknown order", status=404)
    if str(getattr(transaction, "provider", "")).lower() != "prodamus":
        logger.warning("Prodamus webhook provider mismatch order=%s", order_id)
        return web.Response(text="error: provider mismatch", status=400)

    if status in {"order_canceled", "order_denied"}:
        if str(getattr(transaction, "status", "")).lower() != "completed":
            await update_transaction_status(order_id, "failed")
        return web.Response(text="success", status=200)

    if status != "success":
        logger.info("Prodamus webhook ignored status=%s order=%s", status, order_id)
        return web.Response(text="success", status=200)

    try:
        _validate_success_payload(payload, transaction)
    except ProdamusPayloadError as exc:
        logger.warning("Prodamus webhook rejected order=%s: %s", order_id, exc)
        return web.Response(text=f"error: {exc}", status=400)

    from bot.handlers.payments import _complete_transaction

    result = await _complete_transaction(order_id, bot=request.app.get("bot"))
    if not result.get("ok") and not result.get("already_completed"):
        logger.error(
            "Prodamus completion failed order=%s reason=%s",
            order_id,
            result.get("reason") or "unknown",
        )
        return web.Response(text="error: completion failed", status=500)

    logger.info(
        "Prodamus payment completed order=%s duplicate=%s",
        order_id,
        bool(result.get("already_completed")),
    )
    return web.Response(text="success", status=200)


def _decorate_payment_keyboard(
    markup: InlineKeyboardMarkup,
    package_id: str,
) -> InlineKeyboardMarkup:
    if not prodamus_enabled():
        return markup

    callback_data = f"prodamus_pay_{package_id}"
    rows: list[list[InlineKeyboardButton]] = []
    inserted = False
    for row in markup.inline_keyboard:
        if any(button.callback_data == callback_data for button in row):
            return markup
        if not inserted and any(button.text == "Резерв 2" for button in row):
            rows.append(
                [
                    InlineKeyboardButton(
                        text="💳 Prodamus · Карта / СБП",
                        callback_data=callback_data,
                    )
                ]
            )
            inserted = True
        rows.append(list(row))

    if not inserted:
        back_index = next(
            (
                index
                for index, row in enumerate(rows)
                if any(button.callback_data == "menu_topup" for button in row)
            ),
            len(rows),
        )
        rows.insert(
            back_index,
            [
                InlineKeyboardButton(
                    text="💳 Prodamus · Карта / СБП",
                    callback_data=callback_data,
                )
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def install_prodamus_text_payment_keyboard() -> None:
    from bot import keyboards as keyboards_module
    from bot.handlers import payments as payments_handler

    current_keyboard = payments_handler.get_payment_method_keyboard
    if getattr(current_keyboard, "_prodamus_payment_compat", False):
        return

    @wraps(current_keyboard)
    def payment_keyboard_with_prodamus(*args: Any, **kwargs: Any) -> InlineKeyboardMarkup:
        package_id = str(args[0] if args else kwargs.get("package_id") or "")
        markup = current_keyboard(*args, **kwargs)
        return _decorate_payment_keyboard(markup, package_id)

    payment_keyboard_with_prodamus._prodamus_payment_compat = True
    keyboards_module.get_payment_method_keyboard = payment_keyboard_with_prodamus
    payments_handler.get_payment_method_keyboard = payment_keyboard_with_prodamus


async def handle_prodamus_payment(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    if not prodamus_enabled():
        await callback.answer("Prodamus пока не настроен", show_alert=True)
        return

    package_id = str(callback.data or "").replace("prodamus_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    from bot.handlers import payments as payments_handler

    promo = await payments_handler._get_selected_promo(state)
    promo_bonus = payments_handler._promo_bonus_for_package(promo, package)
    package_bonus = package_bonus_credits(package)
    credits = total_package_credits(package, promo_bonus)
    telegram_id = int(callback.from_user.id)
    order_id = f"{telegram_id}_{int(time.time() * 1000)}_{package_id}"

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"
    try:
        payment_url = build_prodamus_payment_url(
            order_id=order_id,
            package_id=package_id,
            package_name=str(package.get("name") or package_id),
            credits=credits,
            amount_rub=float(package["price_rub"]),
            telegram_id=telegram_id,
            success_url=success_url,
        )
    except Exception as exc:
        logger.exception("Failed to build Prodamus payment order=%s", order_id)
        await callback.message.edit_text(
            "Не удалось открыть Prodamus. Попробуйте другой способ оплаты.\n"
            f"Причина: <code>{types.html.quote(str(exc))}</code>",
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(telegram_id)
    created = await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=order_id,
        provider="prodamus",
        credits=credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        await callback.message.edit_text(
            "Не удалось сохранить платёж. Выберите пакет ещё раз."
        )
        return

    bonus_lines: list[str] = []
    if package_bonus > 0:
        bonus_lines.append(f"• Бонус пакета: <code>{package_bonus}</code> бананов")
    if promo and promo_bonus > 0:
        bonus_lines.append(
            f"• Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code> бананов"
        )
    bonus_text = "\n" + "\n".join(bonus_lines) if bonus_lines else ""

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_topup")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
        ]
    )
    await callback.message.edit_text(
        "💳 <b>Оплата через Prodamus</b>\n"
        f"• Пакет: <code>{package['name']}</code>\n"
        f"• Бананов: <code>{credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "После успешной оплаты бананы начислятся автоматически.",
        reply_markup=markup,
        parse_mode="HTML",
    )
    await callback.answer()


def _install_prodamus_callback() -> None:
    global _CALLBACK_REGISTERED
    if _CALLBACK_REGISTERED:
        return
    from bot.handlers import payments as payments_handler

    payments_handler.router.callback_query.register(
        handle_prodamus_payment,
        F.data.startswith("prodamus_pay_"),
    )
    _CALLBACK_REGISTERED = True


def install_prodamus_miniapp_payment() -> None:
    import bot.miniapp as miniapp_module

    current_payload = miniapp_module._payment_package_payload
    if not getattr(current_payload, "_prodamus_payment_compat", False):
        @wraps(current_payload)
        def package_payload_with_prodamus(package: dict[str, Any]) -> dict[str, Any]:
            payload = current_payload(package)
            payload["prodamus_enabled"] = prodamus_enabled()
            return payload

        package_payload_with_prodamus._prodamus_payment_compat = True
        miniapp_module._payment_package_payload = package_payload_with_prodamus

    current_create_payment = miniapp_module.miniapp_create_payment
    if getattr(current_create_payment, "_prodamus_payment_compat", False):
        return

    @wraps(current_create_payment)
    async def create_payment_with_prodamus(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            provider = str(body.get("provider") or "").strip().lower()
            if provider != "prodamus":
                return await current_create_payment(request)
            if not prodamus_enabled():
                return web.json_response(
                    {"ok": False, "error": "Prodamus not configured"}, status=503
                )

            package_id = str(body.get("package_id") or "").strip()
            if not package_id:
                return web.json_response(
                    {"ok": False, "error": "package_id is required"}, status=400
                )

            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                body.get("init_data", ""),
                body.get("start_param_fallback"),
            )
            user = ctx["user"]
            package = miniapp_module.preset_manager.get_package(package_id)
            if not package:
                return web.json_response(
                    {"ok": False, "error": "Package not found"}, status=404
                )

            promo_code = body.get("promo_code")
            promo = (
                await miniapp_module.get_promo_code_by_code(promo_code, active_only=True)
                if promo_code
                else None
            )
            promo_bonus = (
                miniapp_module.get_promo_bonus_for_credits(package["credits"])
                if promo
                else 0
            )
            credits = miniapp_module.total_package_credits(package, promo_bonus)
            order_id = (
                f"{telegram_id}_{int(miniapp_module.time.time() * 1000)}_{package_id}"
            )

            payment_url = build_prodamus_payment_url(
                order_id=order_id,
                package_id=package_id,
                package_name=str(package.get("name") or package_id),
                credits=credits,
                amount_rub=float(package["price_rub"]),
                telegram_id=int(telegram_id),
                success_url=_env("PRODAMUS_SUCCESS_URL") or None,
            )
            created = await miniapp_module.create_transaction(
                order_id=order_id,
                user_id=user.id,
                payment_id=order_id,
                provider="prodamus",
                credits=credits,
                amount_rub=float(package["price_rub"]),
                status="pending",
                promo_code_id=promo.id if promo and promo_bonus > 0 else None,
                promo_code=promo.code if promo and promo_bonus > 0 else None,
                promo_bonus_credits=promo_bonus,
            )
            if not created:
                return web.json_response(
                    {"ok": False, "error": "Failed to persist payment"}, status=500
                )

            return web.json_response(
                {
                    "ok": True,
                    "provider": "prodamus",
                    "order_id": order_id,
                    "payment_id": order_id,
                    "payment_url": payment_url,
                    "credits": credits,
                    "promo_bonus_credits": promo_bonus,
                    "promo_code": promo.code if promo and promo_bonus > 0 else "",
                }
            )
        except Exception as exc:
            return miniapp_module._miniapp_error_response(
                exc,
                log_message="Mini App Prodamus payment creation failed",
            )

    create_payment_with_prodamus._prodamus_payment_compat = True
    miniapp_module.miniapp_create_payment = create_payment_with_prodamus


def setup_prodamus_routes(app: web.Application) -> None:
    install_prodamus_text_payment_keyboard()
    _install_prodamus_callback()
    install_prodamus_miniapp_payment()
    app.router.add_post(PRODAMUS_WEBHOOK_PATH, handle_prodamus_webhook)
    logger.info(
        "Prodamus payment integration registered: path=%s enabled=%s",
        PRODAMUS_WEBHOOK_PATH,
        prodamus_enabled(),
    )
