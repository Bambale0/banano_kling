#!/usr/bin/env bash
set -euo pipefail

echo "Applying full Lava integration..."

python3 <<'PY'
from pathlib import Path

# =========================
# bot/config.py
# =========================
path = Path("bot/config.py")
text = path.read_text(encoding="utf-8")

if "LAVA_API_KEY" not in text:
    marker = '''    CRYPTOBOT_WEBHOOK_PATH: str = os.getenv(
        "CRYPTOBOT_WEBHOOK_PATH", "/cryptobot/webhook"
    )
'''
    insert = marker + '''
    # Lava.top payments
    LAVA_API_KEY: str = os.getenv("LAVA_API_KEY", "")
    LAVA_API_BASE_URL: str = os.getenv("LAVA_API_BASE_URL", "https://gate.lava.top")
    LAVA_WEBHOOK_PATH: str = os.getenv("LAVA_WEBHOOK_PATH", "/lava/webhook")
    LAVA_DEFAULT_EMAIL: str = os.getenv("LAVA_DEFAULT_EMAIL", "buyer@example.com")
    LAVA_OFFER_ID_MINI: str = os.getenv("LAVA_OFFER_ID_MINI", "")
    LAVA_OFFER_ID_START: str = os.getenv("LAVA_OFFER_ID_START", "")
    LAVA_OFFER_ID_OPTIMAL: str = os.getenv("LAVA_OFFER_ID_OPTIMAL", "")
    LAVA_OFFER_ID_PRO: str = os.getenv("LAVA_OFFER_ID_PRO", "")
    LAVA_OFFER_ID_STUDIO: str = os.getenv("LAVA_OFFER_ID_STUDIO", "")
    LAVA_OFFER_ID_BUSINESS: str = os.getenv("LAVA_OFFER_ID_BUSINESS", "")
'''
    text = text.replace(marker, insert)

text = text.replace(
    'if self.PAYMENT_PROVIDER in {"cryptobot", "yookassa", "tbank"}:',
    'if self.PAYMENT_PROVIDER in {"cryptobot", "lava", "yookassa", "tbank"}:',
)

if "def lava_notification_url" not in text:
    marker = '''    @property
    def cryptobot_notification_url(self) -> str:
        path = self.CRYPTOBOT_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"
'''
    insert = marker + '''
    @property
    def lava_notification_url(self) -> str:
        path = self.LAVA_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    def lava_offer_id_for_package(self, package_id: str) -> str:
        mapping = {
            "mini": self.LAVA_OFFER_ID_MINI,
            "start": self.LAVA_OFFER_ID_START,
            "optimal": self.LAVA_OFFER_ID_OPTIMAL,
            "pro": self.LAVA_OFFER_ID_PRO,
            "studio": self.LAVA_OFFER_ID_STUDIO,
            "business": self.LAVA_OFFER_ID_BUSINESS,
        }
        return mapping.get(package_id, "")
'''
    text = text.replace(marker, insert)

path.write_text(text, encoding="utf-8")


# =========================
# bot/handlers/payments.py
# =========================
path = Path("bot/handlers/payments.py")
text = path.read_text(encoding="utf-8")

if "from bot.services.lava_service import lava_service" not in text:
    text = text.replace(
        "from bot.services.cryptobot_service import cryptobot_service\n",
        "from bot.services.cryptobot_service import cryptobot_service\n"
        "from bot.services.lava_service import lava_service\n",
    )

text = text.replace(
    "Оплата выполняется через CryptoBot.",
    "Оплата выполняется через выбранного платёжного провайдера.",
)

old_start = '''async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт инвойс в CryptoBot."""
    if not cryptobot_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: CryptoBot не настроен.\\n"
            "Проверьте переменную окружения <code>CRYPTOBOT_API_TOKEN</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return
'''
new_start = '''async def initiate_payment(callback: types.CallbackQuery):
    """Создаёт инвойс у выбранного платёжного провайдера."""
    provider = config.payment_provider

    if provider == "lava" and not lava_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: Lava не настроена.\\n"
            "Проверьте переменную окружения <code>LAVA_API_KEY</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    if provider != "lava" and not cryptobot_service.enabled:
        await callback.message.edit_text(
            "Не удалось создать оплату: CryptoBot не настроен.\\n"
            "Проверьте переменную окружения <code>CRYPTOBOT_API_TOKEN</code>.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return
'''
text = text.replace(old_start, new_start)

