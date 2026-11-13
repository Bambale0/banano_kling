"""Recover uncertain Wan acknowledgements from canonical provider lineage."""
from __future__ import annotations

import json
import logging
import secrets
from urllib.parse import parse_qs, urlparse

from bot import database
from bot import db as db_backend
from bot.services.wan3_models import wan3_model_spec
from bot.services.wan3_neironych_runtime import _SAFE_REQUEST_ID, NEIRONYCH_TASK_PREFIX
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
    try:
        expected_model = wan3_model_spec(row["provider_model"]).provider_model
    except (KeyError, ValueError):
        return False
    if canonical.get("source") == "neironych":
        # The canonical native GET is authenticated for this partner and
        # returns a client ID that we set *before* the paid POST.
        return bool(
            str(canonical.get("taskId") or "").startswith("neironych:")
            and canonical.get("client_request_id") == row["internal_task_id"]
            and canonical.get("model", expected_model) == expected_model
        )
    if canonical.get("model") != expected_model:
        return False
    params = _object(canonical.get("param"))
    if params.get("model") != expected_model:
        return False
    callback = params.get("callBackUrl")
    if not isinstance(callback, str):
        return False
    callback_query = parse_qs(urlparse(callback).query)
    if callback_query.get("intent") != [row["internal_task_id"]]:
        return False
    supplied_nonce = callback_query.get("nonce", [""])[0]
    if supplied_nonce:
        if not secrets.compare_digest(str(row["callback_nonce"]), supplied_nonce):
            return False
    else:
        from bot.services.wan3_prime_callback_auth import signed_callbacks_enabled

        if not signed_callbacks_enabled():
            return False
    expected = _object(row["request_summary"]).get("prepared_input")
    actual = _object(params.get("input"))
    # JSON serialization distinguishes true/1 and false/0; plain Python dict
    # equality does not. Additional undocumented input also fails closed.
    return bool(isinstance(expected, dict) and expected and
                json.dumps(expected, sort_keys=True, ensure_ascii=False) == json.dumps(actual, sort_keys=True, ensure_ascii=False))


_NATIVE_BY_KIE = {
    "wan/3-0-video": "wan-3",
    "wan/3-0-video-prime": "wan-3-prime",
}


def verified_native_candidate(row, generation: dict | None) -> str | None:
    """Require one verified native generation owned by the same partner.

    The upstream GET /api/v1/generations/by-client-request-id/... uses the
    same bearer token as POST and scopes the result to that partner.
    """
    expected_model = _NATIVE_BY_KIE.get(row["provider_model"])
    internal_id = str(row["internal_task_id"])
    if not expected_model or not isinstance(generation, dict):
        return None
    if (generation.get("client_request_id") != internal_id
            or generation.get("idempotency_key") != internal_id
            or generation.get("model_slug") != expected_model):
        return None
    request_id = generation.get("id")
    if not isinstance(request_id, str) or not _SAFE_REQUEST_ID.fullmatch(request_id):
        return None
    return NEIRONYCH_TASK_PREFIX + request_id


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
            candidate_id = row["candidate_id"]
            upstream_verified = True
            if str(candidate_id).startswith("neironych:"):
                upstream_verified = False
                lookup = getattr(lifecycle.transport, "lookup_native_submission", None)
                if lookup is not None:
                    record = await lookup(task_id)
                    upstream_verified = verified_native_candidate(row, record) == candidate_id
            if upstream_verified:
                canonical = await lifecycle.transport.get_task_status(candidate_id)
                upstream_verified = bool(
                    isinstance(canonical, dict)
                    and canonical.get("taskId") == candidate_id
                    and matches_submission(row, canonical)
                )
            if upstream_verified:
                await lifecycle._bind_provider_id(task_id, candidate_id)
                logger.info("Wan3 unknown recovered: task_id=%s provider_task_id=%s", task_id, candidate_id)
                recovered += 1
            else:
                logger.warning("Wan3 lineage unconfirmed: task_id=%s provider_task_id=%s", task_id, candidate_id)
        except Exception as exc:  # noqa: BLE001 - provider outage must leave the durable uncertain operation intact
            logger.warning("Wan3 recovery deferred: task_id=%s error_type=%s", task_id, type(exc).__name__)
        finally:
            await lifecycle._mark_checked(task_id, retry_seconds=60)
    return recovered


def native_recovery_route_filter(*, postgres: bool) -> str:
    """Filter before LIMIT so legacy unknown jobs cannot starve native recovery."""
    if postgres:
        return "(CAST(task.request_data AS JSONB) ->> 'provider_submission_route') = 'neironych'"
    return (
        "CASE WHEN json_valid(task.request_data) "
        "THEN json_extract(task.request_data, '$.provider_submission_route') "
        "ELSE NULL END = 'neironych'"
    )


async def recover_unknown_native_submissions(lifecycle, *, limit: int = 20) -> int:
    """Find accepted native requests after a lost acknowledgement or crash.

    Never replay a paid POST. GET by stable client ID and then authenticated
    native GET must agree before the existing lifecycle binds the provider ID.
    """
    lookup = getattr(lifecycle.transport, "lookup_native_submission", None)
    if lookup is None:
        return 0
    route_filter = native_recovery_route_filter(
        postgres=bool(getattr(db_backend, "is_postgres", lambda: False)()),
    )
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        rows = await (await db.execute(f"""
            SELECT intent.*, task.request_data AS task_request_data
            FROM wan3_prime_intents AS intent
            JOIN generation_tasks AS task ON task.task_id = intent.internal_task_id
            WHERE intent.provider_task_id IS NULL AND intent.settled = 0
              AND intent.status = 'unknown'
              AND ({route_filter})
              AND (intent.next_attempt_at IS NULL OR intent.next_attempt_at <= CURRENT_TIMESTAMP)
              AND (intent.lease_until IS NULL OR intent.lease_until <= CURRENT_TIMESTAMP)
            ORDER BY intent.updated_at, intent.id LIMIT ?
        """, (limit,))).fetchall()
    recovered = 0
    for row in rows:
        task_id = row["internal_task_id"]
        metadata = _object(row["task_request_data"])
        if metadata.get("provider_submission_route") != "neironych":
            continue
        if not await lifecycle._claim_reconcile_lease(task_id, respect_backoff=True):
            continue
        try:
            record = await lookup(task_id)
            candidate_id = verified_native_candidate(row, record)
            if candidate_id:
                canonical = await lifecycle.transport.get_task_status(candidate_id)
                if (isinstance(canonical, dict)
                        and canonical.get("taskId") == candidate_id
                        and matches_submission(row, canonical)):
                    await lifecycle._bind_provider_id(task_id, candidate_id)
                    recovered += 1
                    logger.info(
                        "Wan3 native lost acknowledgement recovered: task_id=%s provider_task_id=%s",
                        task_id, candidate_id,
                    )
            # Upstream 404 or missing lineage is uncertain. Keep funds reserved
            # until confirmed/settled; a second paid POST would be unsafe.
        except Exception as exc:  # noqa: BLE001 - provider outage must not lose recovery candidate
            logger.warning("Wan3 native lookup deferred: task_id=%s error_type=%s",
                           task_id, type(exc).__name__)
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
            WHERE (status IN ('unknown', 'result_attention') AND settled = 0) OR delivery_status = 'uncertain'
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
