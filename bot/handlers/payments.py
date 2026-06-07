import logging
import time

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiohttp import web

from bot.config import config
from bot.database import (
    add_credits,
    add_credits_once,
    add_free_generations,
    confirm_recurring_subscription,
    create_transaction,
    credit_first_payment_referral_bonus,
    disable_recurring_subscription,
    get_or_create_user,
    get_recurring_subscription,
    get_telegram_id_by_user_id,
    get_transaction_by_order,
    get_user_credits,
    mark_promo_code_used,
    upsert_recurring_subscription,
    validate_promo_code,
    update_transaction_status,
)
from bot.keyboards import (
    get_back_keyboard,
    get_credit_emoji,
    get_credit_plural,
    get_main_menu_keyboard,
    get_payment_confirmation_keyboard,
    get_payment_packages_keyboard,
    get_support_contact,
)
from bot.services.cryptobot_service import cryptobot_service
from bot.services.admin_config_service import admin_package_config_service
from bot.services.preset_manager import preset_manager
from bot.services.subscription_service import subscription_service
from bot.services.tbank_service import tbank_service
from bot.states import PaymentStates
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
    except TelegramBadRequest as exc:
        if _is_ignored_telegram_error(exc):
            logger.warning(
                "Skipping notification for telegram_id=%s: %s",
                telegram_id,
                exc,
            )
            return
        raise


def _format_bonus_text(referral_bonus: dict) -> str:
    if referral_bonus.get("mode") == "partner":
        return f"🎁 Партнёрский бонус: <code>{referral_bonus['value']}</code> ₽\n"
    if referral_bonus.get("mode") == "banana":
        return f"🎁 Реферальный бонус: <code>{referral_bonus['value']}</code> BoomCoin\n"
    return ""


def _package_id_from_order_id(order_id: str) -> str:
    return order_id.rsplit("_", 1)[-1]


def _subscription_feature_text(package: dict) -> str:
    features = []
    if package.get("photo_limit_text"):
        features.append(package["photo_limit_text"])
    if package.get("includes_pro"):
        features.append("Banana Pro")
    if package.get("video_limit_text"):
        features.append(package["video_limit_text"])
    if package.get("priority"):
        features.append("приоритет")
    if not package.get("video_limit_text"):
        features.append("без видео")
    return ", ".join(features)


def _credit_package_summary(package: dict) -> str:
    total = int(package.get("credits") or 0) + int(package.get("bonus_credits") or 0)
    bonus = int(package.get("bonus_credits") or 0)
    bonus_text = f" (+{bonus} бонус)" if bonus else ""
    return f"• <b>{total} BoomCoin</b> — {package['price_rub']} ₽{bonus_text}"


def _topup_menu_text(packages: list[dict] | None = None) -> str:
    credit_emoji = get_credit_emoji()
    credit_plural = get_credit_plural()
    credit_lines = []
    subscription_lines = []
    packages = packages if packages is not None else preset_manager.get_packages()
    for package in packages:
        if subscription_service.is_subscription_package(package):
            subscription_lines.append(
                f"• <b>{package['name']}</b> — {package['price_rub']} ₽ / "
                f"{package.get('period', 'период')}: {_subscription_feature_text(package)}"
            )
        elif not package.get("hidden"):
            credit_lines.append(_credit_package_summary(package))
    credit_text = "\n".join(credit_lines)
    subscription_text = "\n".join(subscription_lines)
    return (
        f"{credit_emoji} <b>Пополнение баланса</b>\n\n"
        f"<b>{credit_plural}</b>\n"
        "Разовый баланс без срока действия: для видео, доплат и генераций сверх подписки.\n"
        f"{credit_text}\n\n"
        "<b>Подписки</b>\n"
        f"Фото-лимиты по времени + бонусный баланс {credit_plural}. "
        f"После лимита бот продолжит работать за {credit_plural}.\n"
        f"{subscription_text}\n\n"
        "<i>Для старта берите Boom. Для Banana Pro и видео — Pro или Studio.</i>"
    )


