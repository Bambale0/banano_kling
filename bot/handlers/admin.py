import json
import logging
import re
import csv
import io
import html
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    add_credits,
    create_promo_code,
    deactivate_promo_code,
    deduct_credits,
    export_users,
    get_admin_stats,
    get_bot_setting,
    get_promo_codes,
    get_user_stats,
    set_bot_setting,
    set_user_banned,
)
from bot.keyboards import (
    get_admin_keyboard,
    get_admin_price_image_keyboard,
    get_admin_price_video_keyboard,
    get_admin_prices_keyboard,
    get_back_keyboard,
)
from bot.services.preset_manager import preset_manager
from bot.services.admin_ai_service import admin_ai_service
from bot.states import AdminStates

PRICE_PATH = Path("data/price.json")

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return config.is_admin(user_id)


def _admin_nav_keyboard(back_data: str = "admin_back"):
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data=back_data)],
            [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
        ]
    )


def _user_actions_keyboard(user_id: int, is_banned: bool):
    ban_text = "✅ Разбанить" if is_banned else "🚫 Забанить"
    ban_action = "unban" if is_banned else "ban"
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="➕ Добавить BoomCoin",
                    callback_data=f"admin_add_credits_{user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="➖ Списать BoomCoin",
                    callback_data=f"admin_deduct_credits_{user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=ban_text,
                    callback_data=f"admin_user_{ban_action}_{user_id}",
                )
            ],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
            [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
        ]
    )


def _admin_ai_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="📘 Инструкция", callback_data="admin_ai_help")],
            [types.InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
            [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
        ]
    )


def _admin_ai_confirm_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Выполнить", callback_data="admin_ai_confirm"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отмена", callback_data="admin_ai_cancel"
                ),
            ],
            [types.InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
        ]
    )


def _admin_ai_help_text() -> str:
    return """
📘 <b>Инструкция: ИИ-админ</b>

ИИ-админ — агентный помощник для управления ботом. Он понимает обычный язык, сохраняет контекст текущей админ-сессии и может выполнять цепочки шагов.

<b>Как пользоваться</b>
1. Откройте <code>/admin</code> → <b>🤖 ИИ-админ</b> или команду <code>/admin_ai</code>.
2. Напишите задачу обычным текстом.
3. Если действие меняет данные, бот покажет план и попросит нажать <b>✅ Выполнить</b>.
4. После результата можно продолжать в том же контексте: <code>проверь подробнее</code>, <code>теперь покажи пользователя</code>.

<b>Отчёты и агентные цепочки</b>
• <code>сделай отчёт по боту</code>
• <code>дай сводку по состоянию бота и логам</code>
• <code>проверь здоровье бота</code>

Для отчёта агент сам выполняет несколько шагов: статистика, техрежим, промокоды, анализ последних логов.

<b>Анализ логов</b>
• <code>проанализируй последние логи</code>
• <code>почему могли падать генерации?</code>
• <code>найди ошибки webhook за последние 500 строк</code>

Агент читает только разрешённые файлы: <code>logs/bot.log</code>, <code>logs/bot_output.log</code>, <code>logs/watchdog.log</code>. Произвольные shell-команды через ИИ не выполняются.

<b>Research по AI-генерации</b>
• <code>найди новые ИИ для генерации видео и фото</code>
• <code>сравни свежие модели image-to-image для фотореализма</code>
• <code>что стоит протестировать для генерации контента?</code>

Research использует GPT 5.5 с web search и возвращает краткий отчёт: факты, риски, рекомендации для продукта.

<b>Пользователи и баланс</b>
• <code>проверь пользователя 123456789</code>
• <code>начисли 50 BoomCoin пользователю 123456789</code>
• <code>спиши 10 BoomCoin у 123456789</code>
• <code>забань 123456789</code>
• <code>разбань 123456789</code>

<b>Промокоды</b>
• <code>покажи промокоды</code>
• <code>создай промокод VIP20 скидка 20 лимит 100</code>
• <code>создай промокод GIFT50 BoomCoin 50 лимит 200</code>
• <code>создай промокод FREEGEN генерации 1 лимит 100</code>
• <code>отключи промокод VIP20</code>

<b>Техрежим и экспорт</b>
• <code>включи техрежим</code>
• <code>выключи техрежим</code>
• <code>какой сейчас техрежим?</code>
• <code>экспорт пользователей</code>

<b>Безопасность</b>
Действия, которые меняют данные, всегда требуют подтверждения: баланс, бан/разбан, техрежим, промокоды, экспорт. Массовая рассылка через ИИ не выполняется — используйте штатный раздел <b>📣 Рассылка</b>.

<b>Контекст</b>
ИИ-админ помнит последние результаты в рамках текущей FSM-сессии. Чтобы начать заново, напишите: <code>очисти контекст</code>.
""".strip()


def _format_user_stats(user_id: int, stats: dict) -> str:
    promos = stats.get("promos") or []
    promo_text = (
        "\n".join(
            f"• <code>{html.escape(str(p['code']))}</code> −{p['discount_percent']}% ({p['redeemed_at']})"
            for p in promos
        )
        if promos
        else "нет"
    )
    ban_text = "забанен" if stats.get("is_banned") else "активен"
    return f"""
👤 <b>Пользователь</b>

🆔 ID: <code>{user_id}</code>
💰 BoomCoin: <code>{stats['credits']}</code>
🚦 Статус: <code>{ban_text}</code>
📊 Генераций: <code>{stats['generations']}</code>
💸 Потрачено: <code>{stats['total_spent']}</code>
📅 Регистрация: <code>{stats['member_since']}</code>
🎟 Промокоды:
{promo_text}
"""


def _format_admin_stats(stats: dict) -> str:
    return f"""
📊 <b>Статистика бота</b>

👥 Пользователей: <code>{stats['total_users']}</code>
🟢 Активных за 7 дней: <code>{stats['active_users']}</code>
🚫 Забанено: <code>{stats['banned_users']}</code>
🪙 Баланс пользователей: <code>{stats['total_user_balance']}</code>
🎨 Генераций: <code>{stats['total_generations']}</code>
💳 Транзакций: <code>{stats['total_transactions']}</code>
💰 Выручка: <code>{stats['total_revenue']:.0f}</code> ₽
🎁 Рефералов: <code>{stats.get('total_referrals', 0)}</code>
"""


