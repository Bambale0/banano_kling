"""Persistent Telegram promo editor. FSM holds navigation, never the only draft copy."""
from __future__ import annotations

import asyncio
import copy
import html
import logging
import secrets
from collections import Counter
from datetime import datetime, timezone
from weakref import WeakValueDictionary

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import config

logger = logging.getLogger(__name__)
router = Router(name="promo_admin")
_LOCKS: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()
PREFIX = "admin_pr"
PAGE_SIZE = 8
STATUS_LABELS = {
    "draft": "Черновик", "ready": "Готов к отправке", "queued": "В очереди",
    "running": "Рассылается", "sending": "Отправляется", "completed": "Завершено",
    "cancelled": "Отменено", "failed": "Ошибка", "paused": "Приостановлено",
}


def _status(value):
    return html.escape(STATUS_LABELS.get(str(value), str(value)))


def _tested_at(promo):
    value = promo.get("tested_at")
    if not value:
        return "—"
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        return html.escape(str(value))


class PromoAdminStates(StatesGroup):
    text = State()
    media = State()
    button_label = State()
    trend_query = State()


def _service():
    from bot import promo_campaigns
    return promo_campaigns


def _lock(event):
    message = getattr(event, "message", None) or event
    chat = getattr(message, "chat", None)
    key = (event.from_user.id, chat.id if chat else event.from_user.id)
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def _button(text, data):
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Callback exceeds Telegram limit")
    return types.InlineKeyboardButton(text=text, callback_data=data)


def _keyboard(rows):
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def _cb(action, promo, token, arg=None):
    value = f"{PREFIX}:{action}:{promo['id']}:{promo['revision']}:{token}"
    return value if arg is None else f"{value}:{arg}"


def _editable(promo):
    return promo.get("status") in {"draft", "ready"}


def _ready(promo):
    summary = promo.get("test_summary") or {}
    return bool(
        _editable(promo)
        and promo.get("ready")
        and promo.get("content_hash")
        and promo.get("tested_content_hash") == promo.get("content_hash")
        and summary.get("content_hash") == promo.get("content_hash")
        and int(summary.get("sent") or 0) >= 1
    )


async def _authorized(event):
    if event.from_user and config.is_admin(event.from_user.id):
        return True
    if hasattr(event, "data"):
        await event.answer("⛔ Нет доступа", show_alert=True)
    else:
        await event.answer("⛔ Нет доступа")
    return False


async def _reset(state, **data):
    old = await state.get_data()
    closed = list(dict.fromkeys(
        old.get("promo_closed_groups", []) + old.get("promo_media_groups", [])
    ))[-50:]
    await state.clear()
    await state.update_data(promo_closed_groups=closed, **data)


async def _present(event, text, markup, *, fresh=False):
    if hasattr(event, "data"):
        if event.message is None:
            return await event.bot.send_message(event.from_user.id, text, parse_mode="HTML", reply_markup=markup)
        if not fresh:
            try:
                return await event.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return event.message
                # Old cards may have been deleted or contain media instead of text.
        return await event.message.answer(text, parse_mode="HTML", reply_markup=markup)
    return await event.answer(text, parse_mode="HTML", reply_markup=markup)


