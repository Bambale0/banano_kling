"""Provider-agnostic Telegram progress indicator for generation tasks.

Every generation is persisted in ``generation_tasks``.  This module uses that
single source of truth instead of inventing provider-specific percentages:
while a task is pending/processing it animates an indeterminate bar, then
switches the same Telegram message to a terminal completed/failed state.

A small durable notification ledger also lets a background worker cover flows
that do not have an explicit start notifier (for example a newly added video,
audio or character model) without duplicating messages from handlers that do.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta
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
_AUTO_NOTIFY_GRACE_SECONDS = 6
_AUTO_NOTIFY_LOOKBACK_MINUTES = 15
_AUTO_NOTIFY_SCAN_SECONDS = 3.0
_TRACKERS: dict[tuple[int, int], asyncio.Task[None]] = {}
_WORKER_TASK: asyncio.Task[None] | None = None
_SCHEMA_LOCK: asyncio.Lock | None = None
_SCHEMA_READY = False


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


def _schema_lock() -> asyncio.Lock:
    global _SCHEMA_LOCK
    if _SCHEMA_LOCK is None:
        _SCHEMA_LOCK = asyncio.Lock()
    return _SCHEMA_LOCK


async def ensure_generation_progress_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _schema_lock():
        if _SCHEMA_READY:
            return
        async with db_backend.connect(DATABASE_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_progress_notifications (
                    task_id TEXT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()
        _SCHEMA_READY = True


async def find_generation_progress_notification(
    task_ids: Iterable[Any],
) -> tuple[int, int] | None:
    normalized = _clean_task_ids(task_ids)
    if not normalized:
        return None
    await ensure_generation_progress_schema()
    placeholders = ",".join("?" for _ in normalized)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT chat_id, message_id
            FROM generation_progress_notifications
            WHERE task_id IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            normalized,
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return int(row["chat_id"]), int(row["message_id"])


async def remember_generation_progress_notification(
    task_ids: Iterable[Any],
    *,
    chat_id: int,
    message_id: int,
) -> None:
    normalized = _clean_task_ids(task_ids)
    if not normalized:
        return
    await ensure_generation_progress_schema()
    async with db_backend.connect(DATABASE_PATH) as db:
        for task_id in normalized:
            await db.execute(
                """
                INSERT INTO generation_progress_notifications(
                    task_id, chat_id, message_id, updated_at
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (task_id) DO UPDATE SET
                    chat_id = EXCLUDED.chat_id,
                    message_id = EXCLUDED.message_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (task_id, int(chat_id), int(message_id)),
            )
        await db.commit()


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
        await remember_generation_progress_notification(
            task_ids,
            chat_id=chat_id,
            message_id=message_id,
        )
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
    """Start one lightweight tracker for an already-sent progress message."""

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


def _generic_task_text(row: Any) -> str:
    model = html.escape(str(row["model"] or row["preset_id"] or "AI"))
    task_id = html.escape(str(row["task_id"] or ""))
    task_type = str(row["type"] or "generation").strip().lower()
    type_label = {
        "image": "Фото",
        "video": "Видео",
        "audio": "Аудио",
        "character": "Персонаж",
    }.get(task_type, "Генерация")
    return "\n".join(
        [
            "🚀 <b>Генерация запущена</b>",
            build_progress_line(),
            "",
            f"• Тип: <code>{type_label}</code>",
            f"• Модель: <code>{model}</code>",
            f"• ID задачи: <code>{task_id}</code>",
            "",
            "Обычно результат приходит в течение 1–3 минут.",
            "Я пришлю его сюда сразу после готовности.",
        ]
    )


async def _pending_generation_rows() -> list[Any]:
    await ensure_generation_progress_schema()
    now = datetime.utcnow()
    earliest = now - timedelta(minutes=_AUTO_NOTIFY_LOOKBACK_MINUTES)
    grace_cutoff = now - timedelta(seconds=_AUTO_NOTIFY_GRACE_SECONDS)
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, telegram_id, task_id, type, preset_id, model, status, created_at
            FROM generation_tasks
            WHERE status IN ('pending', 'processing')
              AND telegram_id IS NOT NULL
              AND created_at >= ?
              AND created_at <= ?
            ORDER BY id DESC
            LIMIT 50
            """,
            (earliest.isoformat(), grace_cutoff.isoformat()),
        )
        return list(await cursor.fetchall())


async def _cover_unnotified_generation(bot: Any, row: Any) -> None:
    task_id = str(row["task_id"] or "").strip()
    telegram_id = int(row["telegram_id"] or 0)
    if not task_id or not telegram_id:
        return

    existing = await find_generation_progress_notification([task_id])
    text = _generic_task_text(row)
    if existing:
        chat_id, message_id = existing
        if (chat_id, message_id) not in _TRACKERS:
            track_generation_progress(
                bot,
                chat_id=chat_id,
                message_id=message_id,
                telegram_id=telegram_id,
                task_ids=[task_id],
                text=text,
            )
        return

    try:
        sent = await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.debug(
            "Unable to auto-send generation progress: telegram_id=%s task_id=%s",
            telegram_id,
            task_id,
            exc_info=True,
        )
        return
    except Exception:
        logger.exception(
            "Generation progress auto-notifier failed: telegram_id=%s task_id=%s",
            telegram_id,
            task_id,
        )
        return

    await remember_generation_progress_notification(
        [task_id],
        chat_id=telegram_id,
        message_id=sent.message_id,
    )
    track_generation_progress(
        bot,
        chat_id=telegram_id,
        message_id=sent.message_id,
        telegram_id=telegram_id,
        task_ids=[task_id],
        text=text,
    )


async def generation_progress_worker(bot: Any) -> None:
    await ensure_generation_progress_schema()
    while True:
        try:
            rows = await _pending_generation_rows()
            for row in rows:
                await _cover_unnotified_generation(bot, row)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Generation progress worker iteration failed")
        await asyncio.sleep(_AUTO_NOTIFY_SCAN_SECONDS)


def ensure_generation_progress_worker(bot: Any) -> asyncio.Task[None]:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(
            generation_progress_worker(bot),
            name="generation-progress-worker",
        )
    return _WORKER_TASK
