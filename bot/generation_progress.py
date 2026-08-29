"""Provider-agnostic Telegram progress indicator for generation tasks.

The bot already persists every launched generation in ``generation_tasks``.  This
module uses that single source of truth instead of inventing provider-specific
percentages: while a task is pending/processing it animates an indeterminate bar,
then switches the same Telegram message to a terminal completed/failed state.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any, Iterable

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot import db as db_backend
from bot.database import DATABASE_PATH

logger = logging.getLogger(__name__)

_PROGRESS_PREFIX = "⏳ <code>"
_PROGRESS_LINE_RE = re.compile(r"^⏳ <code>[^<]+</code>.*$", re.MULTILINE)
_TASK_ID_RE = re.compile(r"• ID задачи: <code>([^<]+)</code>")
_PROVIDER_ID_RE = re.compile(r"• ID провайдера: <code>([^<]+)</code>")
_ACTIVITY_FRAMES = (
    "▰▱▱▱▱▱▱▱",
    "▱▰▱▱▱▱▱▱",
    "▱▱▰▱▱▱▱▱",
    "▱▱▱▰▱▱▱▱",
    "▱▱▱▱▰▱▱▱",
    "▱▱▱▱▱▰▱▱",
    "▱▱▱▱▱▱▰▱",
    "▱▱▱▱▱▱▱▰",
    "▱▱▱▱▱▱▰▱",
    "▱▱▱▱▱▰▱▱",
    "▱▱▱▱▰▱▱▱",
    "▱▱▱▰▱▱▱▱",
    "▱▱▰▱▱▱▱▱",
    "▱▰▱▱▱▱▱▱",
)
_POLL_SECONDS = 12.0
_MAX_POLLS = 600  # 2 hours; watchdog owns long-running recovery after that.
_TRACKERS: dict[tuple[int, int], asyncio.Task[None]] = {}


def build_progress_line(status: str = "pending", *, frame: int = 0) -> str:
    normalized = str(status or "pending").strip().lower()
    if normalized == "completed":
        return "✅ <code>▰▰▰▰▰▰▰▰</code> Готово"
    if normalized == "failed":
        return "⚠️ <code>▰▰▰▰▰▰▰▰</code> Не удалось завершить"
    activity = _ACTIVITY_FRAMES[frame % len(_ACTIVITY_FRAMES)]
    label = "Нейросеть создаёт результат" if normalized == "processing" else "В работе"
    return f"⏳ <code>{activity}</code> {label}"


def ensure_progress_line(text: str) -> str:
    """Add the public progress line once to an existing start notification."""

    if not isinstance(text, str) or not text:
        return text
    if _PROGRESS_PREFIX in text:
        return text
    lines = text.splitlines()
    insert_at = 1 if lines else 0
    lines.insert(insert_at, build_progress_line())
    lines.insert(insert_at + 1, "")
    return "\n".join(lines)


def extract_task_ids(text: str) -> list[str]:
    values: list[str] = []
    for pattern in (_TASK_ID_RE, _PROVIDER_ID_RE):
        for match in pattern.finditer(str(text or "")):
            value = html.unescape(match.group(1)).strip()
            if value and value not in values:
                values.append(value)
    return values


def _replace_progress_line(text: str, line: str) -> str:
    if _PROGRESS_LINE_RE.search(text):
        return _PROGRESS_LINE_RE.sub(line, text, count=1)
    return ensure_progress_line(text).replace(build_progress_line(), line, 1)


def _terminal_text(text: str, status: str) -> str:
    normalized = str(status or "").strip().lower()
    updated = _replace_progress_line(text, build_progress_line(normalized))
    if normalized == "completed":
        updated = updated.replace(
            "🚀 <b>Генерация запущена</b>",
            "✅ <b>Генерация готова</b>",
            1,
        )
        updated = updated.replace(
            "Обычно результат приходит в течение 1–3 минут.",
            "Результат готов.",
            1,
        )
        updated = updated.replace(
            "Я пришлю его сюда сразу после готовности.",
            "Он уже доступен в чате и истории генераций.",
            1,
        )
    elif normalized == "failed":
        updated = updated.replace(
            "🚀 <b>Генерация запущена</b>",
            "⚠️ <b>Генерация не завершилась</b>",
            1,
        )
        updated = updated.replace(
            "Обычно результат приходит в течение 1–3 минут.",
            "Задача завершилась с ошибкой.",
            1,
        )
        updated = updated.replace(
            "Я пришлю его сюда сразу после готовности.",
            "Можно повторить запуск — детали ошибки бот покажет отдельным сообщением.",
            1,
        )
    return updated


def _clean_task_ids(task_ids: Iterable[Any]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for raw in task_ids:
        value = str(raw or "").strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return tuple(cleaned)


async def _lookup_generation_status(
    telegram_id: int,
    task_ids: tuple[str, ...],
) -> str | None:
    if not task_ids:
        return None

    direct_placeholders = ",".join("?" for _ in task_ids)
    alias_clauses = " OR ".join("request_data LIKE ?" for _ in task_ids)
    sql = (
        "SELECT status FROM generation_tasks "
        "WHERE telegram_id = ? AND ("
        f"task_id IN ({direct_placeholders})"
    )
    if alias_clauses:
        sql += f" OR {alias_clauses}"
    sql += ") ORDER BY id DESC LIMIT 1"
    params: list[Any] = [telegram_id, *task_ids, *(f"%{task_id}%" for task_id in task_ids)]

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(sql, tuple(params))
        row = await cursor.fetchone()
    if not row:
        return None
    return str(row["status"] or "pending").strip().lower()


async def _safe_edit(bot: Any, chat_id: int, message_id: int, text: str) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
        )
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        logger.debug(
            "Generation progress edit rejected: chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            exc,
        )
    except TelegramForbiddenError:
        logger.debug("Generation progress stopped: chat is unavailable", exc_info=True)
    except Exception:
        logger.debug("Generation progress edit failed", exc_info=True)
    return False


async def _watch_progress(
    bot: Any,
    *,
    chat_id: int,
    message_id: int,
    telegram_id: int,
    task_ids: tuple[str, ...],
    base_text: str,
) -> None:
    missing_polls = 0
    try:
        for poll_index in range(_MAX_POLLS):
            status = await _lookup_generation_status(telegram_id, task_ids)
            if status in {"completed", "failed"}:
                await _safe_edit(
                    bot,
                    chat_id,
                    message_id,
                    _terminal_text(base_text, status),
                )
                return

            if status is None:
                missing_polls += 1
                if missing_polls >= 10:
                    logger.info(
                        "Generation progress tracker stopped without task row: telegram_id=%s task_ids=%s",
                        telegram_id,
                        task_ids,
                    )
                    return
            else:
                missing_polls = 0

            if poll_index > 0:
                progress_text = _replace_progress_line(
                    base_text,
                    build_progress_line(status or "pending", frame=poll_index),
                )
                if not await _safe_edit(bot, chat_id, message_id, progress_text):
                    return
            await asyncio.sleep(_POLL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Generation progress tracker crashed: telegram_id=%s task_ids=%s",
            telegram_id,
            task_ids,
        )
    finally:
        _TRACKERS.pop((chat_id, message_id), None)


def track_generation_progress(
    bot: Any,
    *,
    chat_id: int,
    message_id: int,
    telegram_id: int,
    task_ids: Iterable[Any],
    text: str,
) -> None:
    """Start one lightweight tracker for the already-sent start message."""

    normalized_ids = _clean_task_ids(task_ids)
    if not normalized_ids or not chat_id or not message_id or not telegram_id:
        return

    key = (int(chat_id), int(message_id))
    previous = _TRACKERS.pop(key, None)
    if previous and not previous.done():
        previous.cancel()

    task = asyncio.create_task(
        _watch_progress(
            bot,
            chat_id=int(chat_id),
            message_id=int(message_id),
            telegram_id=int(telegram_id),
            task_ids=normalized_ids,
            base_text=ensure_progress_line(text),
        ),
        name=f"generation-progress-{chat_id}-{message_id}",
    )
    _TRACKERS[key] = task