def _payment_created_text(
    package: dict,
    total_credits: int,
    *,
    amount_rub: int | float,
    original_amount_rub: int | float | None = None,
    promo_code: str | None = None,
    promo_discount_percent: int = 0,
    recurring_enabled: bool = False,
) -> str:
    credit_emoji = get_credit_emoji()
    credit_plural = get_credit_plural()
    bonus_text = ""
    if package.get("bonus_credits", 0) > 0:
        bonus_text = f" (+{package['bonus_credits']} бонус)"
    if promo_code and promo_discount_percent and original_amount_rub:
        price_text = (
            f"💰 Сумма: <s>{original_amount_rub}</s> ₽ → <code>{amount_rub}</code> ₽\n"
            f"🎟 Промокод: <code>{promo_code}</code> −{promo_discount_percent}%"
        )
    else:
        price_text = f"💰 Сумма: <code>{amount_rub}</code> ₽"

    feature_lines = []
    if package.get("period"):
        feature_lines.append(f"⏳ Срок: <code>{package['period']}</code>")
    if package.get("photo_limit_text"):
        feature_lines.append(f"🖼 Фото: <code>{package['photo_limit_text']}</code>")
    if package.get("video_limit_text"):
        feature_lines.append(f"🎬 Видео: <code>{package['video_limit_text']}</code>")
    if subscription_service.is_subscription_package(package):
        feature_lines.append("✅ Подписка активируется после оплаты")
    features_text = ("\n" + "\n".join(feature_lines)) if feature_lines else ""
    balance_label = (
        "Бонусный баланс"
        if subscription_service.is_subscription_package(package)
        else credit_plural
    )
    balance_suffix = f" {credit_plural}" if balance_label != credit_plural else ""
    after_payment_text = (
        "После успешной оплаты баланс и доступ начислятся автоматически."
        if subscription_service.is_subscription_package(package)
        else f"После успешной оплаты {credit_plural} начислятся автоматически."
    )

    return (
        f"💳 <b>Оплата пакета «{package['name']}»</b>\n\n"
        f"{credit_emoji} {balance_label}: <code>{total_credits}</code>{balance_suffix}{bonus_text}"
        f"{features_text}\n"
        f"{price_text}\n\n"
        "Нажмите кнопку ниже, чтобы перейти к оплате.\n"
        f"{after_payment_text}"
        f"{_payment_created_recurring_note(recurring_enabled)}"
    )


def _recurring_choice_keyboard(package_id: str, provider: str):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="💳 Оплатить один раз",
        callback_data=f"buyonce_{provider}_{package_id}",
    )
    builder.button(
        text="☐ Согласен на автопродление",
        callback_data=f"recagree_{provider}_{package_id}",
    )
    builder.button(text="🔙 Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def _recurring_consent_keyboard(package_id: str, provider: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Согласие дано", callback_data="recurring_consent_checked")
    builder.button(
        text="💳 Перейти к первой оплате",
        callback_data=f"buyrec_{provider}_{package_id}",
    )
    builder.button(text="🔙 Назад", callback_data=f"buy_{provider}_{package_id}")
    builder.adjust(1)
    return builder.as_markup()


def _recurring_choice_text(package: dict) -> str:
    support_contact = get_support_contact()
    return (
        f"🧾 <b>{package['name']}</b>\n\n"
        f"Цена: <code>{package['price_rub']}</code> ₽ / {package.get('period', 'период')}\n"
        f"Лимит: <code>{package.get('photo_limit_text', 'по пакету')}</code>\n\n"
        "Можно оплатить один раз или включить автопродление.\n\n"
        "<b>Условия автопродления</b>\n"
        f"• Сумма списания: <code>{package['price_rub']}</code> ₽\n"
        f"• Периодичность: <code>{package.get('period', 'период')}</code>\n"
        "• Карта сохраняется у Т-Банка, а бот продлит подписку автоматически "
        "в конце срока.\n"
        "• Отключить можно в разделе пополнения.\n"
        f"• Для отмены подписки или возврата напишите в поддержку: <code>{support_contact}</code>\n\n"
        "Чтобы включить автопродление, нажмите кнопку согласия ниже."
    )


def _payment_created_recurring_note(enabled: bool) -> str:
    if not enabled:
        return ""
    support_contact = get_support_contact()
    return (
        "\n\n🔁 <b>Автопродление будет включено после оплаты.</b>\n"
        "Т-Банк сохранит платежные реквизиты и вернет токен для будущих списаний.\n"
        f"Отменить автопродление или запросить возврат можно через поддержку: "
        f"<code>{support_contact}</code>."
    )


