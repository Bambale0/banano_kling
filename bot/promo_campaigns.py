"""Persistent Telegram promo drafts using the existing notification queue.

Only newly composed promos use this contract. Historical queued campaigns and
non-promo system notifications keep their existing behavior.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from bot import db as db_backend
from bot.config import config
from bot.internal_admin_notification_schema import (
    ensure_internal_admin_notification_schema,
)
from bot.promo_message import build_message_snapshot, normalize_message


class PromoError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _validation_error(exc: ValueError) -> PromoError:
    detail = str(exc)
    if "buttons" in detail or "button." in detail or "button positions" in detail:
        text = "Для каждой из двух кнопок нужны подпись от 1 до 64 символов и выбранный тренд"
    elif "HTML" in detail or "html" in detail or "entit" in detail:
        text = "Некорректное HTML-форматирование. Проверьте теги или выберите обычный текст"
    elif "limit" in detail or "text exceeds" in detail:
        text = "Текст слишком длинный: максимум 1024 символа с одним файлом и 4096 для текста или альбома"
    elif "media" in detail:
        text = "Прикрепите не более 10 фото или видео через Telegram"
    elif "text is required" in detail or "visible text" in detail:
        text = "Добавьте текст промо. Для альбома он будет отправлен отдельным сообщением с кнопками"
    else:
        text = "Не удалось проверить промо. Проверьте текст, медиа и выбранные тренды"
    return PromoError("INVALID_PROMO", text)


def _admin(admin_id: int) -> None:
    if not config.is_admin(admin_id):
        raise PromoError("FORBIDDEN", "Нет доступа")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value


def _json_slot() -> str:
    return "CAST(? AS JSONB)" if db_backend.is_postgres() else "?"


@asynccontextmanager
async def _transaction():
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        if not db_backend.is_postgres():
            await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


def _promo_columns() -> str:
    # The legacy column stores the database's local wall clock without a zone.
    # Attach the same database session zone before returning an ISO timestamp.
    if db_backend.is_postgres():
        return "*, tested_at AT TIME ZONE current_setting('TimeZone') AS tested_at_aware"
    return "*"


async def _record_revision(
    conn: Any, campaign_id: int, revision: int, admin_id: int, payload_hash: str,
) -> None:
    """Append normalized-payload attribution inside the campaign transaction."""
    await conn.execute(
        """INSERT INTO notification_promo_revisions
           (campaign_id, revision, admin_telegram_id, payload_hash)
           VALUES (?, ?, ?, ?)""",
        (campaign_id, revision, admin_id, payload_hash),
    )


async def _fetch(conn: Any, campaign_id: int, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock and db_backend.is_postgres() else ""
    cur = await conn.execute(
        f"SELECT {_promo_columns()} FROM notification_campaigns WHERE id = ? AND promo_version = 2" + suffix,
        (campaign_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise PromoError("NOT_FOUND", "Промо-рассылка не найдена")
    return dict(row)


def _editable(row: dict[str, Any], revision: int) -> None:
    if row["status"] != "draft":
        raise PromoError("PROMO_ALREADY_STARTED", "Эта рассылка уже запущена. Создайте копию")
    if int(row["revision"]) != int(revision):
        raise PromoError("STALE_REVISION", "Рассылка изменена. Откройте актуальную версию")


async def _check_trends(conn: Any, message: dict[str, Any]) -> dict[str, str]:
    titles = {}
    for button in sorted(message.get("buttons", []), key=lambda item: item["trend_id"]):
        cur = await conn.execute(
            "SELECT id, title, tags, status, is_public FROM user_prompts WHERE id = ?"
            + (" FOR SHARE" if db_backend.is_postgres() else ""),
            (button["trend_id"],),
        )
        row = await cur.fetchone()
        tags = _decode(row["tags"], []) if row else []
        if (
            not row or row["status"] != "approved" or not row["is_public"]
            or "trend" not in [str(tag).lower().strip() for tag in tags]
        ):
            raise PromoError(
                "TREND_NOT_AVAILABLE",
                f"Тренд #{button['trend_id']} больше недоступен. Выберите другой тренд",
            )
        titles[str(row["id"])] = str(row["title"])
    return titles


async def search_trends(query: str = "", page: int = 0, size: int = 6) -> dict[str, Any]:
    """Server-side, bounded search over the existing public approved trend model."""
    query = str(query).strip()[:160]
    page = max(0, min(int(page), 100000))
    size = max(1, min(int(size), 20))
    # tags is the existing serialized JSON TEXT field. Quoted matching excludes
    # trend-video/private-reference tags which are not the public trend marker.
    sql = """SELECT id, title, preview_url FROM user_prompts
             WHERE status = 'approved' AND is_public = 1 AND tags LIKE ?"""
    args: list[Any] = ['%"trend"%']
    if query:
        sql += " AND (LOWER(title) LIKE ? ESCAPE '\\' OR id = ?)"
        escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.extend(["%" + escaped + "%", int(query) if query.isdecimal() and len(query) < 19 else -1])
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([size + 1, page * size])
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(sql, tuple(args))
        rows = await cur.fetchall()
    return {"items": [dict(row) for row in rows[:size]], "page": page, "has_more": len(rows) > size}


async def _audience(conn: Any) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE COALESCE(is_banned, 0) = 0 AND telegram_id IS NOT NULL"
    )
    row = await cur.fetchone()
    return int(row["n"])


def _view(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if "tested_at_aware" in result:
        result["tested_at"] = result.pop("tested_at_aware")
    for key, default in (("message", {}), ("message_snapshot", None), ("test_summary", {})):
        result[key] = _decode(result.get(key), default)
    for key in ("tested_at", "created_at", "updated_at", "started_at", "completed_at"):
        value = result.get(key)
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    result["ready"] = bool(
        result["status"] == "draft"
        and result.get("content_hash")
        and result.get("tested_content_hash") == result.get("content_hash")
        and int(result["test_summary"].get("sent", 0)) > 0
    )
    return result


async def create_promo(admin_id: int, idempotency_key: str | None = None) -> dict[str, Any]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    message = normalize_message(
        {"schema_version": 2, "text": "", "parse_mode": "HTML", "media": [], "buttons": []}, allow_empty=True
    )
    digest = hashlib.sha256(_json(message).encode()).hexdigest()
    key = f"promo-create:{admin_id}:{idempotency_key or uuid.uuid4().hex}"
    slot = _json_slot()
    async with _transaction() as conn:
        cur = await conn.execute(
            f"""INSERT INTO notification_campaigns
                (name, channel, status, segment, message, created_by, reason,
                 idempotency_key, promo_version, revision, content_hash)
                VALUES (?, 'telegram', 'draft', {slot}, {slot}, ?, ?, ?, 2, 1, ?)
                ON CONFLICT (idempotency_key) DO NOTHING RETURNING id""",
            ("Промо-рассылка", _json({"type": "all"}), _json(message), str(admin_id),
             "Telegram admin promo", key, digest),
        )
        row = await cur.fetchone()
        if row:
            campaign_id = int(row["id"])
            await _record_revision(conn, campaign_id, 1, admin_id, digest)
        else:
            cur = await conn.execute(
                "SELECT id FROM notification_campaigns WHERE idempotency_key = ?", (key,)
            )
            campaign_id = int((await cur.fetchone())["id"])
    return await get_promo(campaign_id, admin_id)


async def get_promo(campaign_id: int, admin_id: int) -> dict[str, Any]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        row = await _fetch(conn, campaign_id)
        result = _view(row)
        result["audience_count"] = await _audience(conn) if row["status"] == "draft" else row["audience_count"]
        result["trend_titles"] = {}
        for button in result["message"].get("buttons", []):
            cur = await conn.execute("SELECT title FROM user_prompts WHERE id = ?", (button["trend_id"],))
            trend = await cur.fetchone()
            result["trend_titles"][str(button["trend_id"])] = str(trend["title"]) if trend else "Недоступен"
        cur = await conn.execute(
            """SELECT last_error, COUNT(*) AS n FROM notification_deliveries
               WHERE campaign_id = ? AND status IN ('failed','blocked','uncertain')
               GROUP BY last_error""", (campaign_id,),
        )
        result["error_groups"] = [
            {"code": str(item["last_error"] or "unknown"), "count": int(item["n"])}
            for item in await cur.fetchall()
        ]
    return result


async def list_promos(admin_id: int, limit: int = 8, before: int | None = None) -> list[dict[str, Any]]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    sql = f"SELECT {_promo_columns()} FROM notification_campaigns WHERE promo_version = 2"
    args: list[Any] = []
    if before:
        sql += " AND id < ?"
        args.append(int(before))
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(max(int(limit), 1), 21))
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(sql, tuple(args))
        return [_view(dict(row)) for row in await cur.fetchall()]


async def save_promo(
    campaign_id: int, admin_id: int, message: dict[str, Any], expected_revision: int,
) -> dict[str, Any]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    try:
        normalized = normalize_message(message, allow_empty=True)
    except ValueError as exc:
        raise _validation_error(exc) from exc
    digest = hashlib.sha256(_json(normalized).encode()).hexdigest()
    async with _transaction() as conn:
        row = await _fetch(conn, campaign_id, lock=True)
        _editable(row, expected_revision)
        await _check_trends(conn, normalized)
        if normalized != _decode(row["message"], {}):
            await conn.execute(
                f"""UPDATE notification_campaigns SET message = {_json_slot()},
                    revision = revision + 1, content_hash = ?, tested_content_hash = NULL,
                    tested_at = NULL, tested_by = NULL, test_run_key = NULL,
                    test_summary = NULL, message_snapshot = NULL,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (_json(normalized), digest, campaign_id),
            )
            await _record_revision(conn, campaign_id, int(row["revision"]) + 1, admin_id, digest)
            await conn.execute(
                """UPDATE notification_test_sends SET status = 'cancelled'
                   WHERE campaign_id = ? AND status IN ('queued', 'failed') AND test_run_key IS NOT NULL""",
                (campaign_id,),
            )
    return await get_promo(campaign_id, admin_id)