def _format_promos(promos: list[dict]) -> str:
    if not promos:
        return "🎟 <b>Промокоды</b>\n\nПока промокодов нет."
    lines = ["🎟 <b>Последние промокоды</b>", ""]
    for promo in promos:
        status = "✅" if promo["is_active"] else "⛔"
        expires = promo["expires_at"] or "без срока"
        if promo.get("promo_type") == "bananas":
            value = f"+{promo['reward_credits']}🪙"
        elif promo.get("promo_type") == "generation":
            value = f"{promo['reward_credits']} free gen"
        else:
            value = f"−{promo['discount_percent']}%"
        lines.append(
            f"{status} <code>{html.escape(str(promo['code']))}</code> — "
            f"{value}, {promo['used_count']}/{promo['max_uses']}, до {expires}"
        )
    return "\n".join(lines)


def _clip_html(text: str, limit: int = 3600) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n<i>Обрезано под лимит Telegram.</i>"


def _read_log_tail(lines: int = 250) -> str:
    log_paths = [
        Path("logs/bot.log"),
        Path("logs/bot_output.log"),
        Path("logs/watchdog.log"),
    ]
    collected: list[str] = []
    for path in log_paths:
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            collected.append(f"== {path} ==\nНе удалось прочитать: {exc}")
            continue
        tail = content[-max(20, min(lines, 1000)) :]
        collected.append(f"== {path} ==\n" + "\n".join(tail))
    return "\n\n".join(collected) or "Лог-файлы не найдены."


def _quick_log_metrics(log_text: str) -> dict:
    patterns = {
        "ERROR": r"\bERROR\b|exception|Traceback",
        "WARNING": r"\bWARNING\b|warning",
        "WEBHOOK": r"webhook",
        "RESTART": r"Bot starting|Server started|Starting in webhook mode",
        "HEALTH": r"GET /health",
    }
    return {
        name: len(re.findall(pattern, log_text, flags=re.I))
        for name, pattern in patterns.items()
    }


async def _analyze_logs_with_ai(query: str, lines: int = 250) -> str:
    log_text = _read_log_tail(lines)
    metrics = _quick_log_metrics(log_text)
    prompt = (
        "Проанализируй логи Telegram-бота Banana Boom для админа. "
        "Дай краткий отчёт: что происходит, ошибки/риски, вероятная причина, что проверить дальше. "
        "Если критичных ошибок нет, скажи это явно.\n\n"
        f"Запрос админа: {query or 'общий анализ'}\n"
        f"Метрики: {json.dumps(metrics, ensure_ascii=False)}\n\n"
        f"Логи:\n{log_text[-12000:]}"
    )
    try:
        from bot.services.gpt55_service import gpt55_service

        response = await gpt55_service.ask(
            [{"type": "input_text", "text": prompt}],
            history=[],
            reasoning_effort="high",
            web_search=False,
        )
    except Exception as exc:
        logger.warning("Admin AI log analysis failed: %r", exc)
        response = None

    if response:
        return _clip_html(
            "🧾 <b>Анализ логов</b>\n\n"
            f"{html.escape(response)}\n\n"
            f"<b>Счётчики:</b> <code>{html.escape(json.dumps(metrics, ensure_ascii=False))}</code>"
        )

    important = [
        line for line in log_text.splitlines()
        if re.search(r"\b(ERROR|WARNING)\b|Traceback|exception|failed", line, flags=re.I)
    ][-20:]
    important_text = "\n".join(important) if important else "Критичных ERROR/WARNING в выбранном хвосте не найдено."
    return _clip_html(
        "🧾 <b>Анализ логов</b>\n\n"
        f"<b>Счётчики:</b> <code>{html.escape(json.dumps(metrics, ensure_ascii=False))}</code>\n\n"
        f"<b>Важные строки:</b>\n<code>{html.escape(important_text)}</code>"
    )


async def _research_ai_generation(query: str) -> str:
    prompt = (
        "Сделай актуальный research для админа Telegram-бота генерации контента. "
        "Найди новые/важные AI-модели, API и провайдеров для image/video generation, "
        "оцени полезность для продукта, качество, стоимость/риски, что стоит протестировать. "
        "Ответ по-русски, структурно и кратко. Отделяй проверенные факты от рекомендаций.\n\n"
        f"Запрос: {query or 'новые AI в генерации контента'}"
    )
    try:
        from bot.services.gpt55_service import gpt55_service

        response = await gpt55_service.ask(
            [{"type": "input_text", "text": prompt}],
            history=[],
            reasoning_effort="high",
            web_search=True,
        )
    except Exception as exc:
        logger.warning("Admin AI research failed: %r", exc)
        response = None

    if not response:
        return (
            "🔎 <b>Research AI</b>\n\n"
            "Не удалось получить веб-исследование сейчас. Проверьте KIE_AI_API_KEY/Kie.ai доступ."
        )
    return _clip_html("🔎 <b>Research AI-генерации</b>\n\n" + html.escape(response))


def _validate_admin_ai_action(plan: dict) -> str | None:
    actions = plan.get("actions")
    if isinstance(actions, list) and actions:
        for item in actions:
            error = _validate_admin_ai_action(item)
            if error:
                return error
        return None

    action = plan.get("action")
    params = plan.get("params") or {}
    if action == "unknown":
        return plan.get("summary") or "Не понял действие."
    if action in {"user_info", "add_credits", "deduct_credits", "ban_user", "unban_user"}:
        if not params.get("telegram_id"):
            return "Нужен Telegram ID пользователя."
    if action in {"add_credits", "deduct_credits"} and not params.get("amount"):
        return "Нужна сумма BoomCoin."
    if action == "maintenance_set" and "enabled" not in params:
        return "Нужно указать: включить или выключить техрежим."
    if action == "create_promo":
        if not params.get("code"):
            return "Нужен код промокода."
        if not params.get("value") or not params.get("max_uses"):
            return "Для промокода нужны значение и лимит активаций."
    if action == "deactivate_promo" and not params.get("code"):
        return "Нужен код промокода."
    return None


