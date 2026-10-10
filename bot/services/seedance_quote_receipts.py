"""Durable actor-bound quote approval and atomic single-use Seedance debit.

Feature-owned tables only. No existing accepted snapshots/history are rewritten.
Database adapter is injected so transaction tests need no application bootstrap.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime, timedelta


class QuoteConflict(ValueError):
    pass


class InsufficientCredits(ValueError):
    pass


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SeedanceQuoteReceipts:
    def __init__(self, connect, row_factory, storage_lock=None, validate_media=None, allow_new_claim=None):
        self.connect = connect
        self.row_factory = row_factory
        self.storage_lock = storage_lock
        self.validate_media = validate_media
        self.allow_new_claim = allow_new_claim

    async def ensure_schema(self):
        async with self.connect() as db:
            native = getattr(db, "execute_native_ddl", None)
            if native:
                await native("SELECT pg_advisory_xact_lock(73003003)")
            statements = [
                """CREATE TABLE IF NOT EXISTS seedance_snapshot_reservations (
                    upload_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS seedance_quote_receipts (
                    quote_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL, original_json TEXT NOT NULL,
                    provider_json TEXT NOT NULL, billing_json TEXT NOT NULL,
                    quote_hash TEXT NOT NULL, charged_cost REAL NOT NULL DEFAULT 0,
                    phase TEXT NOT NULL DEFAULT 'quoted', provider_task_id TEXT,
                    canonical_bound INTEGER NOT NULL DEFAULT 0,
                    refunded INTEGER NOT NULL DEFAULT 0, expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS seedance_quote_media_leases (
                    quote_id TEXT NOT NULL, media_id BIGINT NOT NULL,
                    PRIMARY KEY (quote_id, media_id)
                )""",
            ]
            for statement in statements:
                if native:
                    await native(statement.replace(" REAL ", " DOUBLE PRECISION "))
                else:
                    await db.execute(statement)
            await db.commit()

    async def create(self, *, user_id: int, telegram_id: int, original: dict,
                     provider: dict, billing: dict, media_ids: list[int]) -> dict:
        if billing.get("version") != 2 or billing.get("model") not in {"seedance_2", "seedance_2_5"}:
            raise ValueError("Unsupported measured Seedance quote")
        expires = (datetime.now(UTC) + timedelta(minutes=15)).replace(tzinfo=None).isoformat(" ")
        quote_id = uuid.uuid4().hex
        snapshot = {"actor": telegram_id, "quote_id": quote_id,
                    "original": original, "provider": provider, "billing": billing}
        quote_hash = hashlib.sha256(canonical_json(snapshot).encode()).hexdigest()
        async with self.connect() as db:
            if self.storage_lock:
                await self.storage_lock(db)
            await db.execute(
                "INSERT INTO seedance_quote_receipts (quote_id,user_id,telegram_id,original_json,"
                "provider_json,billing_json,quote_hash,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (quote_id, user_id, telegram_id, canonical_json(original), canonical_json(provider),
                 canonical_json(billing), quote_hash, expires),
            )
            for media_id in set(media_ids):
                owned = await (await db.execute(
                    "SELECT id FROM wan3_prime_media WHERE id = ? AND user_id = ? "
                    "AND source = 'seedance_quote_snapshot'", (media_id, user_id),
                )).fetchone()
                if not owned:
                    raise QuoteConflict("Snapshot ownership changed")
                await db.execute("INSERT INTO seedance_quote_media_leases (quote_id,media_id) VALUES (?,?)",
                                 (quote_id, media_id))
            await db.commit()
        return await self.find(telegram_id, quote_id)

    async def find(self, telegram_id: int, quote_id: str) -> dict | None:
        if not re.fullmatch(r"[a-f0-9]{32}", str(quote_id)):
            raise QuoteConflict("Рассчитайте цену перед запуском")
        async with self.connect() as db:
            db.row_factory = self.row_factory
            row = await (await db.execute(
                "SELECT * FROM seedance_quote_receipts WHERE quote_id = ? AND telegram_id = ?",
                (quote_id, telegram_id),
            )).fetchone()
            return dict(row) if row else None

    async def claim(self, *, telegram_id: int, quote_id: str, quote_hash: str,
                    original: dict, current_billing: dict) -> dict:
        async with self.connect() as db:
            db.row_factory = self.row_factory
            if self.storage_lock:
                await self.storage_lock(db)
            locked = await db.execute(
                "UPDATE users SET updated_at = updated_at WHERE telegram_id = ?", (telegram_id,),
            )
            if locked.rowcount != 1:
                raise QuoteConflict("Владелец запуска не найден")
            row = await (await db.execute(
                "SELECT * FROM seedance_quote_receipts WHERE quote_id = ? AND telegram_id = ?",
                (quote_id, telegram_id),
            )).fetchone()
            if not row or row["quote_hash"] != quote_hash or row["original_json"] != canonical_json(original):
                raise QuoteConflict("Настройки изменились. Проверьте новый расчёт")
            if row["phase"] != "quoted":
                await db.commit()
                return dict(row, created=False)
            expiry = datetime.fromisoformat(str(row["expires_at"]))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= datetime.now(UTC) or row["billing_json"] != canonical_json(current_billing):
                raise QuoteConflict("Цена изменилась или устарела. Проверьте новый расчёт")
            pending = await (await db.execute(
                "SELECT quote_id FROM seedance_quote_receipts WHERE user_id = ? "
                "AND (phase IN ('submitting','outcome_unknown') OR (phase = 'accepted' AND canonical_bound = 0)) LIMIT 1",
                (row["user_id"],),
            )).fetchone()
            if pending:
                raise QuoteConflict("Предыдущий запуск ещё проверяется. Повторное списание заблокировано")
            if self.validate_media:
                await self.validate_media(db, quote_id, row["user_id"])
            # Last admission check under the claim lock, after async media checks.
            # Previously claimed/unknown/accepted rows returned above stay recoverable.
            if self.allow_new_claim and not self.allow_new_claim():
                raise QuoteConflict("Новые запуски Seedance временно приостановлены. Уже принятые задачи продолжаются.")
            charge = float(current_billing["charge_cost"])
            if not math.isfinite(charge) or charge < 0:
                raise QuoteConflict("Некорректная цена")
            if charge:
                debited = await db.execute(
                    "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND telegram_id = ? AND credits >= ?",
                    (charge, row["user_id"], telegram_id, charge),
                )
                if debited.rowcount != 1:
                    raise InsufficientCredits("Недостаточно бананов")
            await db.execute(
                "UPDATE seedance_quote_receipts SET phase='submitting', charged_cost=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE quote_id=? AND phase='quoted'", (charge, quote_id),
            )
            await db.commit()
            return dict(row, phase="submitting", charged_cost=charge, created=True)

    async def accepted(self, quote_id: str, provider_task_id: str) -> bool:
        if not provider_task_id:
            raise ValueError("Missing provider task ID")
        async with self.connect() as db:
            result = await db.execute(
                "UPDATE seedance_quote_receipts SET phase='accepted',provider_task_id=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE quote_id=? AND phase IN ('submitting','outcome_unknown','accepted') "
                "AND (provider_task_id IS NULL OR provider_task_id=?)", (provider_task_id, quote_id, provider_task_id),
            )
            await db.commit()
            return result.rowcount == 1

    async def unknown(self, quote_id: str):
        async with self.connect() as db:
            await db.execute("UPDATE seedance_quote_receipts SET phase='outcome_unknown',updated_at=CURRENT_TIMESTAMP "
                             "WHERE quote_id=? AND phase='submitting'", (quote_id,))
            await db.commit()

    async def mark_bound(self, quote_id: str, provider_task_id: str):
        async with self.connect() as db:
            await db.execute("UPDATE seedance_quote_receipts SET canonical_bound=1,updated_at=CURRENT_TIMESTAMP "
                             "WHERE quote_id=? AND provider_task_id=? AND phase='accepted'", (quote_id, provider_task_id))
            await db.commit()

    async def unbound_accepted(self, limit=20):
        async with self.connect() as db:
            db.row_factory = self.row_factory
            rows = await (await db.execute("SELECT * FROM seedance_quote_receipts WHERE phase='accepted' "
                                           "AND canonical_bound=0 AND provider_task_id IS NOT NULL ORDER BY created_at LIMIT ?",
                                           (limit,))).fetchall()
            return [dict(row) for row in rows]

    async def rejected_and_refund(self, quote_id: str) -> bool:
        """Caller must prove rejection before any accepted task; no timeout refunds."""
        async with self.connect() as db:
            db.row_factory = self.row_factory
            row = await (await db.execute(
                "UPDATE seedance_quote_receipts SET phase='rejected',refunded=1,updated_at=CURRENT_TIMESTAMP "
                "WHERE quote_id=? AND phase='submitting' AND provider_task_id IS NULL AND refunded=0 "
                "RETURNING user_id,telegram_id,charged_cost", (quote_id,),
            )).fetchone()
            if not row:
                await db.rollback()
                return False
            if row["charged_cost"]:
                credit = await db.execute("UPDATE users SET credits=credits+?,updated_at=CURRENT_TIMESTAMP "
                                          "WHERE id=? AND telegram_id=?",
                                          (row["charged_cost"], row["user_id"], row["telegram_id"]))
                if credit.rowcount != 1:
                    raise QuoteConflict("Refund owner changed")
            await db.commit()
            return True