async def _bot_username(bot: Any) -> str:
    me = await asyncio.wait_for(bot.get_me(), timeout=10)
    username = str(me.username or "").strip()
    if not username:
        raise PromoError("BOT_USERNAME_MISSING", "Не удалось определить ссылку бота")
    return username


async def test_promo(
    campaign_id: int, admin_id: int, bot: Any, expected_revision: int,
    idempotency_key: str,
) -> dict[str, Any]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    admins = sorted(set(config.admin_ids))
    if not admins:
        raise PromoError("NO_ADMINS", "Нет администраторов для тестовой отправки")
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 120:
        raise PromoError("INVALID_KEY", "Некорректный ключ тестовой отправки")
    username = await _bot_username(bot)
    run_key = f"promo:{campaign_id}:{admin_id}:{idempotency_key}"
    slot = _json_slot()
    async with _transaction() as conn:
        row = await _fetch(conn, campaign_id, lock=True)
        _editable(row, expected_revision)
        message = _decode(row["message"], {})
        await _check_trends(conn, message)
        try:
            snapshot = build_message_snapshot(message, username)
        except ValueError as exc:
            raise _validation_error(exc) from exc
        digest = snapshot["content_hash"]
        cur = await conn.execute(
            """SELECT COUNT(*) AS n FROM notification_test_sends
               WHERE campaign_id = ? AND test_run_key = ?
                 AND (status IN ('queued','sending') OR (status = 'failed' AND attempts < 5))""", (campaign_id, row.get("test_run_key")),
        )
        pending = int((await cur.fetchone())["n"])
        if row.get("test_run_key") == run_key or pending:
            return _view(row)
        cur = await conn.execute(
            "SELECT content_hash FROM notification_test_sends WHERE test_run_key = ? LIMIT 1", (run_key,)
        )
        previous = await cur.fetchone()
        if previous:
            raise PromoError("TEST_KEY_USED", "Этот тест уже выполнен. Откройте промо и повторите тест")
        summary = {"status": "queued", "sent": 0, "failed": 0, "uncertain": 0,
                   "pending": len(admins), "errors": [], "content_hash": digest}
        await conn.execute(
            f"""UPDATE notification_campaigns SET content_hash = ?, tested_content_hash = NULL,
                tested_at = NULL, tested_by = NULL, test_run_key = ?, test_summary = {slot},
                message_snapshot = {slot}, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (digest, run_key, _json(summary), _json(snapshot), campaign_id),
        )
        for telegram_id in admins:
            await conn.execute(
                f"""INSERT INTO notification_test_sends
                    (campaign_id, telegram_id, status, requested_by, request_id, idempotency_key,
                     content_hash, test_run_key, message_snapshot)
                    VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, {slot})
                    ON CONFLICT (idempotency_key) DO NOTHING""",
                (campaign_id, telegram_id, str(admin_id), run_key, f"{run_key}:{telegram_id}",
                 digest, run_key, _json(snapshot)),
            )
    from bot.notification_service import ensure_notification_campaign_worker
    ensure_notification_campaign_worker(bot)
    return await get_promo(campaign_id, admin_id)


async def refresh_test_state(campaign_id: int, content_hash: str) -> None:
    """Worker callback; only receipts from the current version/run can unlock send."""
    async with _transaction() as conn:
        row = await _fetch(conn, campaign_id, lock=True)
        if row["status"] not in {"draft", "running", "completed"} or (content_hash is not None and row.get("content_hash") != content_hash):
            return
        content_hash = row.get("content_hash")
        cur = await conn.execute(
            """SELECT telegram_id, status, attempts, error, requested_by
               FROM notification_test_sends WHERE campaign_id = ? AND test_run_key = ?
               AND content_hash = ?""",
            (campaign_id, row.get("test_run_key"), content_hash),
        )
        receipts = [dict(item) for item in await cur.fetchall()]
        current_admins = set(config.admin_ids)
        sent = sum(item["status"] == "sent" and int(item["telegram_id"]) in current_admins for item in receipts)
        pending = sum(item["status"] in {"queued", "sending"} or
                      (item["status"] == "failed" and int(item["attempts"]) < 5) for item in receipts)
        errors = [
            {"telegram_id": int(item["telegram_id"]), "code": str(item["error"] or item["status"])}
            for item in receipts if item["status"] in {"blocked", "uncertain"}
            or (item["status"] == "failed" and int(item["attempts"]) >= 5)
        ]
        summary = {
            "status": "sending" if pending else "completed", "sent": sent,
            "failed": len(errors), "uncertain": sum(item["status"] == "uncertain" for item in receipts),
            "pending": pending, "errors": errors, "content_hash": content_hash,
        }
        if row["status"] != "draft":
            await conn.execute(
                f"UPDATE notification_campaigns SET test_summary = {_json_slot()} WHERE id = ?",
                (_json(summary), campaign_id),
            )
            return
        await conn.execute(
            f"""UPDATE notification_campaigns SET test_summary = {_json_slot()},
                tested_content_hash = ?, tested_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE NULL END,
                tested_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (_json(summary), content_hash if sent else None, sent,
             receipts[0]["requested_by"] if receipts and sent else None, campaign_id),
        )


