"""Expose separate Lava Card and SBP actions in the Mini App checkout."""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiohttp import web

from bot.services.lava_service import normalize_lava_customer_email


_LAVA_MINIAPP_METHODS = {
    "lava_card": "CARD",
    "lava_sbp": "SBP",
}


def _payment_error_message(result: Any, *, default: str = "Не удалось создать платёж") -> str:
    """Extract a human-readable Lava message from arbitrarily nested JSON."""

    if isinstance(result, str):
        message = result.strip()
        if message and message.lower() != "[object object]":
            return message
        return default

    if isinstance(result, dict):
        for key in ("error", "message", "Message", "detail", "description", "raw"):
            if key not in result:
                continue
            message = _payment_error_message(result.get(key), default="")
            if message:
                return message
        for value in result.values():
            message = _payment_error_message(value, default="")
            if message:
                return message

    if isinstance(result, (list, tuple)):
        for value in result:
            message = _payment_error_message(value, default="")
            if message:
                return message

    return default


def install_miniapp_lava_payment_methods() -> None:
    """Handle separate Card/SBP actions without relying on undocumented fields.

    Lava exposes available RUB payment methods on its hosted checkout according
    to the creator account's API-channel payment settings. The current public
    ``POST /api/v3/invoice`` contract doesn't document ``paymentMethod``, so the
    Mini App keeps distinct Card/SBP actions while invoice creation stays on the
    supported contract. The requested action is preserved in UTM metadata.
    """

    import bot.miniapp as miniapp_module

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
            payment_method = _LAVA_MINIAPP_METHODS.get(raw_provider)
            if not payment_method:
                return await current_create_payment(request)

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

            result = await miniapp_module.lava_service.create_invoice(
                email=customer_email,
                offer_id=offer_id,
                currency=lava_currency,
                amount=float(package["price_rub"]),
                buyer_language="RU",
                client_utm={
                    "telegram_id": str(telegram_id),
                    "order_id": order_id,
                    "package_id": str(package_id),
                    "requested_payment_method": payment_method,
                },
            )

            if not result or not result.get("ok"):
                message = _payment_error_message(result)
                miniapp_module.logger.warning(
                    "Lava invoice rejected user=%s package=%s requested_method=%s: %s",
                    telegram_id,
                    package_id,
                    payment_method,
                    message,
                )
                return web.json_response(
                    {"ok": False, "error": message},
                    status=502,
                )

            payment_id = miniapp_module.lava_service.extract_invoice_id(result)
            payment_url = miniapp_module.lava_service.extract_payment_url(result)
            if not payment_id or not payment_url:
                return web.json_response(
                    {"ok": False, "error": "Lava не вернула ссылку на оплату"},
                    status=502,
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
                log_message="Mini App Lava payment creation failed",
            )

    miniapp_module.miniapp_create_payment = create_payment_with_explicit_lava_method
    miniapp_module._lava_payment_methods_compat_installed = True