old_invoice = '''    result = await cryptobot_service.create_invoice(
        amount_rub=float(package["price_rub"]),
        description=description,
        order_id=order_id,
        paid_btn_url=success_url,
    )

    if not result or not result.get("ok"):
        error_msg = (
            (result or {}).get("error")
            or (result or {}).get("message")
            or "Не удалось создать инвойс"
        )
        await callback.message.edit_text(
            "Не удалось создать платёж.\\n" f"Причина: <code>{error_msg}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    invoice = result.get("result") or {}
    invoice_id = str(invoice.get("invoice_id"))
    payment_url = (
        invoice.get("bot_invoice_url")
        or invoice.get("mini_app_invoice_url")
        or invoice.get("web_app_invoice_url")
    )

    if not invoice_id or not payment_url:
        await callback.message.edit_text(
            "Не удалось получить ссылку на оплату от CryptoBot.",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(callback.from_user.id)
    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=invoice_id,
        provider="cryptobot",
        credits=total_credits,
        amount_rub=float(package["price_rub"]),
        status="pending",
    )
'''
new_invoice = '''    if provider == "lava":
        offer_id = config.lava_offer_id_for_package(package_id)
        if not offer_id:
            await callback.message.edit_text(
                "Не удалось создать оплату: для пакета не задан Lava offerId.\\n"
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
        result = await cryptobot_service.create_invoice(
            amount_rub=float(package["price_rub"]),
            description=description,
            order_id=order_id,
            paid_btn_url=success_url,
        )

    if not result or not result.get("ok"):
        error_msg = (
            (result or {}).get("error")
            or (result or {}).get("message")
            or (result or {}).get("raw")
            or "Не удалось создать инвойс"
        )
        await callback.message.edit_text(
            "Не удалось создать платёж.\\n" f"Причина: <code>{error_msg}</code>",
            reply_markup=get_back_keyboard("menu_topup"),
            parse_mode="HTML",
        )
        return

    if provider == "lava":
        invoice_id = lava_service.extract_invoice_id(result)
        payment_url = lava_service.extract_payment_url(result)
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
'''
text = text.replace(old_invoice, new_invoice)

text = text.replace(
    '''        "💳 <b>Оплата через CryptoBot</b>\\n"''',
    '''        f"💳 <b>Оплата через {'Lava' if provider == 'lava' else 'CryptoBot'}</b>\\n"''',
)

text = text.replace(
    '''        "Нажмите кнопку ниже и завершите оплату в CryptoBot.",''',
    '''        "Нажмите кнопку ниже и завершите оплату.",''',
)

old_check = '''    if not cryptobot_service.enabled:
        await callback.answer("Платёжный сервис временно недоступен", show_alert=True)
        return

    invoice = await cryptobot_service.get_invoice(transaction.payment_id)
    status = (invoice or {}).get("status", "")
    paid = status == "paid"
'''
new_check = '''    if transaction.provider == "lava":
        if not lava_service.enabled:
            await callback.answer("Платёжный сервис временно недоступен", show_alert=True)
            return

        invoice = await lava_service.get_invoice(transaction.payment_id)
        status = (invoice or {}).get("status", "")
        paid = status == "completed"
    else:
        if not cryptobot_service.enabled:
            await callback.answer("Платёжный сервис временно недоступен", show_alert=True)
            return

        invoice = await cryptobot_service.get_invoice(transaction.payment_id)
        status = (invoice or {}).get("status", "")
        paid = status == "paid"
'''
text = text.replace(old_check, new_check)

if "async def handle_lava_webhook" not in text:
    text += r'''


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
            logger.warning("Cannot resolve telegram_id for user_id=%s", transaction.user_id)
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        await update_transaction_status(order_id, "completed")
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )

        bonus_text = ""
        if referral_bonus.get("mode") == "partner":
            bonus_text = f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
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
                logger.warning("Skipping Lava notification for user %s: %s", telegram_id, e)
            else:
                logger.error("Failed to notify user %s: %s", telegram_id, e)

        return web.Response(status=200)

    except Exception as e:
        logger.exception("Error processing Lava webhook: %s", e)
        return web.Response(status=200)
'''

path.write_text(text, encoding="utf-8")


# =========================
# bot/main.py
# =========================
path = Path("bot/main.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
    "from bot.handlers.payments import handle_cryptobot_webhook\n",
    "from bot.handlers.payments import handle_cryptobot_webhook, handle_lava_webhook\n",
)

if "await lava_service.close()" not in text:
    text = text.replace(
'''    try:
        from bot.services.cryptobot_service import cryptobot_service

        await cryptobot_service.close()
    except Exception:
        logger.exception("Failed to close CryptoBot session")
''',
'''    try:
        from bot.services.cryptobot_service import cryptobot_service

        await cryptobot_service.close()
    except Exception:
        logger.exception("Failed to close CryptoBot session")

    try:
        from bot.services.lava_service import lava_service

        await lava_service.close()
    except Exception:
        logger.exception("Failed to close Lava session")
''',
)

if "config.LAVA_WEBHOOK_PATH" not in text:
    variants = [
        (
            "app.router.add_post(config.CRYPTOBOT_WEBHOOK_PATH, handle_cryptobot_webhook)",
            "app.router.add_post(config.CRYPTOBOT_WEBHOOK_PATH, handle_cryptobot_webhook)\n        app.router.add_post(config.LAVA_WEBHOOK_PATH, handle_lava_webhook)",
        ),
        (
            "web_app.router.add_post(config.CRYPTOBOT_WEBHOOK_PATH, handle_cryptobot_webhook)",
            "web_app.router.add_post(config.CRYPTOBOT_WEBHOOK_PATH, handle_cryptobot_webhook)\n        web_app.router.add_post(config.LAVA_WEBHOOK_PATH, handle_lava_webhook)",
        ),
    ]

    for old, new in variants:
        if old in text:
            text = text.replace(old, new)
            break
    else:
        text += "\n# TODO: register Lava webhook route manually: app.router.add_post(config.LAVA_WEBHOOK_PATH, handle_lava_webhook)\n"

path.write_text(text, encoding="utf-8")
PY

python3 -m py_compile bot/config.py bot/services/lava_service.py bot/handlers/payments.py bot/main.py

echo "Lava integration patch applied."
echo "Now check git diff before commit."