def _admin_ai_plan_preview(plan: dict) -> str:
    if isinstance(plan.get("actions"), list) and plan["actions"]:
        lines = [
            "🤖 <b>ИИ-админ подготовил агентный прогон</b>",
            "",
            f"Описание: {html.escape(str(plan.get('summary') or ''))}",
            "",
            "<b>Шаги:</b>",
        ]
        for index, item in enumerate(plan["actions"], start=1):
            action = item.get("action")
            params = item.get("params") or {}
            lines.append(
                f"{index}. <code>{html.escape(str(action))}</code> — "
                f"{html.escape(str(item.get('summary') or ''))}"
            )
            if params:
                params_text = ", ".join(f"{key}={value}" for key, value in params.items())
                lines.append(f"   <code>{html.escape(params_text)}</code>")
        lines.extend(["", "Подтвердите выполнение."])
        return "\n".join(lines)

    action = plan.get("action")
    params = plan.get("params") or {}
    lines = [
        "🤖 <b>ИИ-админ подготовил действие</b>",
        "",
        f"Действие: <code>{html.escape(str(action))}</code>",
        f"Описание: {html.escape(str(plan.get('summary') or ''))}",
    ]
    if params:
        lines.append("")
        lines.append("<b>Параметры:</b>")
        for key, value in params.items():
            lines.append(f"• <code>{html.escape(str(key))}</code>: <code>{html.escape(str(value))}</code>")
    lines.extend(["", "Подтвердите выполнение."])
    return "\n".join(lines)


