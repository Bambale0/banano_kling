"""Route Mini App Card/SBP actions through the active RUB checkout provider."""

from __future__ import annotations

from functools import wraps
from typing import Any

from aiohttp import web

from bot.services.lava_service import normalize_lava_customer_email
from bot.services.freekassa_service import (
    FREEKASSA_CARD_RUB_METHOD_ID,
    FREEKASSA_SBP_METHOD_ID,
    freekassa_service,
)


_LAVA_MINIAPP_METHODS = {
    "lava_card": FREEKASSA_CARD_RUB_METHOD_ID,
    "lava_sbp": FREEKASSA_SBP_METHOD_ID,
}


def _request_ip(request: web.Request) -> str:
    real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if real_ip:
        return real_ip
    forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return str(request.remote or "").strip()


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


def install_miniapp_lava_payment_methods() -> None:
    """Keep legacy Mini App actions working after RUB checkout moved to KASSA."""

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
            payment_system_id = _LAVA_MINIAPP_METHODS.get(raw_provider)
            if not payment_system_id:
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

            if not freekassa_service.api_enabled:
                return web.json_response(
                    {"ok": False, "error": "KASSA временно недоступна"},
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

            customer_ip = _request_ip(request)
            if not customer_ip:
                return web.json_response(
                    {"ok": False, "error": "Не удалось определить IP для оплаты"},
                    status=400,
                )

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
                    {"ok": False, "error": "Payment already exists"},
                    status=409,
                )

            result = await freekassa_service.create_payment(
                amount_rub=float(package["price_rub"]),
                order_id=order_id,
                description=f"Покупка {total_credits} бананов ({package['name']})",
                return_url=miniapp_module.config.YOOKASSA_RETURN_URL
                or miniapp_module.config.mini_app_url,
                notification_url=miniapp_module.config.freekassa_notification_url,
                email=customer_email,
                customer_ip=customer_ip,
                payment_system_id=payment_system_id,
            )

            if not result or not result.get("ok"):
                await miniapp_module.update_transaction_status(order_id, "failed")
                return web.json_response(
                    {"ok": False, "error": _payment_error_message(result)},
                    status=500,
                )

            payment_id = str(result.get("payment_id") or "").strip()
            payment_url = str(result.get("payment_url") or "").strip()
            if not payment_id or not payment_url:
                await miniapp_module.update_transaction_status(order_id, "failed")
                return web.json_response(
                    {"ok": False, "error": "Failed to get KASSA payment link"},
                    status=500,
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
                log_message="Mini App explicit Lava payment creation failed",
            )

    miniapp_module.miniapp_create_payment = create_payment_with_explicit_lava_method
    miniapp_module._lava_payment_methods_compat_installed = True
