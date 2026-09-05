"""Add explicit Lava methods and payment compatibility guards."""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from bot.services.freekassa_service import (
    FREEKASSA_CARD_RUB_METHOD_ID,
    FREEKASSA_SBP_METHOD_ID,
    freekassa_service,
)
from bot.services.lava_service import normalize_lava_customer_email
from bot.tribute_config import TRIBUTE_PACKAGE_LINKS


_LAVA_MINIAPP_METHODS = {
    "lava_card": ("rub", None, "CARD"),
    "lava_sbp": ("rub", "PAY2ME", "SBP"),
    "lava_foreign": ("foreign", None, None),
    "lava_foreign_card": ("foreign", "UNLIMIT", "CARD"),
    "lava_foreign_paypal": ("foreign", "PAYPAL", None),
}
_FREEKASSA_MINIAPP_METHODS = {
    "freekassa_card": FREEKASSA_CARD_RUB_METHOD_ID,
    "freekassa_sbp": FREEKASSA_SBP_METHOD_ID,
}


def _payment_error_message(result: Any, *, default: str = "Failed to create payment") -> str:
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        for key in ("error", "message", "Message", "raw"):
            value = result.get(key)
            message = _payment_error_message(value, default="")
            if message:
                return message
    return default


def _decorate_text_payment_options(
    markup: InlineKeyboardMarkup,
    package_id: str,
) -> InlineKeyboardMarkup:
    """Expose Tribute as the CIS/foreign fallback in the flat Telegram payment keyboard."""

    tribute_url = TRIBUTE_PACKAGE_LINKS.get(str(package_id))
    if not tribute_url:
        return markup

    reserve_label = "СНГ И ЗАРУБЕЖНЫЕ"
    star_labels = {"⭐ Stars", "⭐ Telegram Stars"}
    rows: list[list[InlineKeyboardButton]] = []
    stars_rows: list[list[InlineKeyboardButton]] = []

    for row in markup.inline_keyboard:
        if any(button.text == reserve_label for button in row):
            continue
        if len(row) == 1 and row[0].text in star_labels:
            stars_rows.append(list(row))
            continue
        rows.append(list(row))

    reserve_row = [InlineKeyboardButton(text=reserve_label, url=tribute_url)]
    sbp_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any(button.text == "⚡ СБП" for button in row)
        ),
        -1,
    )
    if sbp_index >= 0:
        rows.insert(sbp_index + 1, reserve_row)
    else:
        rows.insert(0, reserve_row)

    back_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any(button.callback_data == "menu_topup" for button in row)
        ),
        len(rows),
    )
    for star_row in stars_rows:
        rows.insert(back_index, star_row)
        back_index += 1

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _install_freekassa_reserve_button() -> None:
    """Expose KASSA and Reserve 2 in the actual text-bot payment keyboard."""

    from bot.handlers import lava_checkout as lava_checkout_module

    current_keyboard = lava_checkout_module._payment_options_keyboard
    if getattr(current_keyboard, "_freekassa_reserve_compat", False):
        return

    @wraps(current_keyboard)
    def payment_options_with_reserves(*args: Any, **kwargs: Any):
        package_id = str(args[0] if args else kwargs.get("package_id") or "")
        kwargs["freekassa"] = bool(freekassa_service.api_enabled)
        markup = current_keyboard(*args, **kwargs)
        return _decorate_text_payment_options(markup, package_id)

    payment_options_with_reserves._freekassa_reserve_compat = True
    lava_checkout_module._payment_options_keyboard = payment_options_with_reserves


def _install_freekassa_package_flag(miniapp_module: Any) -> None:
    """Expose only a boolean availability flag to the Mini App bootstrap."""

    current_payload = miniapp_module._payment_package_payload
    if getattr(current_payload, "_freekassa_reserve_compat", False):
        return

    @wraps(current_payload)
    def payment_package_with_freekassa(package: dict[str, Any]) -> dict[str, Any]:
        payload = current_payload(package)
        payload["freekassa_enabled"] = bool(freekassa_service.api_enabled)
        return payload

    payment_package_with_freekassa._freekassa_reserve_compat = True
    miniapp_module._payment_package_payload = payment_package_with_freekassa


async def _create_freekassa_miniapp_checkout(
    request: web.Request,
    body: dict[str, Any],
    raw_provider: str,
    payment_system_id: int,
    miniapp_module: Any,
) -> web.Response:
    """Create our pending order and return the signed local FreeKassa checkout."""

    if not freekassa_service.api_enabled:
        return web.json_response(
            {"ok": False, "error": "KASSA временно недоступна"}, status=503
        )

    package_id = body.get("package_id")
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
        miniapp_module.get_promo_bonus_for_credits(package["credits"]) if promo else 0
    )
    total_credits = miniapp_module.total_package_credits(package, promo_bonus)
    order_id = f"{telegram_id}_{int(miniapp_module.time.time() * 1000)}_{package_id}"

    created = await miniapp_module.create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=order_id,
        provider="freekassa",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )
    if not created:
        return web.json_response(
            {"ok": False, "error": "Не удалось сохранить платёж. Попробуйте ещё раз."},
            status=500,
        )

    # Import lazily: this compatibility module is imported before all payment
    # routers, while the checkout handler itself is fully initialized before
    # install_miniapp_lava_payment_methods() is called.
    from bot.handlers.freekassa_payments import _checkout_url

    payment_url = _checkout_url(order_id, payment_system_id)
    return web.json_response(
        {
            "ok": True,
            "provider": raw_provider,
            "order_id": order_id,
            "payment_id": order_id,
            "payment_url": payment_url,
            "credits": total_credits,
            "promo_bonus_credits": promo_bonus,
            "promo_code": promo.code if promo and promo_bonus > 0 else "",
        }
    )


