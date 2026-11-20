"""Account-scoped web generation history.

Separate from legacy Telegram tasks. No fabricated Telegram IDs or silent
cross-platform ownership. Actual provider task creation uses this record
shape only after independent billing and queue lifecycle are verified.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from aiohttp import web

from bot import db as db_backend
from bot.shared_accounts.schema import ensure_schema

_TASK_ID = re.compile(r"^web_[a-f0-9]{32}$")
_CURSOR = re.compile(r"^([0-9]{1,16}):(web_[a-f0-9]{32})$")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS web_generation_tasks (
        task_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        media_type TEXT NOT NULL CHECK(media_type IN ('image','video')),
        model TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')),
        result_url TEXT,
        provider_task_id TEXT UNIQUE,
        created_at_epoch BIGINT NOT NULL,
        updated_at_epoch BIGINT NOT NULL,
        request_key TEXT,
        request_hash TEXT,
        request_json TEXT,
        cost TEXT,
        reservation_key TEXT,
        phase TEXT NOT NULL DEFAULT 'queued',
        lease_until_epoch BIGINT NOT NULL DEFAULT 0,
        deadline_epoch BIGINT NOT NULL DEFAULT 0,
        asset_key TEXT,
        error_code TEXT,
        attempt_count BIGINT NOT NULL DEFAULT 0)""",
    """CREATE INDEX IF NOT EXISTS web_generation_tasks_account_created
       ON web_generation_tasks(account_id,created_at_epoch DESC,task_id DESC)""",
    """CREATE INDEX IF NOT EXISTS web_generation_tasks_queue
       ON web_generation_tasks(status,phase,lease_until_epoch)""",
    """CREATE TABLE IF NOT EXISTS web_generation_references (
        reference_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES shared_accounts(id),
        content_sha256 TEXT NOT NULL,
        url TEXT NOT NULL,
        media_type TEXT NOT NULL,
        created_at_epoch BIGINT NOT NULL,
        UNIQUE(account_id,content_sha256))""",
    """CREATE INDEX IF NOT EXISTS web_generation_references_owner
       ON web_generation_references(account_id,created_at_epoch DESC)""",
)
_ADDITIVE_FIELDS = {
    "request_key": "TEXT",
    "request_hash": "TEXT",
    "request_json": "TEXT",
    "cost": "TEXT",
    "reservation_key": "TEXT",
    "phase": "TEXT NOT NULL DEFAULT 'queued'",
    "lease_until_epoch": "BIGINT NOT NULL DEFAULT 0",
    "deadline_epoch": "BIGINT NOT NULL DEFAULT 0",
    "asset_key": "TEXT",
    "error_code": "TEXT",
    "attempt_count": "BIGINT NOT NULL DEFAULT 0",
}



async def ensure_web_tasks_schema() -> None:
    async with db_backend.connect() as db:
        await ensure_schema(db)
        if db_backend.is_postgres():
            await db.execute("SELECT pg_advisory_xact_lock(?)", (80420161122,))
        else:
            await db.execute("BEGIN IMMEDIATE")
        try:
            ddl = getattr(db, "execute_native_ddl", db.execute)
            await ddl(_SCHEMA[0])
            if db_backend.is_postgres():
                columns = await (await db.execute(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_name='web_generation_tasks'"""
                )).fetchall()
            else:
                columns = await (await db.execute("PRAGMA table_info(web_generation_tasks)")).fetchall()
            found = {row[0] if db_backend.is_postgres() else row[1] for row in columns}
            for field, definition in _ADDITIVE_FIELDS.items():
                if field not in found:
                    await ddl(f"ALTER TABLE web_generation_tasks ADD COLUMN {field} {definition}")
            for statement in _SCHEMA[1:]:
                await ddl(statement)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def _public_task(row) -> dict:
    media = str(row[4] or "")
    if media:
        parsed = urlsplit(media)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or len(media) > 4096):
            media = ""
    return {
        "task_id": str(row[0]),
        "type": str(row[1]),
        "model": str(row[2]),
        "status": str(row[3]),
        "result_url": media or None,
        "created_at_epoch": int(row[5]),
        "updated_at_epoch": int(row[6]),
        "phase": str(row[7]) if len(row) > 7 else "",
        "cost": str(row[8]) if len(row) > 8 and row[8] else None,
        "error_code": str(row[9]) if len(row) > 9 and row[9] else None,
    }


async def task_history(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    account_id = await _session_account(request)
    if not account_id:
        return _json({"ok": False, "error": "session_required"}, 401)
    before = str(request.query.get("cursor") or "")
    match = _CURSOR.fullmatch(before) if before else None
    if before and not match:
        return _json({"ok": False, "error": "Invalid cursor"}, 400)
    await ensure_web_tasks_schema()
    sql = """SELECT task_id,media_type,model,status,result_url,created_at_epoch,updated_at_epoch,
                    phase,cost,error_code
             FROM web_generation_tasks WHERE account_id IN (
                 WITH RECURSIVE owned(id) AS (
                     SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                     JOIN owned o ON a.merged_into=o.id WHERE a.status='merged'
                 ) SELECT id FROM owned)"""
    params: tuple = (account_id,)
    if match:
        epoch, task_id = int(match.group(1)), match.group(2)
        sql += " AND (created_at_epoch < ? OR (created_at_epoch = ? AND task_id < ?))"
        params += (epoch, epoch, task_id)
    sql += " ORDER BY created_at_epoch DESC,task_id DESC LIMIT 21"
    async with db_backend.connect() as db:
        rows = await (await db.execute(sql, params)).fetchall()
    records = [_public_task(row) for row in rows[:20]]
    next_cursor = None
    if len(rows) > 20:
        last = rows[19]
        next_cursor = f"{int(last[5])}:{last[0]!s}"
    return _json({"ok": True, "recent_tasks": records, "next_cursor": next_cursor})


async def task_detail(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    account_id = await _session_account(request)
    if not account_id:
        return _json({"ok": False, "error": "session_required"}, 401)
    task_id = str(request.match_info.get("task_id") or "")
    if not _TASK_ID.fullmatch(task_id):
        return _json({"ok": False, "error": "Task not found"}, 404)
    await ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        row = await (await db.execute(
            """SELECT task_id,media_type,model,status,result_url,created_at_epoch,updated_at_epoch,
                      phase,cost,error_code
               FROM web_generation_tasks WHERE task_id=? AND account_id IN (
                    WITH RECURSIVE owned(id) AS (
                        SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                        JOIN owned o ON a.merged_into=o.id WHERE a.status='merged'
                    ) SELECT id FROM owned)""",
            (task_id, account_id),
        )).fetchone()
    if not row:
        return _json({"ok": False, "error": "Task not found"}, 404)
    return _json({"ok": True, "task": _public_task(row)})


def setup_web_task_routes(app: web.Application, root: str) -> None:
    app.router.add_get(root + "/history", task_history)
    app.router.add_get(root + "/task/{task_id}", task_detail)