async def start_promo(
    campaign_id: int, admin_id: int, bot: Any, expected_revision: int,
    expected_hash: str, expected_audience: int,
) -> dict[str, Any]:
    _admin(admin_id)
    await ensure_internal_admin_notification_schema()
    username = await _bot_username(bot)
    async with _transaction() as conn:
        row = await _fetch(conn, campaign_id, lock=True)
        if row["status"] in {"running", "completed"} and (
            row.get("content_hash") == expected_hash and int(row["revision"]) == int(expected_revision)
        ):
            return _view(row)
        _editable(row, expected_revision)
        message = _decode(row["message"], {})
        await _check_trends(conn, message)
        try:
            snapshot = build_message_snapshot(message, username)
        except ValueError as exc:
            raise _validation_error(exc) from exc
        digest = snapshot["content_hash"]
        if (
            not expected_hash or digest != expected_hash
            or digest != row.get("tested_content_hash")
            or digest != row.get("content_hash")
            or snapshot != _decode(row.get("message_snapshot"), {})
        ):
            raise PromoError("PROMO_NOT_TESTED", "Рассылка изменена после теста. Запустите «Тест на админах» повторно")
        cur = await conn.execute(
            """SELECT telegram_id FROM notification_test_sends
               WHERE campaign_id = ? AND test_run_key = ? AND content_hash = ? AND status = 'sent'""",
            (campaign_id, row.get("test_run_key"), digest),
        )
        if not any(config.is_admin(int(item["telegram_id"])) for item in await cur.fetchall()):
            raise PromoError("PROMO_NOT_TESTED", "Тест не доставлен ни одному активному администратору")
        await conn.execute(
            """INSERT INTO notification_deliveries (campaign_id, user_id, telegram_id)
               SELECT ?, id, telegram_id FROM users WHERE COALESCE(is_banned, 0) = 0
               AND telegram_id IS NOT NULL ON CONFLICT (campaign_id, telegram_id) DO NOTHING""",
            (campaign_id,),
        )
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM notification_deliveries WHERE campaign_id = ?", (campaign_id,)
        )
        total = int((await cur.fetchone())["n"])
        if total != int(expected_audience):
            raise PromoError("AUDIENCE_CHANGED", "Число получателей изменилось. Подтвердите отправку ещё раз")
        await conn.execute(
            """UPDATE notification_campaigns SET status = ?, audience_count = ?, queued_count = ?,
               started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP,
               completed_at = CASE WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE NULL END
               WHERE id = ? AND status = 'draft' AND revision = ?""",
            ("running" if total else "completed", total, total, total, campaign_id, expected_revision),
        )
        # Remaining admin deliveries may still finish, but they must not unlock or mutate this snapshot.
    from bot.notification_service import ensure_notification_campaign_worker
    ensure_notification_campaign_worker(bot)
    return await get_promo(campaign_id, admin_id)


async def duplicate_promo(campaign_id: int, admin_id: int) -> dict[str, Any]:
    original = await get_promo(campaign_id, admin_id)
    duplicate = await create_promo(admin_id)
    return await save_promo(duplicate["id"], admin_id, original["message"], duplicate["revision"])


async def cancel_promo(campaign_id: int, admin_id: int, expected_revision: int) -> dict[str, Any]:
    _admin(admin_id)
    async with _transaction() as conn:
        row = await _fetch(conn, campaign_id, lock=True)
        _editable(row, expected_revision)
        await conn.execute(
            "UPDATE notification_campaigns SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (campaign_id,),
        )
        await conn.execute(
            "UPDATE notification_test_sends SET status = 'cancelled' WHERE campaign_id = ? AND status IN ('queued','failed')",
            (campaign_id,),
        )
    return await get_promo(campaign_id, admin_id)
