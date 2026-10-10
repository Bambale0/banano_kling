"""Durable Motion launch ownership, debit and rejection-only refund.

Callers supply the database adapter. Submitting/unknown receipts are never
automatically resubmitted. Historical task prices and ledger stay untouched.
"""
from __future__ import annotations

import hashlib
import json
import math
import re


class MotionLaunchConflict(ValueError):
    pass


class MotionInsufficientCredits(ValueError):
    pass


def _has_acceptance_witness(value) -> bool:
    if not isinstance(value, dict):
        return False
    if any(value.get(key) for key in ("task_id", "taskId", "id")):
        return True
    return any(_has_acceptance_witness(value.get(key)) for key in ("data", "raw", "response"))


def definitely_rejected_motion_result(result) -> bool:
    if not isinstance(result, dict) or _has_acceptance_witness(result):
        return False
    if result.get("error") in {
        "missing_api_key", "image_required", "video_url_required", "unsupported_motion_model",
    }:
        return True
    return result.get("error") == "api_error" and result.get("status_code") in {
        400, 401, 402, 403, 404, 422, 429,
    }


class MotionLaunchReceipts:
    def __init__(self, connect, row_factory):
        self.connect = connect
        self.row_factory = row_factory

    async def ensure_schema(self):
        async with self.connect() as db:
            statement = """CREATE TABLE IF NOT EXISTS motion_launch_receipts (
                receipt_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                telegram_id BIGINT NOT NULL,
                request_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                recipe_json TEXT NOT NULL,
                charged_cost REAL NOT NULL,
                phase TEXT NOT NULL,
                provider_task_id TEXT,
                refunded INTEGER NOT NULL DEFAULT 0,
                canonical_bound INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(telegram_id, request_key)
            )"""
            native = getattr(db, "execute_native_ddl", None)
            if native:
                await native("SELECT pg_advisory_xact_lock(73003002)")
                await native(statement.replace(" REAL ", " DOUBLE PRECISION "))
            else:
                await db.execute(statement)
            await db.commit()

    async def find(self, telegram_id: int, request_key: str) -> dict | None:
        if not re.fullmatch(r"[a-f0-9]{32}", str(request_key)):
            raise ValueError("Обновите Mini App: нужен идентификатор запуска Motion")
        async with self.connect() as db:
            db.row_factory = self.row_factory
            row = await (await db.execute(
                "SELECT * FROM motion_launch_receipts WHERE telegram_id = ? AND request_key = ?",
                (telegram_id, request_key),
            )).fetchone()
            return dict(row, created=False) if row else None

    async def reserve(self, *, user_id: int, telegram_id: int, request_key: str,
                      recipe: dict, cost: float, admin_free: bool) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}", str(request_key)):
            raise ValueError("Обновите Mini App: нужен идентификатор запуска Motion")
        if isinstance(cost, bool) or not math.isfinite(float(cost)) or cost < 0:
            raise ValueError("Некорректная стоимость Motion")
        recipe_json = json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(recipe_json.encode()).hexdigest()
        receipt_id = f"motion_launch_{telegram_id}_{request_key}"
        charge = 0.0 if admin_free else float(cost)
        async with self.connect() as db:
            db.row_factory = self.row_factory
            locked = await db.execute(
                "UPDATE users SET updated_at = updated_at WHERE id = ? AND telegram_id = ?",
                (user_id, telegram_id),
            )
            if locked.rowcount != 1:
                raise ValueError("Владелец Motion не найден")
            row = await (await db.execute(
                "SELECT * FROM motion_launch_receipts WHERE receipt_id = ?", (receipt_id,),
            )).fetchone()
            if row:
                await db.commit()
                if row["fingerprint"] != fingerprint:
                    raise MotionLaunchConflict("Этот запуск уже связан с другими настройками")
                return dict(row, created=False)
            pending = await (await db.execute(
                "SELECT receipt_id FROM motion_launch_receipts WHERE user_id = ? "
                "AND (phase IN ('submitting', 'outcome_unknown') OR (phase = 'accepted' AND canonical_bound = 0)) LIMIT 1", (user_id,),
            )).fetchone()
            if pending:
                await db.rollback()
                raise MotionLaunchConflict("Предыдущий запуск Motion ещё проверяется; повторное списание заблокировано")
            if charge > 0:
                debited = await db.execute(
                    "UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND telegram_id = ? AND credits >= ?",
                    (charge, user_id, telegram_id, charge),
                )
                if debited.rowcount != 1:
                    await db.rollback()
                    raise MotionInsufficientCredits("Недостаточно бананов")
            await db.execute(
                "INSERT INTO motion_launch_receipts "
                "(receipt_id, user_id, telegram_id, request_key, fingerprint, recipe_json, charged_cost, phase) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'submitting')",
                (receipt_id, user_id, telegram_id, request_key, fingerprint, recipe_json, charge),
            )
            await db.commit()
            return {"receipt_id": receipt_id, "user_id": user_id, "telegram_id": telegram_id,
                        "fingerprint": fingerprint, "recipe_json": recipe_json, "charged_cost": charge,
                        "phase": "submitting", "provider_task_id": None, "refunded": 0, "created": True}

    async def unbound_accepted(self, limit: int = 20) -> list[dict]:
        async with self.connect() as db:
            db.row_factory = self.row_factory
            rows = await (await db.execute(
                "SELECT * FROM motion_launch_receipts WHERE phase = 'accepted' "
                "AND canonical_bound = 0 AND provider_task_id IS NOT NULL "
                "ORDER BY created_at LIMIT ?", (limit,),
            )).fetchall()
            return [dict(row) for row in rows]

    async def mark_bound(self, receipt_id: str, provider_task_id: str) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE motion_launch_receipts SET canonical_bound = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE receipt_id = ? AND provider_task_id = ? AND phase = 'accepted'",
                (receipt_id, provider_task_id),
            )
            await db.commit()

    async def accepted(self, receipt_id: str, provider_task_id: str) -> bool:
        if not provider_task_id:
            raise ValueError("Missing accepted Motion task ID")
        async with self.connect() as db:
            result = await db.execute(
                "UPDATE motion_launch_receipts SET phase = 'accepted', provider_task_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE receipt_id = ? "
                "AND phase IN ('submitting', 'outcome_unknown', 'accepted') "
                "AND (provider_task_id IS NULL OR provider_task_id = ?)",
                (provider_task_id, receipt_id, provider_task_id),
            )
            await db.commit()
            return result.rowcount == 1

    async def unknown(self, receipt_id: str) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE motion_launch_receipts SET phase = 'outcome_unknown', updated_at = CURRENT_TIMESTAMP "
                "WHERE receipt_id = ? AND phase = 'submitting'", (receipt_id,),
            )
            await db.commit()

    async def rejected_and_refund(self, receipt_id: str) -> bool:
        """Only caller-proven non-acceptance enters here; credit and marker are atomic."""
        async with self.connect() as db:
            db.row_factory = self.row_factory
            cursor = await db.execute(
                "UPDATE motion_launch_receipts SET phase = 'rejected', refunded = 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE receipt_id = ? "
                "AND phase = 'submitting' AND refunded = 0 AND provider_task_id IS NULL "
                "RETURNING user_id, telegram_id, charged_cost", (receipt_id,),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return False
            if row["charged_cost"] > 0:
                credit = await db.execute(
                    "UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND telegram_id = ?",
                    (row["charged_cost"], row["user_id"], row["telegram_id"]),
                )
                if credit.rowcount != 1:
                    raise RuntimeError("Motion refund owner disappeared")
            await db.commit()
            return True
