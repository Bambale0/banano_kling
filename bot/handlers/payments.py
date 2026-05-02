import json
import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

from bot.config import config
from bot.database import (
    add_credits,
    create_miniapp_notification,
    create_transaction,
    credit_first_payment_referral_bonus,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    update_transaction_status,
)
from bot.keyboards import (
    get_back_keyboard,
    get_main_menu_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_method_keyboard,
    get_payment_packages_keyboard,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.lava_service import lava_service
from bot.services.preset_manager import preset_manager
from bot.services.yookassa_service import yookassa_service

logger = logging.getLogger(__name__)
router = Router()


def _is_ignored_telegram_error(error: Exception) -> bool:
    error_msg = str(error).lower()
    return (
        "chat not found" in error_msg
        or "bot was blocked" in error_msg
        or "user is deactivated" in error_msg
        or "bot can't initiate conversation" in error_msg
        or "forbidden" in error_msg
        or "chat is deactivated" in error_msg
    )


async def _notify_user(bot: Bot, telegram_id: int, text: str, *, parse_mode=None):
    try:
        await bot.send_message(telegram_id, text, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if _is_ignored_telegram_error(e):
            raise
        raise


async def _render_topup_menu(message: types.Message):
    packages = preset_manager.get_packages()
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через выбранного платёжного провайдера.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
    )

    await message.edit_text(
        text,
        reply_markup=get_payment_packages_keyboard(packages),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message)


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method(callback: types.CallbackQuery):
    """Показывает доступные способы оплаты для выбранного пакета."""
    package_id = callback.data.replace("choose_pay_", "", 1)
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    has_yookassa = yookassa_service.enabled
    has_crypto = cryptobot_service.enabled

    if not has_yookassa and not has_crypto:
        await callback.message.edit_text(
            "❌ Платёжные системы временно недоступны.\nОбратитесь в поддержку.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    if has_yookassa and not has_crypto:
        await callback.answer()
        await callback.bot.answer_callback_query(
            callback.id, text="Перенаправляем на оплату…"
        )
        fake = callback.model_copy(update={"data": f"buy_yookassa_{package_id}"})
        return await initiate_payment(fake)

    if has_crypto and not has_yookassa:
        await callback.answer()
        fake = callback.model_copy(update={"data": f"buy_crypto_{package_id}"})
        return await initiate_payment(fake)

    total_credits = package["credits"] + package.get("bonus_credits", 0)
    await callback.message.edit_text(
        f"💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{package['name']}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package['price_rub']}</code>₽",
        reply_markup=get_payment_method_keyboard(package_id, has_yookassa, has_crypto),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт инвойс у выбранного платёжного провайдера."""
    payload = callback.data.replace("buy_", "", 1)
    if payload.startswith("yookassa_"):
        provider = "yookassa"
    elif payload.startswith("crypto_"):
        provider = "cryptobot"
    else:
        provider = config.payment_provider

    if provider == "lava" and not lava_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: Lava не настроена.\n"
            "Проверьте переменную окружения <code>LAVA_API_KEY</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    if provider == "yookassa" and not yookassa_service.enabled:
        await callback.message.edit_text(
            "YooKassa временно недоступна. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    if provider in ("cryptobot", "cryptopay") and not cryptobot_service.enabled:
        await callback.message.edit_text(
            "CryptoBot временно недоступен. Попробуйте другой способ оплаты.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    payload = callback.data.replace("buy_", "", 1)
    if payload.startswith("yookassa_"):
        package_id = payload.replace("yookassa_", "", 1)
    elif payload.startswith("crypto_"):
        package_id = payload.replace("crypto_", "", 1)
    elif "_" in payload:
        package_id = payload.split("_", 1)[1]
    else:
        package_id = payload
    package = preset_manager.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    order_id = f"{callback.from_user.id}_{int(time.time())}_{package_id}"

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"

    total_credits = package["credits"] + package.get("bonus_credits", 0)
    description = f"Покупка {total_credits} бананов ({package['name']})"

    if provider == "lava":
        offer_id = config.lava_offer_id_for_package(package_id)
        if not offer_id:
            await callback.message.edit_text(
                "Не удалось создать оплату: для пакета не задан Lava offerId.\n"
                f"Проверьте переменную окружения <code>LAVA_OFFER_ID_{package_id.upper()}</code>.",
                reply_markup=get_back_keyboard("menu_topup"),
                parse_mode="HTML",
            )
            return

        result = await lava_service.create_invoice(
            email=config.LAVA_DEFAULT_EMAIL,
            offer_id=offer_id,
            currency="RUB",
            amount=float(package["price_rub"]),
            buyer_language="RU",
            client_utm={
                "telegram_id": str(callback.from_user.id),
                "order_id": order_id,
                "package_id": package_id,
            },
        )
    else:
        if provider == "yookassa":
            if not yookassa_service.enabled:
                await callback.message.edit_text(
                    "Не удалось создать оплату: YooKassa не настроена.\n"
                    "Проверьте переменные окружения YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.",
                    reply_markup=get_back_keyboard("back_main"),
                    parse_mode="HTML",
                )
                return

            result = await yookassa_service.create_payment(
                amount_rub=float(package["price_rub"]),
                order_id=order_id,
                description=description,
                return_url=success_url,
                notification_url=config.yookassa_notification_url,
            )
        else:
            result = await cryptobot_service.create_invoice(
                amount_rub=float(package["price_rub"]),
                description=description,
                order_id=order_id,
                paid_btn_url=success_url,
            )

    # Normalize success check for different providers
    creation_ok = False
    if provider == "lava":
        creation_ok = bool(result and result.get("ok"))
    elif provider == "yookassa":
        # yookassa_service returns {'Success': True, 'PaymentId': ..., 'PaymentURL': ...}
        creation_ok = bool(
            result and (result.get("Success") or result.get("PaymentId"))
        )
    else:
        creation_ok = bool(result and result.get("ok"))

    if not creation_ok:
        error_msg = (
            (result or {}).get("error")
            or (result or {}).get("message")
            or (result or {}).get("raw")
            or (result or {}).get("Message")
            or "Не удалось создать инвойс"
        )
        await callback.message.edit_text(
            "Не удалось создать платёж.\n" f"Причина: <code>{error_msg}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    if provider == "lava":
        invoice_id = lava_service.extract_invoice_id(result)
        payment_url = lava_service.extract_payment_url(result)
    elif provider == "yookassa":
        invoice_id = result.get("PaymentId") if result else None
        payment_url = result.get("PaymentURL") if result else None
    else:
        invoice = result.get("result") or {}
        invoice_id = str(invoice.get("invoice_id"))
        payment_url = (
            invoice.get("bot_invoice_url")
            or invoice.get("mini_app_invoice_url")
            or invoice.get("web_app_invoice_url")
        )

    if not invoice_id or not payment_url:
        await callback.message.edit_text(
            f"Не удалось получить ссылку на оплату от {provider}.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(callback.from_user.id)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=invoice_id,
        provider=provider,
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
    )

    bonus_text = ""
    if package.get("bonus_credits", 0) > 0:
        bonus_text = f"\n• Бонус: <code>{package['bonus_credits']}</code> бананов"

    provider_label = {
        "lava": "Lava",
        "yookassa": "YooKassa (банковская карта)",
        "cryptobot": "CryptoBot (криптовалюта)",
    }.get(provider, provider.capitalize())

    await callback.message.edit_text(
        f"💳 <b>Оплата через {provider_label}</b>\n"
        f"• Пакет: <code>{package['name']}</code>\n"
        f"• Бананов: <code>{total_credits}</code>{bonus_text}\n"
        f"• Сумма: <code>{package['price_rub']}</code> ₽\n\n"
        "Нажмите кнопку ниже и завершите оплату.",
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    """Ручная проверка статуса платежа в CryptoBot."""
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            "✅ <b>Оплата подтверждена</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    if transaction.provider == "lava":
        if not lava_service.enabled:
            await callback.answer(
                "Платёжный сервис временно недоступен", show_alert=True
            )
            return

        invoice = await lava_service.get_invoice(transaction.payment_id)
        status = (invoice or {}).get("status", "")
        paid = status == "completed"
    elif transaction.provider == "yookassa":
        if not yookassa_service.enabled:
            await callback.answer(
                "Платёжный сервис временно недоступен", show_alert=True
            )
            return

        invoice = await yookassa_service.get_payment(transaction.payment_id)
        status = (invoice or {}).get("status", "")
        paid = bool((invoice or {}).get("paid"))
    else:
        if not cryptobot_service.enabled:
            await callback.answer(
                "Платёжный сервис временно недоступен", show_alert=True
            )
            return

        invoice = await cryptobot_service.get_invoice(transaction.payment_id)
        status = (invoice or {}).get("status", "")
        paid = status == "paid"

    if not paid:
        await callback.answer("Платёж ещё в обработке", show_alert=True)
        return

    user = await get_or_create_user(transaction.user_id)
    await add_credits(user.telegram_id, transaction.credits)
    await update_transaction_status(order_id, "completed")
    referral_bonus = await credit_first_payment_referral_bonus(
        user.telegram_id, transaction.credits, transaction.amount_rub
    )

    bonus_text = ""
    if referral_bonus.get("mode") == "partner":
        bonus_text = f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
    elif referral_bonus.get("mode") == "banana":
        bonus_text = (
            f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"
        )

    await callback.message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n"
        f"• Начислено: <code>{transaction.credits}</code> бананов\n"
        f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Платёж отменён. Вы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def handle_cryptobot_webhook(request: web.Request):
    """Webhook updates from Crypto Pay API."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        signature = request.headers.get("crypto-pay-api-signature", "")
        if signature and not cryptobot_service.verify_webhook_signature(
            raw_body, signature
        ):
            logger.warning("Invalid CryptoBot webhook signature")
            return web.Response(status=403)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return web.Response(status=200)

        if data.get("update_type") != "invoice_paid":
            return web.Response(status=200)

        invoice = data.get("payload") or {}
        if (invoice.get("status") or "") != "paid":
            return web.Response(status=200)

        order_id = invoice.get("payload")
        if not order_id:
            logger.warning("CryptoBot webhook has no invoice payload order_id")
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction or transaction.status == "completed":
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = (
                f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
            )
        elif referral_bonus.get("mode") == "banana":
            bonus_text = f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping CryptoBot notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        # Создаём уведомление для мини‑аппа (чтобы UI показал результат при следующем bootstrap)
        try:
            note = f"✅ Оплата успешно обработана — {transaction.credits} бананов за {transaction.amount_rub} ₽"
            await create_miniapp_notification(transaction.user_id, note)
        except Exception:
            logger.exception(
                "Failed to create miniapp notification for order %s", order_id
            )

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing CryptoBot webhook: %s", e)
        return web.Response(status=200)


async def handle_lava_webhook(request: web.Request):
    """Webhook updates from Lava.top."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.warning("Lava webhook received invalid JSON")
            return web.Response(status=200)

        logger.info("Lava webhook payload: %s", data)

        if not lava_service.is_success_webhook(data):
            return web.Response(status=200)

        contract_id = lava_service.webhook_contract_id(data)
        if not contract_id:
            logger.warning("Lava webhook has no contractId")
            return web.Response(status=200)

        import aiosqlite

        from bot.database import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT order_id FROM transactions WHERE payment_id = ? AND provider = ? LIMIT 1",
                (contract_id, "lava"),
            )
            row = await cursor.fetchone()

        if not row:
            logger.warning("Lava transaction not found for contractId=%s", contract_id)
            return web.Response(status=200)

        order_id = row["order_id"]
        transaction = await get_transaction_by_order(order_id)
        if not transaction or transaction.status == "completed":
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = (
                f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
            )
        elif referral_bonus.get("mode") == "banana":
            bonus_text = f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping Lava notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing Lava webhook: %s", e)
        return web.Response(status=200)


async def handle_yookassa_webhook(request: web.Request):
    """Webhook updates from YooKassa."""
    try:
        raw_body = await request.read()
        if not raw_body:
            return web.Response(status=200)

        # Validate webhook signature if configured
        try:
            secret = config.YOOKASSA_WEBHOOK_SECRET
            if secret:
                import base64
                import hashlib
                import hmac

                verified = False
                # Common header names YooKassa might send
                candidate_headers = [
                    request.headers.get("X-Webhook-Signature"),
                    request.headers.get("X-Checkout-Signature"),
                    request.headers.get("X-Signature"),
                ]
                # Compute HMAC-SHA256
                digest = hmac.new(secret.encode(), raw_body, hashlib.sha256)
                hex_expected = digest.hexdigest()
                b64_expected = base64.b64encode(digest.digest()).decode()

                for hdr in candidate_headers:
                    if not hdr:
                        continue
                    if hmac.compare_digest(hdr, hex_expected) or hmac.compare_digest(
                        hdr, b64_expected
                    ):
                        verified = True
                        break

                if not verified:
                    logger.warning(
                        "Rejected YooKassa webhook: invalid signature headers=%s",
                        {
                            k: v
                            for k, v in request.headers.items()
                            if "yookassa" in k.lower() or "signature" in k.lower()
                        },
                    )
                    return web.Response(status=200)
        except Exception:
            logger.exception("Error while validating YooKassa webhook signature")
            return web.Response(status=200)

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            logger.warning("YooKassa webhook received invalid JSON")
            return web.Response(status=200)

        # Try to extract payment id from common YooKassa payload shapes
        payment_id = None
        obj = data.get("object") or {}
        if isinstance(obj, dict):
            payment_id = obj.get("id") or _extract_first(obj, ["id", "payment_id"])

        # Fallback: sometimes payload wraps payment under 'payment'
        if not payment_id:
            payment_id = _extract_first(data, ["payment_id", "id"])  # recursive search

        if not payment_id:
            logger.warning("YooKassa webhook: no payment id found in payload")
            return web.Response(status=200)

        # Fetch payment details from YooKassa SDK
        payment = await yookassa_service.get_payment(payment_id)
        if not payment:
            return web.Response(status=200)

        # Try to resolve order_id from metadata, else lookup by payment_id in DB
        order_id = yookassa_service.extract_order_id(
            payment.get("Raw")
            if isinstance(payment.get("Raw"), dict)
            else payment.get("Raw", {})
        )
        if not order_id:
            # DB lookup by payment_id
            import aiosqlite

            from bot.database import DATABASE_PATH

            async with aiosqlite.connect(DATABASE_PATH) as db_conn:
                db_conn.row_factory = aiosqlite.Row
                cursor = await db_conn.execute(
                    "SELECT order_id FROM transactions WHERE payment_id = ? AND provider = ? LIMIT 1",
                    (payment_id, "yookassa"),
                )
                row = await cursor.fetchone()
                if row:
                    order_id = row["order_id"]

        if not order_id:
            logger.warning(
                "YooKassa webhook: cannot resolve order_id for payment %s", payment_id
            )
            return web.Response(status=200)

        transaction = await get_transaction_by_order(order_id)
        if not transaction or transaction.status == "completed":
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        paid = bool(payment.get("paid")) or (payment.get("status") or "").lower() in (
            "succeeded",
            "paid",
            "captured",
        )

        if not paid:
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = (
                f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
            )
        elif referral_bonus.get("mode") == "banana":
            bonus_text = f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"

        try:
            await _notify_user(
                request.app["bot"],
                telegram_id,
                "✅ <b>Оплата успешно обработана</b>\n"
                f"• Начислено: <code>{transaction.credits}</code> бананов\n"
                f"• Сумма: <code>{transaction.amount_rub}</code> ₽{bonus_text}",
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if _is_ignored_telegram_error(e):
                logger.warning(
                    "Skipping YooKassa notification for user %s: %s", telegram_id, e
                )
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing YooKassa webhook: %s", e)
        return web.Response(status=200)