def _summary(promo):
    message = promo["message"]
    media = message.get("media") or []
    titles = promo.get("trend_titles") or {}
    rows = [
        f"📢 <b>Промо #{promo['id']}</b> · версия {promo['revision']}",
        f"Статус: <b>{_status(promo['status'])}</b>",
        f"Формат: {'HTML' if message.get('parse_mode') else 'обычный текст'}",
        f"Медиа: {len(media)}/10 · фото {sum(m['type'] == 'photo' for m in media)}, видео {sum(m['type'] == 'video' for m in media)}",
    ]
    for index, item in enumerate(media):
        rows.append(f"  {index + 1}. {'Фото' if item['type'] == 'photo' else 'Видео'}")
    rows.append(f"Кнопки: {len(message.get('buttons') or [])}/2 (вертикально)")
    for button in message.get("buttons") or []:
        trend_id = button["trend_id"]
        title = titles.get(str(trend_id), titles.get(trend_id, f"Тренд #{trend_id}"))
        rows.append(f"  {html.escape(button['text'])} → {html.escape(str(title)[:80])} (#{trend_id})")
    text = str(message.get("text") or "")
    rows.extend(["", "<b>Текст</b> (разметка показана буквально):", html.escape(text[:600]) or "—"])
    if len(text) > 600:
        rows.append(f"… всего {len(text)} символов; полный текст придёт при тесте")
    test = promo.get("test_summary") or {}
    if test:
        rows.extend(["", f"Тест: {_status(test.get('status') or '—')}",
                     f"Доставлено: {test.get('sent', 0)} · ожидают: {test.get('pending', 0)} · ошибок: {test.get('failed', 0)} · неясный результат: {test.get('uncertain', 0)}"])
        errors = Counter(str(item.get("code") or "unknown") for item in test.get("errors", []))
        rows.extend(f"  {html.escape(code[:80])}: {count}" for code, count in list(errors.items())[:4])
        for error in test.get("errors", [])[:4]:
            rows.append(f"  Админ {html.escape(str(error.get('telegram_id', '—')))}: {html.escape(str(error.get('code') or 'unknown')[:80])}")
        if len(test.get("errors", [])) > 4:
            rows.append(f"  Ещё ошибок: {len(test['errors']) - 4}")
        rows.append(f"Последняя успешная доставка теста: {_tested_at(promo)}")
    rows.extend(["", "✅ Тест доставлен. Проверьте сообщение и каждую кнопку в Telegram перед рассылкой" if _ready(promo) else "После любых изменений нужен успешный тест текущей версии"])
    if not _editable(promo):
        rows.extend(["", "Снимок рассылки доступен только для чтения",
                     f"Отправлено: {promo.get('sent_count', 0)} · ошибок: {promo.get('failed_count', 0)} · заблокировали: {promo.get('blocked_count', 0)} · в очереди: {promo.get('queued_count', 0)}"])
        for group in (promo.get("error_groups") or [])[:4]:
            rows.append(f"  {html.escape(str(group.get('code') or 'unknown')[:80])}: {group.get('count', 0)}")
    return "\n".join(rows)


async def _view(event, state, promo, *, notice=""):
    token = secrets.token_hex(4)
    await _reset(state, promo_id=promo["id"], promo_revision=promo["revision"], promo_token=token, promo_screen="view")
    rows = []
    if _editable(promo):
        rows += [[_button("✏️ Текст", _cb("text", promo, token)), _button("🖼 Медиа", _cb("media", promo, token))],
                 [_button("🔘 Кнопки", _cb("buttons", promo, token))],
                 [_button("🧪 Тест на админах", _cb("test", promo, token))]]
        if _ready(promo):
            rows.append([_button("📨 Разослать всем…", _cb("confirm", promo, token))])
    rows += [[_button("🔄 Обновить статус", f"{PREFIX}:open:{promo['id']}")],
             [_button("📋 Дублировать", _cb("dup", promo, token))],
             [_button("💾 К списку (всё сохранено)", f"{PREFIX}:list:0")]]
    text = (html.escape(notice) + "\n\n" if notice else "") + _summary(promo)
    await _present(event, text, _keyboard(rows))


async def _list(event, state, before=0):
    promos = await _service().list_promos(event.from_user.id, limit=PAGE_SIZE + 1, before=before or None)
    token = secrets.token_hex(4)
    await _reset(state, promo_token=token, promo_screen="list")
    rows = [[_button("➕ Новое промо", f"{PREFIX}:new:{token}")]]
    for promo in promos[:PAGE_SIZE]:
        preview = str(promo["message"].get("text") or "Медиа без текста").replace("\n", " ")[:35]
        rows.append([_button(f"#{promo['id']} · {STATUS_LABELS.get(promo['status'], promo['status'])} · {preview}", f"{PREFIX}:open:{promo['id']}")])
    if len(promos) > PAGE_SIZE:
        rows.append([_button("Дальше →", f"{PREFIX}:list:{promos[PAGE_SIZE - 1]['id']}")])
    if before:
        rows.append([_button("← Сначала", f"{PREFIX}:list:0")])
    rows.append([_button("← Админ-панель", "admin_back")])
    await _present(event, "📢 <b>Промо-рассылки</b>\n\nЧерновики сохраняются после каждого изменения. Перед рассылкой обязателен «Тест на админах».\n\nЧерновики и история:", _keyboard(rows))


