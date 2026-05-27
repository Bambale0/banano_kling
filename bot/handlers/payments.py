import json
import logging
import time
from datetime import datetime, timedelta


from typing import Any
from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiohttp import web

from bot.config import config
from bot.database import (
    PROMO_BONUS_BY_CREDITS,
    add_credits,
    create_miniapp_notification,
    create_transaction,
    credit_first_payment_referral_bonus,
    get_promo_bonus_for_credits,
    get_promo_code_by_code,
    get_or_create_user,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    normalize_promo_code,
    record_promo_redemption,
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
from bot.states import PaymentStates

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


def _build_bonus_text(referral_bonus: dict[str, Any]) -> str:
    if referral_bonus.get("mode") == "partner":
        return f"\n🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽"
    if referral_bonus.get("mode") == "banana":
        return f"\n🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> бананов"
    return ""


def _build_promo_rules_text() -> str:
    return "\n".join(
        f"• {credits}🍌 → +<code>{bonus}</code>🍌"
        for credits, bonus in PROMO_BONUS_BY_CREDITS.items()
    )


def _build_promo_bonus_text(promo_bonus: dict[str, Any] | None) -> str:
    if not promo_bonus or int(promo_bonus.get("bonus_credits") or 0) <= 0:
        return ""
    code = normalize_promo_code(promo_bonus.get("code"))
    code_part = f" <code>{code}</code>" if code else ""
    return (
        f"\n🎟 Промокод{code_part}: +<code>{promo_bonus['bonus_credits']}</code> бананов"
    )


def _transaction_promo_text(transaction) -> str:
    if int(getattr(transaction, "promo_bonus_credits", 0) or 0) <= 0:
        return ""
    return _build_promo_bonus_text(
        {
            "code": getattr(transaction, "promo_code", "") or "",
            "bonus_credits": getattr(transaction, "promo_bonus_credits", 0),
        }
    )


async def _get_selected_promo(state: FSMContext | None):
    if state is None:
        return None
    data = await state.get_data()
    code = data.get("promo_code")
    if not code:
        return None
    promo = await get_promo_code_by_code(str(code), active_only=True)
    if not promo:
        await state.update_data(promo_code=None, promo_code_id=None)
        return None
    return promo


def _promo_bonus_for_package(promo, package: dict[str, Any]) -> int:
    if not promo:
        return 0
    return get_promo_bonus_for_credits(package.get("credits"))


def _extract_first(obj: Any, keys: list[str] | tuple[str, ...]) -> Any:
    """Recursively find the first non-empty value for any key in a webhook payload."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return value
        for value in obj.values():
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _extract_first(value, keys)
            if found not in (None, ""):
                return found
    return None


async def _resolve_payment_state(transaction) -> dict[str, Any]:
    provider = (getattr(transaction, "provider", None) or "cryptobot").lower()
    payment_id = getattr(transaction, "payment_id", None)

    if not payment_id:
        return {"provider": provider, "status": "", "paid": False, "failed": False}

    try:
        if provider == "lava":
            if not lava_service.enabled:
                return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
            invoice = await lava_service.get_invoice(payment_id)
            status = str((invoice or {}).get("status") or "").lower()
            return {
                "provider": provider,
                "status": status,
                "paid": status == "completed",
                "failed": status in {"cancelled", "canceled", "failed", "expired"},
                "invoice": invoice,
            }

        if provider == "yookassa":
            if not yookassa_service.enabled:
                return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
            invoice = await yookassa_service.get_payment(payment_id)
            status = str((invoice or {}).get("status") or "").lower()
            paid = bool((invoice or {}).get("paid")) or status in {"succeeded", "paid", "captured"}
            failed = status in {"canceled", "cancelled", "failed", "rejected"}
            return {
                "provider": provider,
                "status": status,
                "paid": paid,
                "failed": failed,
                "invoice": invoice,
            }

        if not cryptobot_service.enabled:
            return {"provider": provider, "status": "service_disabled", "paid": False, "failed": False}
        invoice = await cryptobot_service.get_invoice(payment_id)
        status = str((invoice or {}).get("status") or "").lower()
        failed = status in {"expired", "cancelled", "canceled", "invalid"}
        if status == "active" and _is_pending_past_ttl(transaction):
            failed = True
            status = "expired_local_ttl"
        return {
            "provider": provider,
            "status": status,
            "paid": status == "paid",
            "failed": failed,
            "invoice": invoice,
        }
    except Exception as exc:
        logger.exception(
            "Payment state resolve failed for order=%s provider=%s: %s",
            getattr(transaction, "order_id", "?"),
            provider,
            exc,
        )
        return {
            "provider": provider,
            "status": "lookup_error",
            "paid": False,
            "failed": False,
            "error": str(exc),
        }


def _is_pending_past_ttl(transaction, ttl_days: int | None = None) -> bool:
    ttl_days = ttl_days or max(1, int(config.CRYPTOBOT_PENDING_TTL_DAYS or 7))
    created_at = getattr(transaction, "created_at", None)
    if not created_at:
        return False

    try:
        cutoff = datetime.now(created_at.tzinfo) - timedelta(days=ttl_days)
    except Exception:
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    return created_at < cutoff


async def cleanup_stale_cryptobot_pending(limit: int = 500) -> dict[str, int]:
    import aiosqlite

    from bot.database import DATABASE_PATH

    stats = {"checked": 0, "failed": 0, "kept": 0}

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT order_id, payment_id, created_at FROM transactions WHERE provider = 'cryptobot' AND status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )).fetchall()

    for row in rows:
        stats["checked"] += 1
        created_at_raw = row["created_at"]
        try:
            created_at = datetime.fromisoformat(created_at_raw)
        except Exception:
            stats["kept"] += 1
            continue

        stub = type("TxStub", (), {
            "created_at": created_at,
            "order_id": row["order_id"],
        })()
        if not _is_pending_past_ttl(stub):
            stats["kept"] += 1
            continue

        payment_id = row["payment_id"]
        invoice = await cryptobot_service.get_invoice(payment_id)
        status = str((invoice or {}).get("status") or "").lower()

        if status in {"paid"}:
            stats["kept"] += 1
            continue

        if status in {"active", "expired", "cancelled", "canceled", "invalid", ""}:
            if await update_transaction_status(row["order_id"], "failed"):
                stats["failed"] += 1
            else:
                stats["kept"] += 1
            continue

        stats["kept"] += 1

    logger.info(
        "CryptoBot stale pending cleanup finished: checked=%s failed=%s kept=%s ttl_days=%s",
        stats["checked"],
        stats["failed"],
        stats["kept"],
        config.CRYPTOBOT_PENDING_TTL_DAYS,
    )
    return stats


async def _complete_transaction(order_id: str) -> dict[str, Any]:
    transaction = await get_transaction_by_order(order_id)
    if not transaction:
        return {"ok": False, "reason": "not_found"}

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if not telegram_id:
        return {"ok": False, "reason": "telegram_not_found", "transaction": transaction}

    updated = await update_transaction_status(order_id, "completed")
    if not updated:
        return {
            "ok": True,
            "already_completed": True,
            "transaction": transaction,
            "telegram_id": telegram_id,
            "referral_bonus": {},
            "promo_bonus": {},
        }

    await add_credits(telegram_id, transaction.credits)
    referral_bonus = await credit_first_payment_referral_bonus(
        telegram_id, transaction.credits, transaction.amount_rub
    )
    promo_bonus = await record_promo_redemption(transaction)
    return {
        "ok": True,
        "already_completed": False,
        "transaction": transaction,
        "telegram_id": telegram_id,
        "referral_bonus": referral_bonus,
        "promo_bonus": promo_bonus,
    }

async def _render_topup_menu(message: types.Message, state: FSMContext | None = None):
    packages = preset_manager.get_packages()
    promo = await _get_selected_promo(state)
    promo_text = ""
    if promo:
        promo_text = (
            f"\n\n🎟 Активный промокод: <code>{promo.code}</code>\n"
            "Бонус будет начислен автоматически по количеству бананов в пакете."
        )
    text = (
        "🍌 <b>Пополнение баланса</b>\n\n"
        "Оплата выполняется через выбранного платёжного провайдера.\n"
        "Выберите пакет бананов ниже.\n\n"
        "<b>Бонусы по промокоду:</b>\n"
        f"{_build_promo_rules_text()}\n\n"
        "<i>Чем больше пакет, тем выгоднее цена за банан.</i>"
        f"{promo_text}"
    )

    await message.edit_text(
        text,
        reply_markup=get_payment_packages_keyboard(packages, promo_active=bool(promo)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() == PaymentStates.waiting_promo_code.state:
        await state.set_state(None)
    await _render_topup_menu(callback.message, state)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery, state: FSMContext):
    if await state.get_state() == PaymentStates.waiting_promo_code.state:
        await state.set_state(None)
    await _render_topup_menu(callback.message, state)


@router.callback_query(F.data == "topup_enter_promo")
async def topup_enter_promo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.waiting_promo_code)
    await callback.message.edit_text(
        "🎟 <b>Промокод</b>\n\n"
        "Отправьте промокод одним сообщением. Он многоразовый: после ввода можно "
        "пополнять баланс с этим кодом снова.\n\n"
        "<b>Бонусы:</b>\n"
        f"{_build_promo_rules_text()}",
        reply_markup=get_back_keyboard("menu_topup"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "topup_remove_promo")
async def topup_remove_promo(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(promo_code=None, promo_code_id=None)
    await state.set_state(None)
    await callback.answer("Промокод убран")
    await _render_topup_menu(callback.message, state)


@router.message(PaymentStates.waiting_promo_code)
async def topup_process_promo(message: types.Message, state: FSMContext):
    code = normalize_promo_code(message.text)
    promo = await get_promo_code_by_code(code, active_only=True)
    if not promo:
        await message.answer(
            "❌ Промокод не найден или выключен. Проверьте написание и отправьте код ещё раз.",
            reply_markup=get_back_keyboard("menu_topup"),
        )
        return

    await state.update_data(promo_code=promo.code, promo_code_id=promo.id)
    await state.set_state(None)

    packages = preset_manager.get_packages()
    await message.answer(
        "✅ <b>Промокод применён</b>\n\n"
        f"Код: <code>{promo.code}</code>\n"
        "Теперь выберите пакет. Бонус добавится автоматически по количеству бананов.\n\n"
        f"{_build_promo_rules_text()}",
        reply_markup=get_payment_packages_keyboard(packages, promo_active=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("choose_pay_"))
async def choose_payment_method(callback: types.CallbackQuery, state: FSMContext):
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
        return await initiate_payment(fake, state)

    if has_crypto and not has_yookassa:
        await callback.answer()
        fake = callback.model_copy(update={"data": f"buy_crypto_{package_id}"})
        return await initiate_payment(fake, state)

    promo = await _get_selected_promo(state)
    package_bonus = int(package.get("bonus_credits", 0) or 0)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = package["credits"] + package_bonus + promo_bonus
    bonus_lines = []
    if package_bonus > 0:
        bonus_lines.append(f"Бонус пакета: <code>{package_bonus}</code>🍌")
    if promo_bonus > 0 and promo:
        bonus_lines.append(
            f"Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code>🍌"
        )
    bonus_text = "\n".join(bonus_lines)
    bonus_text = f"\n{bonus_text}" if bonus_text else ""
    await callback.message.edit_text(
        f"💳 <b>Выберите способ оплаты</b>\n\n"
        f"Пакет: <b>{package['name']}</b>\n"
        f"Бананы: <code>{total_credits}</code>🍌\n"
        f"Сумма: <code>{package['price_rub']}</code>₽"
        f"{bonus_text}",
        reply_markup=get_payment_method_keyboard(package_id, has_yookassa, has_crypto),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_"))
async def initiate_payment(callback: types.CallbackQuery, state: FSMContext):
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

    promo = await _get_selected_promo(state)
    package_bonus = int(package.get("bonus_credits", 0) or 0)
    promo_bonus = _promo_bonus_for_package(promo, package)
    total_credits = package["credits"] + package_bonus + promo_bonus
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
        promo_code_id=promo.id if promo and promo_bonus > 0 else None,
        promo_code=promo.code if promo and promo_bonus > 0 else None,
        promo_bonus_credits=promo_bonus,
    )

    bonus_text = ""
    if package_bonus > 0:
        bonus_text += f"\n• Бонус пакета: <code>{package_bonus}</code> бананов"
    if promo and promo_bonus > 0:
        bonus_text += (
            f"\n• Промокод <code>{promo.code}</code>: +<code>{promo_bonus}</code> бананов"
        )
    elif promo:
        bonus_text += "\n• Промокод применён, но для этой суммы бонуса нет"

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
    """Ручная проверка статуса платежа у текущего провайдера."""
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        promo_text = _transaction_promo_text(transaction)
        await callback.message.edit_text(
            "✅ <b>Оплата подтверждена</b>\n"
            f"• Начислено: <code>{transaction.credits}</code> бананов\n"
            f"• Сумма: <code>{transaction.amount_rub}</code> ₽{promo_text}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    state = await _resolve_payment_state(transaction)
    if state.get("failed"):
        await update_transaction_status(order_id, "failed")
        await callback.answer("Платёж отменён или не прошёл", show_alert=True)
        return

    if not state.get("paid"):
        await callback.answer("Платёж ещё в обработке", show_alert=True)
        return

    result = await _complete_transaction(order_id)
    if not result.get("ok"):
        await callback.answer("Не удалось завершить оплату", show_alert=True)
        return

    if result.get("already_completed"):
        await callback.answer("Оплата уже была зачислена ранее", show_alert=True)
        return

    bonus_text = (
        _build_promo_bonus_text(result.get("promo_bonus") or {})
        + _build_bonus_text(result.get("referral_bonus") or {})
    )
    transaction = result["transaction"]
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
        if not transaction:
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        # Атомарная смена статуса — защита от двойного начисления при повторных вебхуках
        updated = await update_transaction_status(order_id, "completed")
        if not updated:
            logger.info("CryptoBot webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )
        promo_bonus = await record_promo_redemption(transaction)

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

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
            note = (
                f"✅ Оплата успешно обработана — {transaction.credits} бананов "
                f"за {transaction.amount_rub} ₽"
            )
            if promo_bonus:
                note += f" (промокод +{promo_bonus['bonus_credits']}🍌)"
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
        if not transaction:
            return web.Response(status=200)

        telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
        if not telegram_id:
            logger.warning(
                "Cannot resolve telegram_id for user_id=%s", transaction.user_id
            )
            return web.Response(status=200)

        updated = await update_transaction_status(order_id, "completed")
        if not updated:
            logger.info("Lava webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )
        promo_bonus = await record_promo_redemption(transaction)

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

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
        if not transaction:
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

        updated = await update_transaction_status(order_id, "completed")
        if not updated:
            logger.info("YooKassa webhook: order %s already processed, skipping", order_id)
            return web.Response(status=200)

        await add_credits(telegram_id, transaction.credits)
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id, transaction.credits, transaction.amount_rub
        )
        promo_bonus = await record_promo_redemption(transaction)

        bonus_text = _build_promo_bonus_text(promo_bonus) + _build_bonus_text(
            referral_bonus
        )

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
