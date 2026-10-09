"""Versioned partner economics, separate from admin-managed generation prices.

Environment settings configure future transactions only. Historical ledger entries
and accepted generation/payment terms are never rewritten.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from math import isfinite

from bot import db as db_backend

logger = logging.getLogger(__name__)
LEGACY_LEVEL1_PERCENT = 30.0
LEGACY_LEVEL2_PERCENT = 7.0
LEGACY_REPEAT_REWARD_RUB = 10.0


def _number(name: str, default: float, *, maximum: float | None = None) -> float:
    value = float(os.getenv(name, str(default)))
    if not isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid {name}")
    return value


@dataclass(frozen=True)
class PartnerPolicy:
    level1_percent: float
    level2_percent: float
    repeat_reward_rub: float
    level1_overrides: dict[int, float]

    def first_level_percent(self, recipient_telegram_id: int | None) -> float:
        return self.level1_overrides.get(int(recipient_telegram_id or 0), self.level1_percent)


def get_partner_policy() -> PartnerPolicy:
    overrides = json.loads(os.getenv("PARTNER_LEVEL1_OVERRIDES_JSON", '{"1608435230":30}'))
    if not isinstance(overrides, dict):
        raise ValueError("PARTNER_LEVEL1_OVERRIDES_JSON must be an object")  # noqa: TRY004 - configuration validation
    parsed: dict[int, float] = {}
    for recipient, percent in overrides.items():
        value = float(percent)
        if int(recipient) <= 0 or not isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Invalid partner first-level override")
        parsed[int(recipient)] = value
    return PartnerPolicy(
        level1_percent=_number("PARTNER_LEVEL1_PERCENT", 40, maximum=100),
        level2_percent=_number("PARTNER_LEVEL2_PERCENT", 7, maximum=100),
        repeat_reward_rub=_number("PARTNER_REPEAT_REWARD_RUB", 5),
        level1_overrides=parsed,
    )


async def init_partner_policy_tables(db) -> None:
    """Additive SQLite/PostgreSQL schema. No historical claims are backfilled."""
    for statement in (
        """CREATE TABLE IF NOT EXISTS partner_payment_terms (
            order_id TEXT PRIMARY KEY,
            level1_percent REAL NOT NULL,
            level2_percent REAL NOT NULL,
            level1_overrides_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS referral_activation_bonuses (
            referred_id BIGINT PRIMARY KEY REFERENCES users(id),
            referrer_id BIGINT NOT NULL REFERENCES users(id),
            bonus_credits REAL NOT NULL,
            after_generation_id BIGINT NOT NULL DEFAULT 0,
            qualifying_generation_id BIGINT,
            granted_at TIMESTAMP,
            last_checked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (referred_id != referrer_id)
        )""",
    ):
        ddl = getattr(db, "execute_native_ddl", db.execute)
        await ddl(statement)


async def record_pending_invite_bonus(db, referrer_id: int, referred_id: int, bonus: float) -> None:
    """Called only in the transaction that creates a new referral attachment."""
    await db.execute(
        """INSERT INTO referral_activation_bonuses
           (referred_id, referrer_id, bonus_credits, after_generation_id)
           VALUES (?, ?, ?, (SELECT COALESCE(MAX(id), 0) FROM generation_tasks WHERE user_id = ?))
           ON CONFLICT(referred_id) DO NOTHING""",
        (referred_id, referrer_id, bonus, referred_id),
    )


def generation_partner_snapshot(request_data, *, accepted: bool = False, previous=None, invite_eligible: bool | None = None) -> dict:
    """Stamp trusted terms into the canonical task write, ignoring supplied policy keys."""
    def parse(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            loaded = json.loads(value or "{}")
            return loaded if isinstance(loaded, dict) else {}
        except (ValueError, TypeError):
            return {}

    result = parse(request_data)
    old = parse(previous)
    result["partner_policy_version"] = 2
    result["partner_repeat_reward_rub"] = (
        old["partner_repeat_reward_rub"] if old.get("partner_policy_version") == 2
        else LEGACY_REPEAT_REWARD_RUB if previous is not None
        else get_partner_policy().repeat_reward_rub
    )
    result["partner_invite_eligible"] = (
        bool(invite_eligible) if invite_eligible is not None
        else old.get("partner_invite_eligible", True)
    )
    result["partner_generation_accepted"] = bool(accepted)
    return result


def _qualifying_task_proof(task) -> bool:
    from bot.config import config

    if not task or not str(task.task_id or "").strip() or task.type not in {"image", "video", "motion_control", "audio", "character"}:
        return False
    if not isfinite(float(task.cost or 0)) or float(task.cost or 0) <= 0:
        return False
    if config.is_admin(int(task.telegram_id)) or task.action_type == "admin_replay":
        return False
    try:
        metadata = json.loads(task.request_data or "{}")
    except (ValueError, TypeError):
        return False
    return bool(
        isinstance(metadata, dict) and metadata.get("partner_policy_version") == 2
        and metadata.get("partner_invite_eligible") is True
        and (metadata.get("partner_generation_accepted") is True
             or (task.status == "completed" and task.result_url))
    )


async def _invite_ancestry_is_valid(db, referrer_id: int, referred_id: int) -> bool:
    """Fail closed on any cycle without rewriting historical referral links."""
    current = referrer_id
    seen = {referred_id}
    for _ in range(100):
        if current in seen:
            return False
        seen.add(current)
        cursor = await db.execute("SELECT referred_by FROM users WHERE id = ?", (current,))
        row = await cursor.fetchone()
        if not row:
            return False
        if not row["referred_by"]:
            return True
        current = int(row["referred_by"])
    return False


async def _credit_accepted_invite_bonus(task) -> bool:

    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """SELECT b.referrer_id, b.bonus_credits FROM referral_activation_bonuses b
               JOIN users invited ON invited.id = b.referred_id
               JOIN users inviter ON inviter.id = b.referrer_id
               WHERE b.referred_id = ? AND b.granted_at IS NULL
                 AND b.after_generation_id < ? AND invited.referred_by = b.referrer_id
                 AND b.referrer_id != b.referred_id
                 AND COALESCE(invited.is_banned, 0) = 0 AND COALESCE(inviter.is_banned, 0) = 0""",
            (task.user_id, task.id),
        )
        pending = await cursor.fetchone()
        if not pending or not await _invite_ancestry_is_valid(db, pending["referrer_id"], task.user_id):
            return False
        claimed = await db.execute(
            """UPDATE referral_activation_bonuses
               SET qualifying_generation_id = ?, granted_at = CURRENT_TIMESTAMP
               WHERE referred_id = ? AND referrer_id = ? AND granted_at IS NULL""",
            (task.id, task.user_id, pending["referrer_id"]),
        )
        if claimed.rowcount != 1:
            await db.commit()
            return False
        updated = await db.execute(
            """UPDATE users SET credits = credits + ?, referral_earned = referral_earned + ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (pending["bonus_credits"], pending["bonus_credits"], pending["referrer_id"]),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Invite bonus recipient missing")
        await db.execute(
            "UPDATE referrals SET bonus_credits = ? WHERE referrer_id = ? AND referred_id = ?",
            (pending["bonus_credits"], pending["referrer_id"], task.user_id),
        )
        await db.commit()
        logger.info("Invite activation bonus credited: generation_id=%s referred_id=%s referrer_id=%s",
                    task.id, task.user_id, pending["referrer_id"])
        return True


async def mark_generation_accepted(task_id: str) -> bool:
    """Credit only canonical server proof already persisted with task/provider ID.

    There is no separate acceptance-marker write to lose after an accepted launch.
    Bookkeeping errors never fail that launch or cause its debit to be refunded.
    """
    from bot.database import get_task_by_id

    try:
        task = await get_task_by_id(task_id)
        if not _qualifying_task_proof(task):
            return False
        return await _credit_accepted_invite_bonus(task)
    except Exception:
        logger.exception("Invite qualification bookkeeping failed: task_id=%s", task_id)
        return False


async def reconcile_pending_invite_bonuses(limit: int = 100) -> int:
    """Fairly retry one durable accepted candidate per pending referral."""
    from bot.database import get_task_by_id

    credited = 0
    try:
        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            safe_json = "CASE WHEN json_valid(task.request_data) THEN task.request_data ELSE '{}' END"
            if db_backend.is_postgres():
                version = f"(({safe_json})::jsonb ->> 'partner_policy_version') = '2'"
                accepted = f"(({safe_json})::jsonb ->> 'partner_generation_accepted') = 'true'"
                eligible = f"(({safe_json})::jsonb ->> 'partner_invite_eligible') = 'true'"
            else:
                version = f"json_extract({safe_json}, '$.partner_policy_version') = 2"
                accepted = f"json_extract({safe_json}, '$.partner_generation_accepted') = 1"
                eligible = f"json_extract({safe_json}, '$.partner_invite_eligible') = 1"
            cursor = await db.execute(
                f"""SELECT bonus.referred_id, MIN(task.id) AS generation_id
                   FROM referral_activation_bonuses bonus
                   JOIN generation_tasks task ON task.user_id = bonus.referred_id
                   WHERE bonus.granted_at IS NULL AND task.id > bonus.after_generation_id
                     AND task.type IN ('image', 'video', 'motion_control', 'audio', 'character') AND COALESCE(task.cost, 0) > 0
                     AND COALESCE(task.action_type, '') != 'admin_replay'
                     AND {version} AND {eligible}
                     AND ({accepted} OR (task.status = 'completed' AND task.result_url IS NOT NULL))
                   GROUP BY bonus.referred_id, bonus.last_checked_at
                   ORDER BY CASE WHEN bonus.last_checked_at IS NULL THEN 0 ELSE 1 END,
                            bonus.last_checked_at, bonus.referred_id LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            )
            candidates = [dict(row) for row in await cursor.fetchall()]
        for candidate in candidates:
            async with db_backend.connect() as db:
                await db.execute(
                    "UPDATE referral_activation_bonuses SET last_checked_at = CURRENT_TIMESTAMP WHERE referred_id = ?",
                    (candidate["referred_id"],),
                )
                cursor = await db.execute(
                    "SELECT task_id FROM generation_tasks WHERE id = ?", (candidate["generation_id"],),
                )
                identity = await cursor.fetchone()
                await db.commit()
            task = await get_task_by_id(str(identity[0])) if identity else None
            if _qualifying_task_proof(task) and await _credit_accepted_invite_bonus(task):
                credited += 1
    except Exception:
        logger.exception("Pending invite bonus reconciliation failed")
    return credited