async def open_promos(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    try:
        async with _lock(callback):
            await _list(callback, state)
    except _service().PromoError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Promo admin list failed: admin=%s", callback.from_user.id)
        await callback.answer("Не удалось открыть промо. Попробуйте позже.", show_alert=True)
        return
    await callback.answer()


def _cancel_keyboard(promo, token):
    return _keyboard([[_button("Отмена → к промо", _cb("cancel", promo, token))]])


async def _input(event, state, promo, kind, prompt, **values):
    token = secrets.token_hex(4)
    await _reset(state, promo_id=promo["id"], promo_revision=promo["revision"], promo_token=token, promo_screen=kind, **values)
    await state.set_state(getattr(PromoAdminStates, kind))
    rows = [[_button("Отмена → к промо", _cb("cancel", promo, token))]]
    if kind == "text":
        rows.insert(0, [_button("Переключить HTML / обычный", _cb("format", promo, token)), _button("Удалить текст", _cb("clear", promo, token))])
    if kind == "media":
        rows = _media_rows(promo, token)
    sent = await _present(event, prompt, _keyboard(rows), fresh=True)
    await state.update_data(promo_input_after=getattr(sent, "message_id", 0))


def _media_rows(promo, token):
    rows = []
    for index, item in enumerate(promo["message"].get("media") or []):
        row = [_button(f"Удалить {index + 1} ({'фото' if item['type'] == 'photo' else 'видео'})", _cb("remove", promo, token, index))]
        if index:
            row.append(_button("↑", _cb("up", promo, token, index)))
        rows.append(row)
    rows += [[_button("Готово", _cb("done", promo, token))], [_button("Назад (загруженное сохранено)", _cb("cancel", promo, token))]]
    return rows


async def _media_view(event, state, promo):
    token = secrets.token_hex(4)
    await state.update_data(promo_revision=promo["revision"], promo_token=token)
    await _present(event, f"🖼 Медиа сохранены: {len(promo['message'].get('media') or [])}/10\n\nОтправьте фото, видео или альбом. Порядок альбома сохраняется. Когда все файлы появятся здесь, нажмите «Готово» в последнем сообщении. Тест и рассылка сами не запускаются.", _keyboard(_media_rows(promo, token)))


async def _buttons_view(event, state, promo):
    token = secrets.token_hex(4)
    await _reset(state, promo_id=promo["id"], promo_revision=promo["revision"], promo_token=token, promo_screen="buttons")
    buttons = promo["message"].get("buttons") or []
    rows = []
    for index, button in enumerate(buttons):
        rows.append([_button(f"✏️ {button['text']}", _cb("label", promo, token, index)), _button("Удалить", _cb("delbtn", promo, token, index))])
    if len(buttons) < 2:
        rows.append([_button("➕ Добавить кнопку", _cb("label", promo, token, len(buttons)))])
    if len(buttons) == 2:
        rows.append([_button("↑↓ Поменять порядок", _cb("swap", promo, token))])
    rows.append([_button("Готово", _cb("cancel", promo, token))])
    await _present(event, "🔘 <b>Кнопки промо</b>\n\nНе более двух, каждая в отдельной строке. Подпись и существующий опубликованный тренд сохраняются вместе. Ссылку вводить не нужно.\n\n" + _summary(promo), _keyboard(rows))


async def _search(event, state, promo, query, page=0):
    result = await _service().search_trends(query, page=page, size=PAGE_SIZE)
    token = secrets.token_hex(4)
    items = result["items"]
    await state.update_data(promo_token=token, promo_query=query, promo_candidates=items, promo_screen="search")
    rows = [[_button(f"{item['title'][:42]} · #{item['id']}", _cb("pick", promo, token, index))] for index, item in enumerate(items)]
    pages = []
    if page:
        pages.append(_button("← Назад", _cb("page", promo, token, page - 1)))
    if result.get("has_more"):
        pages.append(_button("Дальше →", _cb("page", promo, token, page + 1)))
    if pages:
        rows.append(pages)
    rows.append([_button("Отмена → к промо", _cb("cancel", promo, token))])
    await _present(event, "🔎 <b>Выберите тренд</b>\n" + f"Поиск: {html.escape(query) or 'все доступные'} · страница {page + 1}\n\n" + ("Ничего не найдено.\n" if not items else "") + "Можно прислать другое название или ID. Показаны только опубликованные доступные тренды.", _keyboard(rows))


async def _checked(callback, state, parts):
    if len(parts) not in {5, 6}:
        raise ValueError("invalid callback")
    promo_id, revision = int(parts[2]), int(parts[3])
    data = await state.get_data()
    if data.get("promo_id") != promo_id or data.get("promo_token") != parts[4]:
        raise ValueError("expired screen")
    promo = await _service().get_promo(promo_id, callback.from_user.id)
    if promo["revision"] != revision:
        raise ValueError("stale revision")
    return promo, data


async def _save(promo, admin_id, message):
    return await _service().save_promo(promo["id"], admin_id, message, expected_revision=promo["revision"])


@router.callback_query(F.data.startswith(f"{PREFIX}:"))
async def promo_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await _authorized(callback):
        return
    try:
        async with _lock(callback):
            await _dispatch(callback, state)
    except _service().PromoError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except (ValueError, IndexError, KeyError):
        await callback.answer("Экран устарел. Откройте промо заново из списка.", show_alert=True)
        return
    except Exception:
        logger.exception("Promo admin callback failed: admin=%s", callback.from_user.id)
        await callback.answer("Не удалось выполнить действие. Обновите статус промо.", show_alert=True)
        return
    await callback.answer()


async def _dispatch(callback, state):
    parts = str(callback.data).split(":")
    action = parts[1]
    admin_id = callback.from_user.id
    if action == "list" and len(parts) == 3:
        await _list(callback, state, int(parts[2]))
        return
    if action == "open" and len(parts) == 3:
        await _view(callback, state, await _service().get_promo(int(parts[2]), admin_id))
        return
    if action == "new" and len(parts) == 3:
        data = await state.get_data()
        if data.get("promo_screen") != "list" or data.get("promo_token") != parts[2]:
            raise ValueError("expired create")
        promo = await _service().create_promo(admin_id, idempotency_key=f"telegram:{admin_id}:{parts[2]}")
        await _view(callback, state, promo, notice="Черновик создан и сохранён")
        return
    promo, data = await _checked(callback, state, parts)
    token = parts[4]
    if action in {"cancel", "done"}:
        await _view(callback, state, promo)
        return
    if action == "dup":
        await _view(callback, state, await _service().duplicate_promo(promo["id"], admin_id), notice="Создана копия. Перед отправкой нужен новый тест")
        return
    if not _editable(promo):
        raise ValueError("read-only campaign")
    message = copy.deepcopy(promo["message"])
    if action == "text":
        await _input(callback, state, promo, "text", "✏️ Пришлите новый текст. Текущий формат: " + ("HTML" if message.get("parse_mode") else "обычный") + ".\n\nДля удаления текста нажмите «Удалить текст». Максимум 4096 символов без медиа или с альбомом; 1024 с одним фото/видео. Изменение сбросит готовность к рассылке.")
    elif action in {"clear", "format"}:
        if action == "clear":
            message["text"] = ""
        else:
            message["parse_mode"] = None if message.get("parse_mode") else "HTML"
        await _view(callback, state, await _save(promo, admin_id, message))
    elif action == "media":
        await _input(callback, state, promo, "media", "🖼 Отправьте до 10 фото/видео, в том числе альбомом. Каждый файл сохраняется в черновик. Подпись первого файла добавится, если текст пустой.\n\nДождитесь всех файлов и нажмите «Готово» в последнем сообщении. Не нужно отправлять альбом повторно.", promo_media_base=message.get("media") or [], promo_media_entries=[], promo_media_groups=[])
    elif action in {"remove", "up"}:
        index = int(parts[5])
        if index < 0 or index >= len(message["media"]) or (action == "up" and index == 0):
            raise ValueError("invalid media index")
        if action == "remove":
            message["media"].pop(index)
        else:
            message["media"][index - 1], message["media"][index] = message["media"][index], message["media"][index - 1]
        promo = await _save(promo, admin_id, message)
        # A manual reordering establishes the next upload's base order.
        await state.update_data(promo_media_base=message["media"], promo_media_entries=[])
        await _media_view(callback, state, promo)
    elif action == "buttons":
        await _buttons_view(callback, state, promo)
    elif action == "label":
        index = int(parts[5])
        if not 0 <= index <= len(message.get("buttons") or []) or index >= 2:
            raise ValueError("invalid button index")
        await _input(callback, state, promo, "button_label", "🔘 Пришлите подпись кнопки (1–64 символа). Затем выберите существующий тренд. До выбора тренда изменения не сохраняются.", promo_button_index=index)
    elif action in {"delbtn", "swap"}:
        if action == "delbtn":
            index = int(parts[5])
            if index < 0:
                raise ValueError("invalid button index")
            message["buttons"].pop(index)
        else:
            message["buttons"].reverse()
        for index, button in enumerate(message["buttons"]):
            button["position"] = index + 1
        await _buttons_view(callback, state, await _save(promo, admin_id, message))
    elif action == "page":
        if data.get("promo_screen") != "search":
            raise ValueError("expired search")
        page = int(parts[5])
        if page < 0:
            raise ValueError("invalid page")
        await _search(callback, state, promo, data.get("promo_query", ""), page)
    elif action == "pick":
        if data.get("promo_screen") != "search" or await state.get_state() != PromoAdminStates.trend_query.state:
            raise ValueError("expired search")
        candidate_index = int(parts[5])
        if candidate_index < 0:
            raise ValueError("invalid candidate")
        candidate = data["promo_candidates"][candidate_index]
        index = data["promo_button_index"]
        button = {"position": index + 1, "text": data["promo_button_label"], "action": "trend", "trend_id": candidate["id"]}
        buttons = message.setdefault("buttons", [])
        if index == len(buttons):
            buttons.append(button)
        else:
            buttons[index] = button
        await _buttons_view(callback, state, await _save(promo, admin_id, message))
    elif action == "test":
        await _service().test_promo(promo["id"], admin_id, callback.bot, expected_revision=promo["revision"], idempotency_key=f"telegram:{promo['id']}:{promo['revision']}:{token}")
        await _view(callback, state, await _service().get_promo(promo["id"], admin_id), notice="Тест поставлен в очередь для админов. Обновите статус после доставки")
    elif action == "confirm":
        if not _ready(promo):
            raise ValueError("test required")
        confirmation_token = secrets.token_hex(4)
        await _reset(state, promo_id=promo["id"], promo_revision=promo["revision"], promo_token=confirmation_token, promo_screen="confirm", promo_confirm_hash=promo["content_hash"], promo_confirm_audience=promo["audience_count"])
        text = "⚠️ <b>Подтверждение массовой рассылки</b>\n" + f"Получателей: <b>{promo['audience_count']}</b>\nВерсия: {promo['revision']}\n\n" + _summary(promo) + "\n\nПроверьте тестовое сообщение и каждую кнопку. Отправить эту версию всем указанным получателям?"
        await _present(callback, text, _keyboard([[_button(f"Да, отправить {promo['audience_count']} получателям", _cb("send", promo, confirmation_token))], [_button("Отмена", _cb("cancel", promo, confirmation_token))]]))
    elif action == "send":
        if data.get("promo_screen") != "confirm" or not _ready(promo):
            raise ValueError("confirmation required")
        await _service().start_promo(promo["id"], admin_id, callback.bot, expected_revision=promo["revision"], expected_hash=data["promo_confirm_hash"], expected_audience=data["promo_confirm_audience"])
        await _view(callback, state, await _service().get_promo(promo["id"], admin_id), notice="Рассылка поставлена в очередь. Повторно запускать её не нужно")
    else:
        raise ValueError("unknown callback")


@router.message(PromoAdminStates.text)
@router.message(PromoAdminStates.media)
@router.message(PromoAdminStates.button_label)
@router.message(PromoAdminStates.trend_query)
async def promo_message(message: types.Message, state: FSMContext):
    if not await _authorized(message):
        return
    try:
        async with _lock(message):
            await _receive(message, state)
    except _service().PromoError as exc:
        await message.answer(str(exc), parse_mode=None)
    except (ValueError, IndexError, KeyError):
        await message.answer("Ввод устарел или промо изменено. Откройте его заново через /admin → Рассылка.")
    except Exception:
        logger.exception("Promo admin input failed: admin=%s", message.from_user.id)
        await message.answer("Не удалось сохранить изменение. Откройте промо заново и проверьте сохранённую версию.")


def _message_text(message, parse_mode, *, caption=False):
    raw = (message.caption if caption else message.text) or ""
    entities = message.caption_entities if caption else message.entities
    if parse_mode == "HTML" and entities:
        return message.html_caption if caption else message.html_text
    return raw


async def _receive(message, state):
    current = await state.get_state()
    if current not in {PromoAdminStates.text.state, PromoAdminStates.media.state, PromoAdminStates.button_label.state, PromoAdminStates.trend_query.state}:
        raise ValueError("input closed")
    data = await state.get_data()
    # A fresh prompt has a later Telegram message id than an older album. This
    # also rejects queued updates that arrive after cancellation/new navigation.
    if message.message_id <= int(data.get("promo_input_after") or 0):
        raise ValueError("input predates prompt")
    seen = data.get("promo_seen_messages", [])
    if message.message_id in seen:
        return
    promo = await _service().get_promo(data["promo_id"], message.from_user.id)
    if not _editable(promo) or promo["revision"] != data["promo_revision"]:
        raise ValueError("stale revision")
    content = copy.deepcopy(promo["message"])
    if current == PromoAdminStates.text.state:
        if message.text is None or message.text.startswith("/"):
            await message.answer("Пришлите текст или нажмите «Отмена» в сообщении редактора.")
            return
        content["text"] = _message_text(message, content.get("parse_mode"))
        await _view(message, state, await _save(promo, message.from_user.id, content), notice="Текст сохранён. Перед отправкой нужен тест этой версии")
    elif current == PromoAdminStates.media.state:
        group = str(message.media_group_id or "")
        if group and group in data.get("promo_closed_groups", []):
            raise ValueError("closed album")
        if message.photo:
            item = {"type": "photo", "file_id": message.photo[-1].file_id}
        elif message.video:
            item = {"type": "video", "file_id": message.video.file_id}
        else:
            await message.answer("Здесь принимаются только фото и видео. Для текста нажмите «Готово», затем «Текст».")
            return
        if len(content.get("media") or []) >= 10:
            await message.answer("Уже сохранено 10 файлов. Удалите лишний перед добавлением нового.")
            return
        entries = list(data.get("promo_media_entries", []))
        entries.append({"message_id": message.message_id, "item": item, "caption": _message_text(message, content.get("parse_mode"), caption=True)})
        entries.sort(key=lambda entry: entry["message_id"])
        content["media"] = list(data.get("promo_media_base", [])) + [entry["item"] for entry in entries]
        if not content.get("text"):
            content["text"] = next((entry["caption"] for entry in entries if entry["caption"]), "")
        promo = await _save(promo, message.from_user.id, content)
        groups = list(data.get("promo_media_groups", []))
        if group and group not in groups:
            groups.append(group)
        await state.update_data(promo_media_entries=entries, promo_media_groups=groups, promo_seen_messages=(seen + [message.message_id])[-100:])
        await _media_view(message, state, promo)
    elif current == PromoAdminStates.button_label.state:
        label = str(message.text or "").strip()
        if not label or len(label) > 64 or label.startswith("/"):
            await message.answer("Нужна подпись длиной от 1 до 64 символов.")
            return
        await state.update_data(promo_button_label=label, promo_seen_messages=(seen + [message.message_id])[-100:])
        await state.set_state(PromoAdminStates.trend_query)
        sent = await message.answer("🔎 Пришлите название или ID существующего тренда. Для просмотра всех доступных отправьте *", reply_markup=_cancel_keyboard(promo, data["promo_token"]))
        await state.update_data(promo_input_after=getattr(sent, "message_id", message.message_id))
    else:
        if not message.text or message.text.startswith("/"):
            await message.answer("Пришлите название, ID тренда или * для списка.")
            return
        query = message.text.strip()
        if len(query) > 160:
            await message.answer("Для поиска используйте не более 160 символов.")
            return
        await _search(message, state, promo, "" if query == "*" else query)
