"""Recover uncertain Wan acknowledgements from canonical provider lineage."""
from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from bot import database
from bot import db as db_backend
from bot.services.wan3_prime_media import WAN3_PROVIDER_MODEL
from bot.services.wan3_prime_schema import execute_wan_ddl

logger = logging.getLogger(__name__)


async def init_recovery_schema() -> None:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await execute_wan_ddl(db, """CREATE TABLE IF NOT EXISTS wan3_prime_recovery_candidates (
            internal_task_id TEXT PRIMARY KEY, provider_task_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        await execute_wan_ddl(db, """CREATE TABLE IF NOT EXISTS wan3_prime_operator_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, internal_task_id TEXT NOT NULL,
            admin_telegram_id BIGINT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.commit()


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def matches_submission(row, canonical: dict) -> bool:
    """Provider-authenticated GET, not a callback body, is the source of truth."""
    if canonical.get("model") != WAN3_PROVIDER_MODEL:
        return False
    params = _object(canonical.get("param"))
    if params.get("model") != WAN3_PROVIDER_MODEL:
        return False
    callback = params.get("callBackUrl")
    if not isinstance(callback, str):
        return False
    callback_query = parse_qs(urlparse(callback).query)
    if callback_query.get("intent") != [row["internal_task_id"]]:
        return False
    supplied_nonce = callback_query.get("nonce", [""])[0]
    if not secrets.compare_digest(str(row["callback_nonce"]), supplied_nonce):
        return False
    expected = _object(row["request_summary"]).get("prepared_input")
    actual = _object(params.get("input"))
    # JSON serialization distinguishes true/1 and false/0; plain Python dict
    # equality does not. Additional undocumented input also fails closed.
    return bool(isinstance(expected, dict) and expected and
                json.dumps(expected, sort_keys=True, ensure_ascii=False) == json.dumps(actual, sort_keys=True, ensure_ascii=False))


async def remember_candidate(internal_task_id: str, provider_task_id: str) -> None:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        # Persist the first authenticated candidate; replays cannot overwrite it.
        await db.execute("INSERT INTO wan3_prime_recovery_candidates (internal_task_id, provider_task_id) "
                         "VALUES (?, ?) ON CONFLICT (internal_task_id) DO NOTHING", (internal_task_id, provider_task_id))
        await db.commit()


async def recover_candidates(lifecycle, *, limit: int = 20) -> int:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute("""
            SELECT intent.*, candidate.provider_task_id AS candidate_id
            FROM wan3_prime_intents intent
            JOIN wan3_prime_recovery_candidates candidate ON candidate.internal_task_id = intent.internal_task_id
            WHERE intent.provider_task_id IS NULL AND intent.settled = 0
              AND intent.status = 'unknown'
              AND (intent.next_attempt_at IS NULL OR intent.next_attempt_at <= CURRENT_TIMESTAMP)
              AND (intent.lease_until IS NULL OR intent.lease_until <= CURRENT_TIMESTAMP)
            ORDER BY intent.updated_at, intent.id LIMIT ?
        """, (limit,))).fetchall()
    recovered = 0
    for row in rows:
        task_id = row["internal_task_id"]
        if not await lifecycle._claim_reconcile_lease(task_id, respect_backoff=True):
            continue
        try:
            canonical = await lifecycle.transport.get_task_status(row["candidate_id"])
            if (isinstance(canonical, dict) and canonical.get("taskId") == row["candidate_id"]
                    and matches_submission(row, canonical)):
                await lifecycle._bind_provider_id(task_id, row["candidate_id"])
                logger.info("Wan3 unknown recovered: task_id=%s provider_task_id=%s", task_id, row["candidate_id"])
                recovered += 1
            else:
                logger.warning("Wan3 lineage unconfirmed: task_id=%s provider_task_id=%s", task_id, row["candidate_id"])
        except Exception as exc:  # noqa: BLE001 - provider outage must leave the durable uncertain operation intact
            logger.warning("Wan3 recovery deferred: task_id=%s error_type=%s", task_id, type(exc).__name__)
        finally:
            await lifecycle._mark_checked(task_id, retry_seconds=60)
    return recovered


async def unresolved_operations(*, limit: int = 30) -> list[dict]:
    """Called by authenticated operators; excludes prompts, media URLs and secrets."""
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute("""
            SELECT internal_task_id, provider_task_id, user_id, telegram_id, status,
                   reserve_credits, delivery_status, error_code, created_at
            FROM wan3_prime_intents
            WHERE (status = 'unknown' AND settled = 0) OR delivery_status = 'uncertain'
            ORDER BY created_at, id LIMIT ?
        """, (max(1, min(limit, 100)),))).fetchall()
    return [dict(row) for row in rows]


async def recover_expired_submissions() -> int:
    """Crashes during a running process need the same recovery as startup."""
    async with db_backend.connect(database.DATABASE_PATH) as db:
        changed = await db.execute("UPDATE wan3_prime_intents SET status = 'unknown', provider_state = 'unknown', "
            "error_code = 'submission_receipt_unknown', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'submitting' AND settled = 0 AND lease_until <= CURRENT_TIMESTAMP")
        await db.commit()
        return max(0, int(changed.rowcount))