def _payment_success_text(transaction, referral_bonus: dict | None = None) -> str:
    credit_emoji = get_credit_emoji()
    credit_plural = get_credit_plural()
    bonus_text = _format_bonus_text(referral_bonus or {})
    promo_text = ""
    if transaction.promo_code and transaction.promo_discount_percent:
        promo_text = (
            f"🎟 Скидка: <code>{transaction.promo_code}</code> "
            f"−{transaction.promo_discount_percent}%\n"
        )
    return (
        "🎉 <b>Оплата успешна!</b>\n\n"
        f"{credit_emoji} Начислено: <code>{transaction.credits}</code> {credit_plural}\n"
        f"💰 Сумма: <code>{transaction.amount_rub}</code> ₽\n"
        f"{promo_text}"
        f"{bonus_text}\n"
        "Теперь можно продолжать генерацию."
    )


async def _render_topup_menu(message: types.Message, provider: str):
    packages = await admin_package_config_service.list_packages(include_hidden=False)
    await message.edit_text(
        _topup_menu_text(packages),
        reply_markup=get_payment_packages_keyboard(packages, provider=provider),
        parse_mode="HTML",
    )


async def _complete_transaction(
    order_id: str,
    bot: Bot | None = None,
    *,
    payment_data: dict | None = None,
) -> bool:
    transaction = await get_transaction_by_order(order_id)
    if not transaction or transaction.status == "completed":
        return bool(transaction and transaction.status == "completed")

    telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
    if not telegram_id:
        logger.error("Telegram user not found for transaction %s", order_id)
        return False

    credited = await add_credits_once(
        telegram_id,
        transaction.credits,
        reason="payment_completed",
        external_id=order_id,
        metadata={"provider": transaction.provider, "amount_rub": transaction.amount_rub},
    )
    await update_transaction_status(order_id, "completed")
    if not credited:
        logger.info("Payment credits already applied for order_id=%s", order_id)
        referral_bonus = {"mode": "none", "value": 0, "percent": 0}
    else:
        referral_bonus = await credit_first_payment_referral_bonus(
            telegram_id,
            transaction.credits,
            transaction.amount_rub,
        )
    if transaction.promo_code:
        promo_marked, promo_reason = await mark_promo_code_used(
            telegram_id, transaction.promo_code, order_id=order_id
        )
        if not promo_marked:
            logger.warning(
                "Promo %s was not marked as used for order %s: %s",
                transaction.promo_code,
                order_id,
                promo_reason,
            )

    package = await admin_package_config_service.get_package(
        _package_id_from_order_id(order_id)
    )
    if package and subscription_service.is_subscription_package(package):
        subscription = await subscription_service.activate_from_package(
            telegram_id, package
        )
        recurring_row = await get_recurring_subscription(telegram_id)
        rebill_id = (
            (payment_data or {}).get("RebillId")
            or (payment_data or {}).get("rebill_id")
            or (
                recurring_row.get("rebill_id")
                if recurring_row
                and recurring_row.get("status") == "pending"
                and recurring_row.get("package_id") == package.get("id")
                else None
            )
        )
        if rebill_id and transaction.provider == "tbank":
            await confirm_recurring_subscription(
                telegram_id,
                rebill_id=str(rebill_id),
                next_charge_at=subscription["expires_at"],
                last_order_id=order_id,
            )

    if bot:
        try:
            await _notify_user(
                bot,
                telegram_id,
                _payment_success_text(transaction, referral_bonus),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            logger.exception("Failed to notify user about payment")

    return True


@router.callback_query(F.data == "menu_topup")
async def show_topup_menu(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message, config.payment_provider)


@router.callback_query(F.data == "menu_buy_credits")
async def show_packages(callback: types.CallbackQuery):
    await _render_topup_menu(callback.message, config.payment_provider)


def _recurring_status_keyboard(enabled: bool):
    builder = InlineKeyboardBuilder()
    if enabled:
        builder.button(text="⛔ Отключить автопродление", callback_data="recurring_disable")
    builder.button(text="💳 Купить подписку", callback_data="menu_topup")
    builder.button(text="🔙 Назад", callback_data="menu_topup")
    builder.adjust(1)
    return builder.as_markup()


def _recurring_status_text(row: dict | None) -> str:
    if not row or row.get("status") == "disabled":
        return (
            "🔁 <b>Автопродление</b>\n\n"
            "Сейчас автопродление выключено.\n"
            "Чтобы включить его, в пополнении выберите подписку, оплатите через Т-Банк и нажмите "
            "вариант <b>«Оплатить и включить автопродление»</b>."
        )

    status = {
        "pending": "ожидает первой оплаты",
        "active": "включено",
        "disabled": "выключено",
    }.get(str(row.get("status")), str(row.get("status")))
    next_charge = row.get("next_charge_at") or "после подтверждения первой оплаты"
    error_text = f"\n⚠️ Ошибка: <code>{row['last_error']}</code>" if row.get("last_error") else ""
    return (
        "🔁 <b>Автопродление</b>\n\n"
        f"Статус: <code>{status}</code>\n"
        f"Пакет: <code>{row.get('package_name')}</code>\n"
        f"Сумма: <code>{int(float(row.get('amount_rub') or 0))}</code> ₽\n"
        f"Следующее списание: <code>{next_charge}</code>"
        f"{error_text}"
    )


@router.callback_query(F.data == "recurring_status")
async def show_recurring_status(callback: types.CallbackQuery):
    row = await get_recurring_subscription(callback.from_user.id)
    enabled = bool(row and row.get("status") != "disabled")
    await callback.message.edit_text(
        _recurring_status_text(row),
        reply_markup=_recurring_status_keyboard(enabled),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "recurring_disable")
async def disable_recurring(callback: types.CallbackQuery):
    disabled = await disable_recurring_subscription(callback.from_user.id)
    await callback.message.edit_text(
        (
            "✅ <b>Автопродление отключено</b>\n\n"
            "Текущая оплаченная подписка останется активной до конца срока."
            if disabled
            else "Автопродление уже выключено."
        ),
        reply_markup=_recurring_status_keyboard(False),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "promo_enter")
async def promo_enter(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎟 <b>Промокод</b>\n\n"
        "Введите код одним сообщением.\n"
        "Он применит скидку к следующей покупке пакета.\n\n"
        "Например: <code>START20</code>",
        reply_markup=get_back_keyboard("menu_topup"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(PaymentStates.waiting_promo_code)


@router.message(PaymentStates.waiting_promo_code, F.text)
async def process_promo_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    success, reason, promo = await validate_promo_code(message.from_user.id, code)

    if success:
        if promo.get("promo_type") in {"bananas", "generation"}:
            marked, mark_reason = await mark_promo_code_used(
                message.from_user.id,
                promo["code"],
                order_id=(
                    f"{promo['promo_type']}:{promo['code']}:"
                    f"{message.from_user.id}:{message.message_id}"
                ),
            )
            if not marked:
                reason_text = {
                    "used_up": "Лимит активаций промокода уже закончился.",
                    "already_used": "Эта активация уже обработана.",
                }.get(mark_reason, "Не удалось активировать промокод.")
                await message.answer(
                    f"❌ <b>Промокод не сработал</b>\n\n{reason_text}",
                    reply_markup=get_back_keyboard("menu_topup"),
                    parse_mode="HTML",
                )
                return

            reward_credits = int(promo.get("reward_credits") or 0)
            if promo["promo_type"] == "generation":
                credited = await add_free_generations(message.from_user.id, reward_credits)
                reward_text = f"Бесплатных генераций: <code>{reward_credits}</code>"
                success_text = "Бесплатные генерации уже доступны."
            else:
                credited = await add_credits_once(
                    message.from_user.id,
                    reward_credits,
                    reason="promo_bonus",
                    external_id=(
                        f"promo_bonus:{promo['code']}:"
                        f"{message.from_user.id}:{message.message_id}"
                    ),
                    metadata={"promo_code": promo["code"]},
                )
                reward_text = f"Начислено: <code>{reward_credits}</code> 🪙"
                success_text = (
                    "BoomCoin уже на балансе."
                    if credited
                    else "Эта активация уже была начислена ранее."
                )
            await state.clear()
            await message.answer(
                "✅ <b>Промокод активирован</b>\n\n"
                f"Код: <code>{promo['code']}</code>\n"
                f"{reward_text}\n\n"
                f"{success_text if credited else 'Промокод уже был применён ранее.'}",
                reply_markup=get_main_menu_keyboard(
                    await get_user_credits(message.from_user.id),
                    message.from_user.id,
                ),
                parse_mode="HTML",
            )
            return

        await state.update_data(active_promo=promo)
        await state.set_state(None)
        await message.answer(
            "✅ <b>Промокод применён</b>\n\n"
            f"Код: <code>{promo['code']}</code>\n"
            f"Скидка: <code>{promo['discount_percent']}%</code>\n\n"
            "Теперь выберите пакет для оплаты.",
            reply_markup=get_payment_packages_keyboard(
                await admin_package_config_service.list_packages(include_hidden=False),
                provider=config.payment_provider,
            ),
            parse_mode="HTML",
        )
        return

    reason_text = {
        "not_found": "Такой промокод не найден или уже отключён.",
        "expired": "Срок действия промокода истёк.",
        "used_up": "Лимит активаций промокода уже закончился.",
        "already_used": "Вы уже активировали этот промокод.",
        "empty": "Введите код текстом.",
    }.get(reason, "Не удалось активировать промокод.")
    await message.answer(
        f"❌ <b>Промокод не сработал</b>\n\n{reason_text}",
        reply_markup=get_back_keyboard("menu_topup"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("topup_provider_"))
async def select_topup_provider(callback: types.CallbackQuery):
    provider = callback.data.replace("topup_provider_", "")
    if provider not in {"tbank", "cryptobot"}:
        provider = config.payment_provider

    await _render_topup_menu(callback.message, provider)
    provider_text = "Выбран Crypto Bot" if provider == "cryptobot" else "Выбран Т-Банк"
    await callback.answer(provider_text)


@router.callback_query(F.data.startswith("recagree_"))
async def confirm_recurring_consent(callback: types.CallbackQuery):
    payload = callback.data.replace("recagree_", "", 1)
    provider = config.payment_provider

    if payload.startswith("tbank_"):
        provider = "tbank"
        package_id = payload.replace("tbank_", "", 1)
    else:
        package_id = payload

    package = await admin_package_config_service.get_package(package_id)
    if not package or package.get("hidden"):
        await callback.answer("Пакет не найден", show_alert=True)
        return
    if provider != "tbank" or not subscription_service.is_subscription_package(package):
        await callback.answer(
            "Автопродление доступно только для подписок через Т-Банк.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        _recurring_choice_text(package)
        + "\n\n✅ <b>Вы согласились на регулярные списания.</b>",
        reply_markup=_recurring_consent_keyboard(package_id, provider),
        parse_mode="HTML",
    )
    await callback.answer("Согласие на автопродление отмечено")


@router.callback_query(F.data == "recurring_consent_checked")
async def recurring_consent_checked(callback: types.CallbackQuery):
    await callback.answer("Согласие уже отмечено")


@router.callback_query(
    F.data.startswith("buy_")
    | F.data.startswith("buyonce_")
    | F.data.startswith("buyrec_")
)
async def initiate_payment(callback: types.CallbackQuery, state: FSMContext):
    recurring_requested = callback.data.startswith("buyrec_")
    one_time_selected = callback.data.startswith("buyonce_")
    if recurring_requested:
        payload = callback.data.replace("buyrec_", "", 1)
    elif one_time_selected:
        payload = callback.data.replace("buyonce_", "", 1)
    else:
        payload = callback.data.replace("buy_", "", 1)
    provider = config.payment_provider

    if payload.startswith("cryptobot_"):
        provider = "cryptobot"
        package_id = payload.replace("cryptobot_", "", 1)
    elif payload.startswith("tbank_"):
        provider = "tbank"
        package_id = payload.replace("tbank_", "", 1)
    else:
        package_id = payload

    package = await admin_package_config_service.get_package(package_id)
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    if package.get("hidden"):
        await callback.answer("Пакет скрыт", show_alert=True)
        return
    is_subscription = subscription_service.is_subscription_package(package)
    if (
        is_subscription
        and provider == "tbank"
        and not recurring_requested
        and not one_time_selected
    ):
        await callback.message.edit_text(
            _recurring_choice_text(package),
            reply_markup=_recurring_choice_keyboard(package_id, provider),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if recurring_requested and (provider != "tbank" or not is_subscription):
        await callback.answer(
            "Автопродление доступно только для подписок через Т-Банк.",
            show_alert=True,
        )
        return
    total_credits = package["credits"] + package.get("bonus_credits", 0)

    data = await state.get_data()
    active_promo = data.get("active_promo") or {}
    promo_code = active_promo.get("code")
    promo_discount_percent = int(active_promo.get("discount_percent") or 0)
    original_price_rub = package["price_rub"]
    amount_rub = original_price_rub

    if promo_code and promo_discount_percent:
        is_valid, reason, promo = await validate_promo_code(
            callback.from_user.id, promo_code
        )
        if not is_valid:
            await state.update_data(active_promo=None)
            await callback.answer(
                {
                    "expired": "Промокод истёк",
                    "used_up": "Лимит промокода закончился",
                    "already_used": "Вы уже использовали этот промокод",
                }.get(reason, "Промокод больше недоступен"),
                show_alert=True,
            )
            promo_code = None
            promo_discount_percent = 0
        else:
            promo_discount_percent = int(promo["discount_percent"])
            amount_rub = max(
                1,
                original_price_rub * (100 - promo_discount_percent) // 100,
            )

    order_id = f"{callback.from_user.id}_{int(time.time())}_{package_id}"
    amount_kop = int(amount_rub * 100)

    bot_info = await callback.bot.get_me()
    success_url = f"https://t.me/{bot_info.username}?start=success_{order_id}"
    fail_url = f"https://t.me/{bot_info.username}?start=fail_{order_id}"

    if provider == "cryptobot":
        if not cryptobot_service.enabled:
            await callback.message.edit_text(
                "❌ <b>Crypto Bot недоступен</b>\n"
                "Проверьте настройку токена Crypto Bot и попробуйте снова.",
                reply_markup=get_back_keyboard("back_main"),
                parse_mode="HTML",
            )
            return

        result = await cryptobot_service.create_invoice(
            amount_rub=amount_rub,
            order_id=order_id,
            description=f"Покупка {total_credits} BoomCoin ({package['name']})",
            paid_btn_url=success_url,
        )
    else:
        provider = "tbank"
        result = await tbank_service.init_payment(
            amount=amount_kop,
            order_id=order_id,
            description=f"Покупка {total_credits} BoomCoin ({package['name']})",
            customer_key=str(callback.from_user.id),
            success_url=success_url,
            fail_url=fail_url,
            notification_url=config.tbank_notification_url,
            recurrent=recurring_requested,
        )

    is_success = (
        result.get("Success") != False
        if result and "Success" in result
        else bool(result)
    )
    has_payment_info = bool(result) and (
        "PaymentId" in result or "payment_id" in result
    )

    if not result or not is_success or not has_payment_info:
        error_msg = (
            result.get("Message", result.get("message", "Неизвестная ошибка"))
            if result
            else "Нет соединения с провайдером"
        )
        logger.error(
            "Payment creation failed for %s: %s, result=%s",
            provider,
            error_msg,
            result,
        )
        await callback.message.edit_text(
            f"❌ <b>Ошибка создания платежа ({provider})</b>\n"
            f"{error_msg}\n"
            "Попробуйте позже или выберите другой способ оплаты.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    payment_id = result.get("PaymentId") or result.get("payment_id")
    payment_url = (
        result.get("PaymentURL")
        or result.get("PaymentUrl")
        or result.get("payment_url")
    )

    if not payment_url:
        logger.error("Payment URL missing for %s: result=%s", provider, result)
        await callback.message.edit_text(
            "❌ <b>Ошибка создания платежа</b>\n"
            "Провайдер не вернул ссылку на оплату.\n"
            "Попробуйте позже.",
            reply_markup=get_back_keyboard("back_main"),
            parse_mode="HTML",
        )
        return

    logger.info("Payment created successfully: %s via %s", payment_id, provider)

    user = await get_or_create_user(callback.from_user.id)

    await create_transaction(
        order_id=order_id,
        user_id=user.id,
        payment_id=str(payment_id),
        provider=provider,
        credits=total_credits,
        amount_rub=amount_rub,
        original_amount_rub=original_price_rub,
        promo_code=promo_code,
        promo_discount_percent=promo_discount_percent,
        status="pending",
    )
    if recurring_requested:
        await upsert_recurring_subscription(
            callback.from_user.id,
            provider="tbank",
            package_id=package_id,
            package_name=str(package["name"]),
            amount_rub=amount_rub,
            credits=total_credits,
            customer_key=str(callback.from_user.id),
            status="pending",
        )

    await callback.message.edit_text(
        _payment_created_text(
            package,
            total_credits,
            amount_rub=amount_rub,
            original_amount_rub=original_price_rub,
            promo_code=promo_code,
            promo_discount_percent=promo_discount_percent,
            recurring_enabled=recurring_requested,
        ),
        reply_markup=get_payment_confirmation_keyboard(payment_url, order_id),
        parse_mode="HTML",
    )
    await state.clear()


@router.message(F.text.startswith("/cryptobot"))
async def cryptobot_status_hint(message: types.Message):
    if config.has_cryptobot:
        await message.answer("✅ Crypto Bot настроен и готов к приёму платежей.")
    else:
        await message.answer(
            "⚠️ Crypto Bot не настроен. Проверьте переменную CRYPTOBOT_API_TOKEN."
        )


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_status(callback: types.CallbackQuery):
    order_id = callback.data.replace("check_payment_", "")
    transaction = await get_transaction_by_order(order_id)

    if not transaction:
        await callback.answer("Транзакция не найдена", show_alert=True)
        return

    if transaction.status == "completed":
        await callback.message.edit_text(
            _payment_success_text(transaction),
            reply_markup=get_main_menu_keyboard(user_id=callback.from_user.id),
            parse_mode="HTML",
        )
        return

    paid = False
    if transaction.provider == "cryptobot":
        invoice = await cryptobot_service.get_invoice(transaction.payment_id)
        paid = bool(invoice and invoice.get("status") == "paid")
    else:
        result = await tbank_service.get_state(transaction.payment_id)
        paid = bool(result and result.get("Status") == "CONFIRMED")

    if not paid:
        await callback.answer("⏳ Платёж ещё не подтверждён.", show_alert=True)
        return

    await _complete_transaction(order_id, payment_data=result)
    transaction = await get_transaction_by_order(order_id)
    await callback.message.edit_text(
        _payment_success_text(transaction),
        reply_markup=get_main_menu_keyboard(user_id=callback.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "❌ <b>Платёж отменён</b>\n\nВы можете попробовать снова в любое время.",
        reply_markup=get_main_menu_keyboard(user_id=callback.from_user.id),
        parse_mode="HTML",
    )


async def handle_tbank_webhook(request):
    try:
        data = await request.json()
        logger.info("T-Bank webhook received: %s", data.get("OrderId"))

        if not tbank_service.verify_notification(data.copy()):
            logger.warning("Invalid signature in T-Bank webhook")
            logger.debug("Webhook data for sig check: %s", data)
            return web.json_response(
                {"Success": False, "Message": "Invalid signature"}, status=200
            )

        if data.get("Status") == "AUTHORIZED" and data.get("RebillId"):
            transaction = await get_transaction_by_order(data.get("OrderId"))
            if transaction:
                telegram_id = await get_telegram_id_by_user_id(transaction.user_id)
                package = await admin_package_config_service.get_package(
                    _package_id_from_order_id(transaction.order_id)
                )
                if telegram_id and package and subscription_service.is_subscription_package(package):
                    await upsert_recurring_subscription(
                        telegram_id,
                        provider="tbank",
                        package_id=str(package["id"]),
                        package_name=str(package["name"]),
                        amount_rub=float(transaction.amount_rub),
                        credits=int(transaction.credits),
                        customer_key=str(telegram_id),
                        rebill_id=str(data["RebillId"]),
                        status="pending",
                    )

        if data.get("Status") == "CONFIRMED":
            await _complete_transaction(
                data.get("OrderId"),
                request.app["bot"],
                payment_data=data,
            )

        return web.json_response({"Success": True}, status=200)
    except Exception as exc:
        logger.exception("Error processing T-Bank webhook: %s", exc)
        return web.json_response(
            {"Success": False, "Message": "Internal error"}, status=500
        )


async def handle_cryptobot_webhook(request):
    try:
        raw_body = await request.read()
        signature = request.headers.get("crypto-pay-api-signature", "")

        if not cryptobot_service.verify_webhook_signature(raw_body, signature):
            logger.warning("Invalid Crypto Bot webhook signature")
            return web.Response(status=403)

        data = await request.json()
        if data.get("update_type") != "invoice_paid":
            return web.Response(status=200)

        invoice = data.get("payload", {})
        order_id = invoice.get("payload")
        if not order_id:
            logger.warning("Crypto Bot webhook missing order_id")
            return web.Response(status=200)

        await _complete_transaction(order_id, request.app["bot"])
        return web.Response(status=200)
    except Exception as exc:
        logger.exception("Error processing Crypto Bot webhook: %s", exc)
        return web.Response(status=500)