async def _execute_admin_ai_action(
    action: str,
    params: dict,
    admin_id: int,
    message: types.Message,
) -> str:
    if action == "bot_report":
        stats = _format_admin_stats(await get_admin_stats())
        maintenance = await _execute_admin_ai_action("maintenance_status", {}, admin_id, message)
        log_report = await _analyze_logs_with_ai(params.get("scope", ""), 180)
        return _clip_html(
            "📋 <b>Агентный отчёт по боту</b>\n\n"
            f"{stats}\n\n{maintenance}\n\n{log_report}"
        )

    if action == "analyze_logs":
        return await _analyze_logs_with_ai(
            params.get("query", ""),
            int(params.get("lines") or 250),
        )

    if action == "research_ai":
        return await _research_ai_generation(params.get("query", ""))

    if action == "clear_context":
        return "🧹 Контекст ИИ-админа очищен."

    if action == "stats":
        return _format_admin_stats(await get_admin_stats())

    if action == "user_info":
        user_id = int(params["telegram_id"])
        return _format_user_stats(user_id, await get_user_stats(user_id))

    if action == "list_promos":
        return _format_promos(await get_promo_codes(limit=10))

    if action == "maintenance_status":
        enabled = (await get_bot_setting("maintenance_mode", "0")) == "1"
        return f"⚙️ <b>Техрежим</b>\n\nСейчас: <code>{'включён' if enabled else 'выключен'}</code>"

    if action == "export_users":
        rows = await export_users()
        buffer = io.StringIO()
        fieldnames = [
            "telegram_id",
            "credits",
            "is_banned",
            "has_paid",
            "referral_code",
            "referral_earned",
            "created_at",
            "updated_at",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        await message.answer_document(
            types.BufferedInputFile(
                buffer.getvalue().encode("utf-8-sig"),
                filename="users_export.csv",
            ),
            caption=f"📦 Экспорт пользователей: {len(rows)} строк",
        )
        return "✅ Экспорт сформирован и отправлен файлом."

    if action == "add_credits":
        user_id = int(params["telegram_id"])
        amount = int(params["amount"])
        success = await add_credits(
            user_id,
            amount,
            reason="admin_ai_adjustment_add",
            external_id=f"admin_ai:{admin_id}:add:{user_id}:{message.message_id}",
            metadata={"admin_id": admin_id},
        )
        stats = await get_user_stats(user_id)
        status = "✅ Начислено" if success else "ℹ️ Операция уже была выполнена"
        return (
            f"{status}: <code>{amount}</code>🪙 пользователю <code>{user_id}</code>\n"
            f"Текущий баланс: <code>{stats['credits']}</code>🪙"
        )

    if action == "deduct_credits":
        user_id = int(params["telegram_id"])
        amount = int(params["amount"])
        success = await deduct_credits(
            user_id,
            amount,
            reason="admin_ai_adjustment_deduct",
            external_id=f"admin_ai:{admin_id}:deduct:{user_id}:{message.message_id}",
            metadata={"admin_id": admin_id},
        )
        if not success:
            return "❌ Не удалось списать BoomCoin. Возможно, недостаточно баланса."
        stats = await get_user_stats(user_id)
        return (
            f"✅ Списано: <code>{amount}</code>🪙 у пользователя <code>{user_id}</code>\n"
            f"Текущий баланс: <code>{stats['credits']}</code>🪙"
        )

    if action in {"ban_user", "unban_user"}:
        user_id = int(params["telegram_id"])
        is_banned = action == "ban_user"
        await set_user_banned(user_id, is_banned)
        return (
            f"{'🚫 Пользователь забанен' if is_banned else '✅ Пользователь разбанен'}: "
            f"<code>{user_id}</code>"
        )

    if action == "maintenance_set":
        enabled = bool(params["enabled"])
        await set_bot_setting("maintenance_mode", "1" if enabled else "0")
        return f"✅ Техрежим {'включён' if enabled else 'выключен'}."

    if action == "create_promo":
        promo_type = params.get("promo_type") or "discount"
        value = int(params["value"])
        max_uses = int(params["max_uses"])
        expires_at = f"{params['expires_at']} 23:59:59" if params.get("expires_at") else None
        ok, result = await create_promo_code(
            code=params["code"],
            discount_percent=value if promo_type == "discount" else 0,
            max_uses=max_uses,
            expires_at=expires_at,
            created_by=admin_id,
            promo_type=promo_type,
            reward_credits=value if promo_type in {"bananas", "generation"} else 0,
        )
        if not ok:
            return f"❌ Не удалось создать промокод: <code>{html.escape(str(result))}</code>"
        suffix = "🪙" if promo_type == "bananas" else " генерац." if promo_type == "generation" else "%"
        return (
            "✅ <b>Промокод создан</b>\n\n"
            f"Код: <code>{result}</code>\n"
            f"Тип: <code>{promo_type}</code>\n"
            f"Значение: <code>{value}{suffix}</code>\n"
            f"Лимит: <code>{max_uses}</code>\n"
            f"Срок: <code>{expires_at or 'без срока'}</code>"
        )

    if action == "deactivate_promo":
        deleted = await deactivate_promo_code(params["code"])
        return "✅ Промокод отключён." if deleted else "❌ Активный промокод не найден."

    return "❌ Это действие пока не поддерживается."


async def _execute_admin_ai_plan(
    plan: dict,
    admin_id: int,
    message: types.Message,
) -> str:
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        return await _execute_admin_ai_action(
            plan["action"],
            plan.get("params") or {},
            admin_id,
            message,
        )

    sections = ["📋 <b>Агентный прогон выполнен</b>"]
    for index, item in enumerate(actions, start=1):
        action = item.get("action")
        params = item.get("params") or {}
        result = await _execute_admin_ai_action(action, params, admin_id, message)
        sections.append(
            f"\n<b>Шаг {index}: <code>{html.escape(str(action))}</code></b>\n{result}"
        )
    return _clip_html("\n".join(sections))


def _remember_admin_ai_context(data: dict, request: str, plan: dict, result: str) -> list[dict]:
    memory = data.get("admin_ai_memory")
    if not isinstance(memory, list):
        memory = []
    memory.append(
        {
            "request": request[:500],
            "plan": {
                "action": plan.get("action"),
                "actions": [
                    item.get("action") for item in plan.get("actions", [])
                    if isinstance(item, dict)
                ],
            },
            "result": re.sub(r"<[^>]+>", "", result)[:900],
        }
    )
    return memory[-8:]


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Открывает админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return

    stats = await get_admin_stats()

    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Активных за 7 дней: <code>{stats['active_users']}</code>
• Забанено: <code>{stats['banned_users']}</code>
• Баланс пользователей: <code>{stats['total_user_balance']}</code> 🪙
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

<b>Разделы:</b>
📊 Статистика — пользователи, платежи, баланс.
📣 Рассылка — текст или фото + текст.
🪙 Баланс — начислить или списать BoomCoin.
🎟 Промокоды — создать, удалить, посмотреть список.
👤 Пользователь — ID, баланс, бан, активированные промокоды.
🚫 Бан / разбан — ограничить доступ к боту.
📦 Экспорт — список пользователей CSV-файлом.
⚙️ Техрежим — временно закрыть бот для пользователей.
💰 Цены — тарифы моделей.
"""

    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")


@router.message(Command("admin_ai"))
async def cmd_admin_ai(message: types.Message, state: FSMContext):
    """Открывает ИИ-управление ботом для админа."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    await state.set_state(AdminStates.waiting_ai_request)
    await message.answer(
        "🤖 <b>ИИ-админ</b>\n\n"
        "Напишите, что нужно сделать с ботом. Я сохраняю контекст этой админ-сессии "
        "и могу выполнять несколько шагов подряд.\n\n"
        "Примеры:\n"
        "• <code>сделай отчёт по боту</code>\n"
        "• <code>проанализируй последние логи</code>\n"
        "• <code>найди новые AI для генерации видео и фото</code>\n"
        "• <code>покажи статистику</code>\n"
        "• <code>проверь пользователя 123456789</code>\n"
        "• <code>начисли 50 BoomCoin пользователю 123456789</code>\n"
        "• <code>включи техрежим</code>\n"
        "• <code>создай промокод VIP20 скидка 20 лимит 100</code>\n\n"
        "Изменения бот всегда попросит подтвердить.",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_ai")
async def admin_ai_open(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        "🤖 <b>ИИ-админ</b>\n\n"
        "Напишите обычным языком, что нужно сделать: отчёт, анализ логов, research новых AI, "
        "статистика, пользователь, баланс, бан, промокод, техрежим или экспорт.\n\n"
        "Контекст этой сессии сохраняется. Можно написать: <code>теперь проверь ошибки подробнее</code>.\n\n"
        "Опасные действия выполняются только после подтверждения.",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ai_help")
async def admin_ai_help(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        _admin_ai_help_text(),
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_ai_request, F.text)
async def admin_ai_process_request(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return

    wait_msg = await message.answer("🤖 Думаю над командой...")
    stats = await get_admin_stats()
    data = await state.get_data()
    memory = data.get("admin_ai_memory") if isinstance(data.get("admin_ai_memory"), list) else []
    plan = await admin_ai_service.plan_action(
        message.text,
        context={
            "admin_id": message.from_user.id,
            "total_users": stats.get("total_users"),
            "maintenance_mode": await get_bot_setting("maintenance_mode", "0"),
            "session_memory": memory[-6:],
        },
    )
    validation_error = _validate_admin_ai_action(plan)
    if validation_error:
        await wait_msg.edit_text(
            "🤖 <b>ИИ-админ</b>\n\n"
            f"{html.escape(validation_error)}\n\n"
            "Попробуйте написать команду конкретнее.",
            reply_markup=_admin_ai_keyboard(),
            parse_mode="HTML",
        )
        return

    if plan.get("action") == "clear_context":
        await state.update_data(admin_ai_memory=[], admin_ai_plan=None)
        await wait_msg.edit_text(
            "🧹 Контекст ИИ-админа очищен.\n\nМожно начать новую админ-задачу.",
            reply_markup=_admin_ai_keyboard(),
            parse_mode="HTML",
        )
        return

    action = plan["action"]
    params = plan.get("params") or {}
    if plan.get("requires_confirmation"):
        await state.update_data(admin_ai_plan=plan)
        await state.set_state(AdminStates.confirming_ai_action)
        await wait_msg.edit_text(
            _admin_ai_plan_preview(plan),
            reply_markup=_admin_ai_confirm_keyboard(),
            parse_mode="HTML",
        )
        return

    result = await _execute_admin_ai_plan(plan, message.from_user.id, wait_msg)
    await state.update_data(
        admin_ai_memory=_remember_admin_ai_context(data, message.text, plan, result)
    )
    await wait_msg.edit_text(
        f"{result}\n\n🤖 Можно отправить следующую админ-команду.",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_ai_cancel")
async def admin_ai_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.set_state(AdminStates.waiting_ai_request)
    await state.update_data(admin_ai_plan=None)
    await callback.message.edit_text(
        "❌ Действие отменено.\n\nНапишите следующую команду для ИИ-админа.",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ai_confirm")
async def admin_ai_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    data = await state.get_data()
    plan = data.get("admin_ai_plan") or {}
    validation_error = _validate_admin_ai_action(plan)
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    await callback.message.edit_text("⏳ Выполняю действие...", parse_mode="HTML")
    result = await _execute_admin_ai_action(
        plan["action"],
        plan.get("params") or {},
        callback.from_user.id,
        callback.message,
    ) if not plan.get("actions") else await _execute_admin_ai_plan(
        plan,
        callback.from_user.id,
        callback.message,
    )
    await state.update_data(
        admin_ai_plan=None,
        admin_ai_memory=_remember_admin_ai_context(
            data,
            str(plan.get("summary") or plan.get("action") or "confirm"),
            plan,
            result,
        ),
    )
    await state.set_state(AdminStates.waiting_ai_request)
    await callback.message.edit_text(
        f"{result}\n\n🤖 Можно отправить следующую админ-команду.",
        reply_markup=_admin_ai_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reload")
async def admin_reload_presets(callback: types.CallbackQuery):
    """Перезагружает пресеты из JSON"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    # Пресеты теперь не используются
    await callback.answer(
        "✅ Пресеты отключены в этой версии",
        show_alert=True,
    )


@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: types.CallbackQuery):
    """Показывает детальную статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    stats = await get_admin_stats()

    text = f"""
📊 <b>Детальная статистика</b>

👥 <b>Пользователи:</b>
• Всего: <code>{stats['total_users']}</code>
• Активных за 7 дней: <code>{stats['active_users']}</code>
• Забанено: <code>{stats['banned_users']}</code>
• Общий баланс: <code>{stats['total_user_balance']}</code> 🪙

🎨 <b>Генерации:</b>
• Всего: <code>{stats['total_generations']}</code>

💳 <b>Платежи:</b>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽
"""

    await callback.message.edit_text(
        text, reply_markup=_admin_nav_keyboard("admin_back"), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_users")
async def admin_users_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "👤 <b>Пользователь / баланс</b>\n\nВведите Telegram ID пользователя:",
        reply_markup=_admin_nav_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.update_data(admin_user_flow="user")
    await state.set_state(AdminStates.waiting_user_id)


@router.message(AdminStates.waiting_user_id)
async def admin_process_user_id(message: types.Message, state: FSMContext):
    """Обрабатывает ввод ID пользователя"""
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    # Получаем статистику пользователя
    try:
        stats = await get_user_stats(user_id)
    except Exception as e:
        logger.warning(f"User {user_id} not found: {e}")
        await message.answer(f"❌ Пользователь с ID {user_id} не найден.")
        return

    await state.update_data(target_user_id=user_id)
    promos = stats.get("promos") or []
    promo_text = (
        "\n".join(
            f"• <code>{p['code']}</code> −{p['discount_percent']}% ({p['redeemed_at']})"
            for p in promos
        )
        if promos
        else "нет"
    )
    ban_text = "забанен" if stats.get("is_banned") else "активен"
    full_name = " ".join(
        part
        for part in (stats.get("first_name"), stats.get("last_name"))
        if part
    ).strip()
    name_text = html.escape(full_name) if full_name else "не указано"
    username = stats.get("username")
    username_text = f"@{html.escape(username)}" if username else "нет username"
    subscription = stats.get("subscription")
    if subscription:
        subscription_text = (
            f"{html.escape(str(subscription['package_name']))} до "
            f"{html.escape(str(subscription['expires_at']))} "
            f"(фото {int(subscription['images_used'])}/{int(subscription['image_limit'])}, "
            f"видео {int(subscription['videos_used'])}/{int(subscription['video_limit'])})"
        )
    else:
        subscription_text = "нет активной"
    data = await state.get_data()
    if data.get("admin_user_flow") == "ban":
        await set_user_banned(user_id, not bool(stats.get("is_banned")))
        await state.clear()
        await message.answer(
            (
                f"✅ Пользователь <code>{user_id}</code> разбанен."
                if stats.get("is_banned")
                else f"🚫 Пользователь <code>{user_id}</code> забанен."
            ),
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )
        return

    text = f"""
👤 <b>Пользователь</b>

🆔 ID: <code>{user_id}</code>
👤 Имя: <code>{name_text}</code>
🔗 Username: <code>{username_text}</code>
💰 BoomCoin: <code>{stats['credits']}</code>
🧾 Подписка: <code>{subscription_text}</code>
🚦 Статус: <code>{ban_text}</code>
📊 Генераций: <code>{stats['generations']}</code>
💸 Потрачено: <code>{stats['total_spent']}</code>
📅 Регистрация: <code>{stats['member_since']}</code>
🎟 Промокоды:
{promo_text}

Выберите действие:
"""

    await message.answer(
        text,
        reply_markup=_user_actions_keyboard(user_id, bool(stats.get("is_banned"))),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(F.data.startswith("admin_add_credits_"))
async def admin_add_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество BoomCoin для добавления"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_add_credits_", ""))
    await state.update_data(target_user_id=user_id, action="add")

    await callback.message.edit_text(
        f"➕ <b>Добавление BoomCoin</b>"
        f"Пользователь ID: <code>{user_id}</code>"
        f"Введите количество BoomCoin для добавления:",
        reply_markup=_admin_nav_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.callback_query(F.data.startswith("admin_deduct_credits_"))
async def admin_deduct_credits_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает количество BoomCoin для списания"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    user_id = int(callback.data.replace("admin_deduct_credits_", ""))
    await state.update_data(target_user_id=user_id, action="deduct")

    await callback.message.edit_text(
        f"➖ <b>Списание BoomCoin</b>"
        f"Пользователь ID: <code>{user_id}</code>"
        f"Введите количество BoomCoin для списания:",
        reply_markup=_admin_nav_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_credits_amount)


@router.callback_query(F.data.startswith("admin_user_ban_"))
async def admin_ban_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    user_id = int(callback.data.replace("admin_user_ban_", ""))
    await set_user_banned(user_id, True)
    await callback.answer("Пользователь забанен", show_alert=True)


@router.callback_query(F.data.startswith("admin_user_unban_"))
async def admin_unban_user(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    user_id = int(callback.data.replace("admin_user_unban_", ""))
    await set_user_banned(user_id, False)
    await callback.answer("Пользователь разбанен", show_alert=True)


@router.callback_query(F.data == "admin_ban_menu")
async def admin_ban_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await state.update_data(admin_user_flow="ban")
    await callback.message.edit_text(
        "🚫 <b>Бан / разбан</b>\n\nВведите Telegram ID пользователя:",
        reply_markup=_admin_nav_keyboard("admin_back"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(AdminStates.waiting_user_id)


@router.message(AdminStates.waiting_credits_amount)
async def admin_process_credits_amount(message: types.Message, state: FSMContext):
    """Обрабатывает ввод количества BoomCoin"""
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверное количество. Введите положительное число:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    action = data.get("action")

    if action == "add":
        success = await add_credits(user_id, amount, reason="admin_adjustment_add", external_id=f"admin:{message.from_user.id}:add:{user_id}:{message.message_id}")
        action_text = f"добавлено <code>{amount}</code> BoomCoin"
    else:
        # Для списания нужно реализовать deduct_credits_by_admin
        from bot.database import deduct_credits

        success = await deduct_credits(user_id, amount, reason="admin_adjustment_deduct", external_id=f"admin:{message.from_user.id}:deduct:{user_id}:{message.message_id}")
        action_text = f"списано <code>{amount}</code> BoomCoin"

    if success:
        stats = await get_user_stats(user_id)
        await message.answer(
            f"✅ <b>Успешно!</b>"
            f"Пользователь ID: <code>{user_id}</code>\n"
            f"Действие: {action_text}\n"
            f"Текущий баланс: <code>{stats['credits']}</code> BoomCoin",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"❌ Ошибка! Возможно, недостаточно BoomCoin для списания.",
            reply_markup=get_admin_keyboard(),
        )

    await state.clear()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает текст рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "📢 <b>Рассылка всем пользователям</b>"
        "Введите текст сообщения для рассылки:\n"
        "<i>Поддерживается HTML-форматирование</i>",
        reply_markup=_admin_nav_keyboard("admin_back"),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_text)


@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Сохраняет текст и предлагает прикрепить фото"""
    await state.update_data(broadcast_text=message.text, broadcast_photo_id=None)

    await message.answer(
        "🖼 <b>Хотите прикрепить изображение к рассылке?</b>\n\n"
        "Отправьте фото или нажмите «Пропустить».",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="⏭ Пропустить", callback_data="admin_broadcast_skip_photo"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена", callback_data="admin_back"
                    ),
                ],
                [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
            ]
        ),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_broadcast_photo)


@router.message(AdminStates.waiting_broadcast_photo, F.photo)
async def admin_broadcast_photo_received(message: types.Message, state: FSMContext):
    """Получает фото и показывает превью"""
    photo_file_id = message.photo[-1].file_id
    await state.update_data(broadcast_photo_id=photo_file_id)
    await _show_broadcast_preview(message, state)


@router.callback_query(F.data == "admin_broadcast_skip_photo")
async def admin_broadcast_skip_photo(callback: types.CallbackQuery, state: FSMContext):
    """Пропускает фото и показывает превью"""
    await state.update_data(broadcast_photo_id=None)
    await callback.message.delete()
    await _show_broadcast_preview(callback.message, state, from_callback=True)


async def _show_broadcast_preview(
    message: types.Message,
    state: FSMContext,
    from_callback: bool = False,
) -> None:
    """Показывает превью рассылки"""
    data = await state.get_data()
    broadcast_text = data.get("broadcast_text", "")
    photo_id = data.get("broadcast_photo_id")

    confirm_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Отправить", callback_data="admin_broadcast_confirm"
                ),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"),
            ],
            [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
        ]
    )

    photo_hint = "🖼 <i>С изображением</i>" if photo_id else "📝 <i>Только текст</i>"
    preview_text = (
        f"📢 <b>Превью рассылки:</b> {photo_hint}\n"
        "───────────────\n"
        f"{broadcast_text}\n"
        "───────────────\n"
        "Подтверждаете отправку?"
    )

    if photo_id:
        await message.answer_photo(
            photo=photo_id,
            caption=preview_text,
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            preview_text,
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )

    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_execute_broadcast(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Выполняет рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    broadcast_photo_id = data.get("broadcast_photo_id")

    # Если превью было с фото — редактируем caption, иначе текст
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
            )
    except Exception:
        await callback.message.answer(
            "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
        )

    # Получаем всех пользователей
    import aiosqlite

    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT telegram_id FROM users")
        users = await cursor.fetchall()

    success_count = 0
    error_count = 0

    for user in users:
        try:
            if broadcast_photo_id:
                await bot.send_photo(
                    user["telegram_id"],
                    photo=broadcast_photo_id,
                    caption=broadcast_text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    user["telegram_id"], broadcast_text, parse_mode="HTML"
                )
            success_count += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['telegram_id']}: {e}")
            error_count += 1

    result_text = (
        f"📢 <b>Рассылка завершена!</b>\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>"
    )
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                result_text,
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                result_text,
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
    except Exception:
        await callback.message.answer(
            result_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML",
        )

    await state.clear()


@router.callback_query(F.data == "admin_export_users")
async def admin_export_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    rows = await export_users()
    buffer = io.StringIO()
    fieldnames = [
        "telegram_id",
        "credits",
        "is_banned",
        "has_paid",
        "referral_code",
        "referral_earned",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    csv_bytes = buffer.getvalue().encode("utf-8-sig")
    await callback.message.answer_document(
        types.BufferedInputFile(csv_bytes, filename="users_export.csv"),
        caption=f"📦 Экспорт пользователей: {len(rows)} строк",
        reply_markup=get_admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_maintenance")
async def admin_maintenance(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    enabled = (await get_bot_setting("maintenance_mode", "0")) == "1"
    await callback.message.edit_text(
        "⚙️ <b>Техрежим</b>\n\n"
        f"Сейчас: <code>{'включён' if enabled else 'выключен'}</code>\n\n"
        "Когда техрежим включён, обычные пользователи получают сообщение о работах. "
        "Админы продолжают пользоваться ботом.",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Выключить" if enabled else "Включить",
                        callback_data="admin_maintenance_toggle",
                    )
                ],
                [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
                [types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_maintenance_toggle")
async def admin_maintenance_toggle(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    enabled = (await get_bot_setting("maintenance_mode", "0")) == "1"
    await set_bot_setting("maintenance_mode", "0" if enabled else "1")
    await callback.answer(
        "Техрежим выключен" if enabled else "Техрежим включён",
        show_alert=True,
    )
    await admin_maintenance(callback)


@router.callback_query(F.data == "admin_promos")
async def admin_promos_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    promos = await get_promo_codes(limit=8)
    lines = [
        "🎟 <b>Промокоды</b>",
        "",
        "Скидка: <code>КОД discount ПРОЦЕНТ ЛИМИТ [YYYY-MM-DD]</code>",
        "BoomCoin: <code>КОД boomcoin КОЛ-ВО ЛИМИТ [YYYY-MM-DD]</code>",
        "Генерации: <code>КОД generation КОЛ-ВО ЛИМИТ [YYYY-MM-DD]</code>",
        "Старый формат тоже работает: <code>START20 20 50</code>",
        "",
        "<b>Последние коды:</b>",
    ]
    if promos:
        for promo in promos:
            status = "✅" if promo["is_active"] else "⛔"
            expires = promo["expires_at"] or "без срока"
            if promo.get("promo_type") == "bananas":
                promo_value = f"+{promo['reward_credits']}🪙"
            elif promo.get("promo_type") == "generation":
                promo_value = f"{promo['reward_credits']} free gen"
            else:
                promo_value = f"−{promo['discount_percent']}%"
            lines.append(
                f"{status} <code>{promo['code']}</code> — "
                f"{promo_value}, {promo['used_count']}/{promo['max_uses']}, до {expires}"
            )
    else:
        lines.append("Пока промокодов нет.")

    keyboard_rows = [[
        types.InlineKeyboardButton(
            text="➕ Создать промокод",
            callback_data="admin_promo_create",
        )
    ]]
    for promo in promos[:5]:
        if promo["is_active"]:
            keyboard_rows.append([
                types.InlineKeyboardButton(
                    text=f"🗑 {promo['code']}",
                    callback_data=f"admin_promo_delete_{promo['code']}",
                )
            ])
    keyboard_rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    keyboard_rows.append([types.InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(AdminStates.waiting_promo_data)


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    await callback.message.edit_text(
        "➕ <b>Создание промокода</b>\n\n"
        "Отправьте одной строкой:\n"
        "<code>КОД discount ПРОЦЕНТ ЛИМИТ [YYYY-MM-DD]</code>\n"
        "<code>КОД boomcoin КОЛ-ВО ЛИМИТ [YYYY-MM-DD]</code>\n\n"
        "<code>КОД generation КОЛ-ВО_ГЕНЕРАЦИЙ ЛИМИТ [YYYY-MM-DD]</code>\n\n"
        "Пример:\n"
        "<code>START20 discount 20 50 2026-06-01</code>\n"
        "<code>PARTNER50 boomcoin 50 200</code>\n"
        "<code>FREEGEN generation 1 100</code>\n\n"
        "Старый формат для скидки тоже работает:\n"
        "<code>VIP15 15 10</code>",
        reply_markup=_admin_nav_keyboard("admin_promos"),
        parse_mode="HTML",
    )
    await callback.answer()
    await state.set_state(AdminStates.waiting_promo_data)


@router.callback_query(F.data.startswith("admin_promo_delete_"))
async def admin_promo_delete(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    code = callback.data.replace("admin_promo_delete_", "", 1)
    deleted = await deactivate_promo_code(code)
    await callback.answer(
        "Промокод отключён" if deleted else "Промокод не найден",
        show_alert=True,
    )


@router.message(AdminStates.waiting_promo_data)
async def admin_process_promo_data(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return

    parts = message.text.strip().split()
    if len(parts) not in {3, 4, 5}:
        await message.answer(
            "❌ Неверный формат.\n\n"
            "Нужно: <code>КОД discount ПРОЦЕНТ ЛИМИТ [YYYY-MM-DD]</code>\n"
            "или <code>КОД boomcoin КОЛ-ВО ЛИМИТ [YYYY-MM-DD]</code>\n"
            "или <code>КОД generation КОЛ-ВО ЛИМИТ [YYYY-MM-DD]</code>",
            parse_mode="HTML",
        )
        return

    code = re.sub(r"[^A-Za-z0-9_-]", "", parts[0]).upper()
    promo_type = "discount"
    value_index = 1
    if len(parts) >= 4 and parts[1].lower() in {"discount", "sale", "скидка"}:
        promo_type = "discount"
        value_index = 2
    elif len(parts) >= 4 and parts[1].lower() in {"boomcoin", "bananas", "banana", "credits", "free"}:
        promo_type = "bananas"
        value_index = 2
    elif len(parts) >= 4 and parts[1].lower() in {"generation", "generations", "gen", "free_generation", "генерация", "генерации"}:
        promo_type = "generation"
        value_index = 2

    try:
        value = int(parts[value_index])
        max_uses = int(parts[value_index + 1])
        if max_uses <= 0:
            raise ValueError
        if promo_type == "discount" and (value <= 0 or value >= 100):
            raise ValueError
        if promo_type == "bananas" and value <= 0:
            raise ValueError
        if promo_type == "generation" and value <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await message.answer(
            "❌ Проверьте значение и лимит.\n"
            "Скидка: 1-99%, BoomCoin: больше 0, лимит: больше 0."
        )
        return

    expires_at = None
    date_index = value_index + 2
    if len(parts) > date_index:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[date_index]):
            await message.answer(
                "❌ Дата должна быть в формате <code>YYYY-MM-DD</code>.",
                parse_mode="HTML",
            )
            return
        expires_at = f"{parts[date_index]} 23:59:59"

    ok, result = await create_promo_code(
        code=code,
        discount_percent=value if promo_type == "discount" else 0,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=message.from_user.id,
        promo_type=promo_type,
        reward_credits=value if promo_type in {"bananas", "generation"} else 0,
    )
    if not ok:
        reason = {
            "exists": "Промокод с таким кодом уже существует.",
            "empty_code": "Код не должен быть пустым.",
            "bad_type": "Тип должен быть discount, boomcoin или generation.",
            "bad_discount": "Скидка должна быть от 1 до 99%.",
            "bad_reward": "Количество BoomCoin должно быть больше нуля.",
            "bad_max_uses": "Лимит должен быть больше нуля.",
        }.get(result, "Не удалось создать промокод.")
        await message.answer(f"❌ {reason}")
        return

    await state.clear()
    await message.answer(
        "✅ <b>Промокод создан</b>\n\n"
        f"Код: <code>{result}</code>\n"
        f"Тип: <code>{ {'bananas': 'бесплатные BoomCoin', 'generation': 'бесплатная генерация'}.get(promo_type, 'скидка') }</code>\n"
        f"Значение: <code>{value}{' 🪙' if promo_type == 'bananas' else ' генерац.' if promo_type == 'generation' else '%'}</code>\n"
        f"Лимит: <code>{max_uses}</code> активаций\n"
        f"Срок: <code>{expires_at or 'без срока'}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_back")
async def admin_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в админ-меню"""
    await state.clear()
    stats = await get_admin_stats()

    text = f"""
🔧 <b>Админ-панель</b>

📊 <b>Статистика:</b>
• Пользователей: <code>{stats['total_users']}</code>
• Генераций: <code>{stats['total_generations']}</code>
• Транзакций: <code>{stats['total_transactions']}</code>
• Выручка: <code>{stats['total_revenue']:.0f}</code> ₽

Выберите действие:
"""

    await callback.message.edit_text(
        text, reply_markup=get_admin_keyboard(), parse_mode="HTML"
    )


# ---------------------------------------------------------------------------
# Price editing
# ---------------------------------------------------------------------------


def _load_price_json() -> dict:
    with open(PRICE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_price_json(data: dict):
    with open(PRICE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    preset_manager.reload()


@router.callback_query(F.data == "admin_prices")
async def admin_prices_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await callback.message.edit_text(
        "💰 <b>Управление ценами</b>\n\nВыберите категорию:",
        reply_markup=get_admin_prices_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_price_cat_image")
async def admin_price_cat_image(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    price_config = _load_price_json()
    await callback.message.edit_text(
        "🖼 <b>Цены на изображения</b>\n\nНажмите на модель для изменения цены:",
        reply_markup=get_admin_price_image_keyboard(price_config),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_price_cat_video")
async def admin_price_cat_video(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    price_config = _load_price_json()
    await callback.message.edit_text(
        "🎬 <b>Цены на видео</b>\n\nНажмите на модель для изменения цены:",
        reply_markup=get_admin_price_video_keyboard(price_config),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_img_"))
async def admin_price_img_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.removeprefix("admin_price_img_")
    price_config = _load_price_json()
    current = (
        price_config.get("costs_reference", {}).get("image_models", {}).get(key, "?")
    )
    await state.update_data(price_type="image", price_key=key)
    await state.set_state(AdminStates.waiting_price_value)
    await callback.message.edit_text(
        f"🖼 <b>Изменение цены: <code>{key}</code></b>\n\n"
        f"Текущая цена: <code>{current}</code> 🪙\n\n"
        f"Введите новую цену (целое число):",
        reply_markup=_admin_nav_keyboard("admin_price_cat_image"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_price_vid_"))
async def admin_price_vid_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    key = callback.data.removeprefix("admin_price_vid_")
    price_config = _load_price_json()
    model_data = (
        price_config.get("costs_reference", {}).get("video_models", {}).get(key, {})
    )

    if "fixed_cost" in model_data:
        hint = (
            f"Текущая цена: <code>{model_data['fixed_cost']}</code> 🪙 (фиксированная)\n\n"
            f"Введите новую цену (целое число):"
        )
        await state.update_data(price_type="video_fixed", price_key=key)
    else:
        current = model_data.get("per_second", model_data.get("base", "?"))
        hint = (
            f"Текущая цена: <code>{current}</code> 🪙 за 1 секунду\n\n"
            f"Введите новую цену за <b>1 секунду</b> (целое число):"
        )
        await state.update_data(price_type="video_per_second", price_key=key)

    await state.set_state(AdminStates.waiting_price_value)
    await callback.message.edit_text(
        f"🎬 <b>Изменение цены: <code>{key}</code></b>\n\n{hint}",
        reply_markup=_admin_nav_keyboard("admin_price_cat_video"),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_price_value)
async def admin_process_price_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    price_type = data.get("price_type")
    price_key = data.get("price_key")
    text = message.text.strip()

    try:
        price_config = _load_price_json()
        costs = price_config.setdefault("costs_reference", {})

        if price_type == "image":
            new_price = int(text)
            costs.setdefault("image_models", {})[price_key] = new_price
            _save_price_json(price_config)
            await state.clear()
            await message.answer(
                f"✅ Цена для <code>{price_key}</code> обновлена: <b>{new_price}</b> 🪙",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )

        elif price_type == "video_fixed":
            new_price = int(text)
            model_data = costs.setdefault("video_models", {}).setdefault(price_key, {})
            model_data["fixed_cost"] = new_price
            model_data["base"] = new_price
            _save_price_json(price_config)
            await state.clear()
            await message.answer(
                f"✅ Цена для <code>{price_key}</code> обновлена: <b>{new_price}</b> 🪙",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )

        elif price_type == "video_per_second":
            new_price = int(text)
            if new_price <= 0:
                raise ValueError("Price must be positive")
            model_data = costs.setdefault("video_models", {}).setdefault(price_key, {})
            model_data["per_second"] = new_price
            model_data["base"] = new_price
            _save_price_json(price_config)
            await state.clear()
            await message.answer(
                f"✅ Цена для <code>{price_key}</code> обновлена: "
                f"<b>{new_price}</b> 🪙/сек",
                reply_markup=get_admin_keyboard(),
                parse_mode="HTML",
            )
        else:
            await state.clear()
            await message.answer(
                "❌ Неизвестный тип цены.", reply_markup=get_admin_keyboard()
            )

    except ValueError as e:
        await message.answer(
            f"❌ Неверный формат: <code>{e}</code>\n\nПопробуйте ещё раз:",
            parse_mode="HTML",
        )