def install_miniapp_lava_payment_methods() -> None:
    """Handle explicit Lava actions and keep FreeKassa as a real reserve."""

    import bot.miniapp as miniapp_module

    _install_freekassa_reserve_button()
    _install_freekassa_package_flag(miniapp_module)

    if getattr(miniapp_module, "_lava_payment_methods_compat_installed", False):
        return

    current_create_payment = miniapp_module.miniapp_create_payment

    @wraps(current_create_payment)
    async def create_payment_with_explicit_lava_method(
        request: web.Request,
    ) -> web.Response:
        try:
            body = await request.json()
            raw_provider = str(body.get("provider") or "").strip().lower()

            freekassa_method = _FREEKASSA_MINIAPP_METHODS.get(raw_provider)
            if freekassa_method is not None:
                return await _create_freekassa_miniapp_checkout(
                    request,
                    body,
                    raw_provider,
                    freekassa_method,
                    miniapp_module,
                )

            lava_method = _LAVA_MINIAPP_METHODS.get(raw_provider)
            if not lava_method:
                return await current_create_payment(request)
            offer_kind, payment_provider, payment_method = lava_method

            package_id = body.get("package_id")
            if not package_id:
                return web.json_response(
                    {"ok": False, "error": "package_id is required"}, status=400
                )

            init_data = body.get("init_data", "")
            promo_code = body.get("promo_code")
            telegram_id, ctx = await miniapp_module._get_user_context(
                request.app,
                init_data,
                body.get("start_param_fallback"),
            )
            user = ctx["user"]

            package = miniapp_module.preset_manager.get_package(package_id)
            if not package:
                return web.json_response(
                    {"ok": False, "error": "Package not found"}, status=404
                )

            if not miniapp_module.lava_service.enabled:
                return web.json_response(
                    {"ok": False, "error": "Lava not configured"}, status=500
                )

            if offer_kind == "foreign":
                (
                    offer_id,
                    lava_currency,
                ) = miniapp_module._miniapp_package_lava_foreign_offer_config(package)
            else:
                offer_id, lava_currency = miniapp_module._miniapp_package_lava_offer_config(
                    package
                )
            if not offer_id:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Lava offer is not configured for package",
                    },
                    status=500,
                )

            order_id = (
                f"{telegram_id}_{int(miniapp_module.time.time() * 1000)}_{package_id}"
            )
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
            total_credits = miniapp_module.total_package_credits(package, promo_bonus)

            raw_customer_email = str(body.get("customer_email") or "").strip()
            customer_email = normalize_lava_customer_email(raw_customer_email)
            if not customer_email:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Укажите действующую почту для оплаты картой или через СБП",
                    },
                    status=400,
                )

            try:
                from bot.handlers.miniapp_regression_safety import _save_payment_email

                customer_email = await _save_payment_email(telegram_id, customer_email)
            except Exception:
                miniapp_module.logger.exception(
                    "Failed to save Mini App Lava payment email user=%s",
                    telegram_id,
                )

            result = await miniapp_module.lava_service.create_invoice(
                email=customer_email,
                offer_id=offer_id,
                currency=lava_currency,
                payment_provider=payment_provider,
                payment_method=payment_method,
                buyer_language="RU",
                _allow_amount_fallback=False,
                client_utm={
                    "telegram_id": str(telegram_id),
                    "order_id": order_id,
                    "package_id": str(package_id),
                    "payment_mode": offer_kind,
                    "requested_payment_method": payment_method or offer_kind,
                },
            )

            if not result or not result.get("ok"):
                return web.json_response(
                    {"ok": False, "error": _payment_error_message(result)},
                    status=500,
                )

            payment_id = miniapp_module.lava_service.extract_invoice_id(result)
            payment_url = miniapp_module.lava_service.extract_payment_url(result)
            if not payment_id or not payment_url:
                return web.json_response(
                    {"ok": False, "error": "Failed to get Lava payment link"},
                    status=500,
                )

            await miniapp_module.create_transaction(
                order_id=order_id,
                user_id=user.id,
                payment_id=payment_id,
                provider="lava",
                credits=total_credits,
                amount_rub=float(package["price_rub"]),
                status="pending",
                promo_code_id=promo.id if promo and promo_bonus > 0 else None,
                promo_code=promo.code if promo and promo_bonus > 0 else None,
                promo_bonus_credits=promo_bonus,
            )

            return web.json_response(
                {
                    "ok": True,
                    "provider": raw_provider,
                    "order_id": order_id,
                    "payment_id": payment_id,
                    "payment_url": payment_url,
                    "credits": total_credits,
                    "promo_bonus_credits": promo_bonus,
                    "promo_code": promo.code if promo and promo_bonus > 0 else "",
                }
            )
        except Exception as exc:
            return miniapp_module._miniapp_error_response(
                exc,
                log_message="Mini App explicit payment creation failed",
            )

    miniapp_module.miniapp_create_payment = create_payment_with_explicit_lava_method
    miniapp_module._lava_payment_methods_compat_installed = True
