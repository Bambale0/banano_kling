"""Persistent, encrypted owner-scoped Astro queue with fenced job leases.

SQLite/PostgreSQL use the existing bot.db adapter. Every transition is a
conditional SQL update; workers cannot complete a job after losing their lease.
A crash may repeat an in-flight KIE call (the vendor offers no guaranteed
exactly-once charged request); completed checkpoint sections are never redone.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from bot import db
from bot.services.astro_report_pipeline import (
    ReportPlan,
    _fact_catalog,
    report_fingerprint,
)


@dataclass(frozen=True)
class AstroJobPolicy:
    max_attempts: int = 4
    retry_base_seconds: int = 5
    retry_max_seconds: int = 300
    lease_seconds: int = 180
    circuit_failures: int = 4
    circuit_cooldown_seconds: int = 120
    retention_days: int = 90

    def __post_init__(self):
        if not (1 <= self.max_attempts <= 20
                and 1 <= self.retry_base_seconds <= self.retry_max_seconds <= 86400
                and 10 <= self.lease_seconds <= 3600
                and 1 <= self.circuit_failures <= 100
                and 1 <= self.circuit_cooldown_seconds <= 86400
                and 1 <= self.retention_days <= 365):
            raise ValueError("Invalid Astro queue policy")

    @classmethod
    def from_env(cls):
        return cls(
            max_attempts=int(os.getenv("ASTRO_REPORT_MAX_ATTEMPTS", "4")),
            retry_base_seconds=int(os.getenv("ASTRO_REPORT_RETRY_BASE_SECONDS", "5")),
            retry_max_seconds=int(os.getenv("ASTRO_REPORT_RETRY_MAX_SECONDS", "300")),
            lease_seconds=int(os.getenv("ASTRO_REPORT_LEASE_SECONDS", "180")),
            circuit_failures=int(os.getenv("ASTRO_REPORT_CIRCUIT_FAILURES", "4")),
            circuit_cooldown_seconds=int(os.getenv("ASTRO_REPORT_CIRCUIT_COOLDOWN_SECONDS", "120")),
            retention_days=int(os.getenv("ASTRO_REPORT_RETENTION_DAYS", "90")),
        )


@dataclass(frozen=True)
class ClaimedAstroJob:
    job_id: str
    owner_id: int
    fingerprint: str
    service_id: str
    facts: dict
    attempt: int
    worker_id: str


async def _create_astro_table(conn, sql: str) -> None:
    """PostgreSQL adapter skips generic SQLite CREATE; use native DDL."""
    if db.is_postgres():
        await conn.execute_native_ddl(sql)
    else:
        await conn.execute(sql)


class AstroReportJobs:
    def __init__(
        self, *, db_path: str | None = None, fingerprint_secret: str,
        data_key: bytes | str, policy: AstroJobPolicy | None = None,
    ):
        if not fingerprint_secret or len(fingerprint_secret) < 12:
            raise ValueError("ASTRO_REPORT_FINGERPRINT_SECRET is required")
        self.db_path = db_path
        self.fingerprint_secret = fingerprint_secret
        self.data_key = data_key
        self.policy = policy or AstroJobPolicy.from_env()
        self._cipher = Fernet(data_key)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @classmethod
    def from_env(cls):
        secret = os.getenv("ASTRO_REPORT_FINGERPRINT_SECRET", "")
        key = os.getenv("ASTRO_REPORT_DATA_KEY", "")
        return cls(fingerprint_secret=secret, data_key=key, policy=AstroJobPolicy.from_env())

    def _connect(self):
        return db.connect(self.db_path)

    def _seal(self, value: dict, *, max_bytes: int = 250_000) -> str:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(raw) > max_bytes:
            raise ValueError("Astro report facts too large")
        return self._cipher.encrypt(raw).decode("ascii")

    def _unseal(self, text: str) -> dict:
        try:
            data = json.loads(self._cipher.decrypt(text.encode("ascii")))
        except (InvalidToken, ValueError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError("Astro report payload cannot be decrypted") from exc
        if not isinstance(data, dict):
            raise TypeError("Astro report payload format invalid")
        return data

    async def initialize(self):
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with self._connect() as conn:
                await _create_astro_table(conn, """
                    CREATE TABLE IF NOT EXISTS astro_report_jobs (
                        job_id TEXT PRIMARY KEY,
                        owner_id BIGINT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        service_id TEXT NOT NULL,
                        facts_sealed TEXT NOT NULL,
                        report_sealed TEXT,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_run_at BIGINT NOT NULL,
                        lease_until BIGINT NOT NULL DEFAULT 0,
                        worker_id TEXT,
                        error_code TEXT,
                        created_at BIGINT NOT NULL,
                        updated_at BIGINT NOT NULL,
                        expires_at BIGINT NOT NULL,
                        consent_version TEXT NOT NULL,
                        UNIQUE (owner_id, fingerprint)
                    )
                """)
                await _create_astro_table(conn, "CREATE INDEX IF NOT EXISTS idx_astro_jobs_due "
                                   "ON astro_report_jobs (status, next_run_at, lease_until)")
                await _create_astro_table(conn, "CREATE INDEX IF NOT EXISTS idx_astro_jobs_owner "
                                   "ON astro_report_jobs (owner_id, created_at)")
                await _create_astro_table(conn, """
                    CREATE TABLE IF NOT EXISTS astro_report_circuit (
                        provider TEXT PRIMARY KEY, failures INTEGER NOT NULL,
                        opened_until BIGINT NOT NULL
                    )
                """)
                await conn.execute("INSERT INTO astro_report_circuit "
                                   "(provider, failures, opened_until) VALUES ('kie', 0, 0) "
                                   "ON CONFLICT (provider) DO NOTHING")
                # Separate table avoids an unsafe ALTER of an existing encrypted jobs schema.
                # At most one explicit paid requeue is permitted for any job ID.
                await _create_astro_table(conn, """
                    CREATE TABLE IF NOT EXISTS astro_report_manual_retry (
                        job_id TEXT PRIMARY KEY,
                        retried_at BIGINT NOT NULL
                    )
                """)
                await conn.commit()
            self._initialized = True

    async def enqueue(
        self, *, owner_id: int, plan: ReportPlan, facts: dict,
        consent: bool, now: int | None = None,
    ) -> str:
        if consent is not True:
            raise ValueError("Explicit Astro birth-data storage consent required")
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid report owner")
        now = int(time.time()) if now is None else now
        approved = _fact_catalog(facts)
        fingerprint = report_fingerprint(
            owner_id=owner_id, plan=plan, facts=approved,
            secret=self.fingerprint_secret,
        )
        sealed = self._seal(approved)
        job_id = uuid4().hex
        await self.initialize()
        # UNIQUE(owner,fingerprint) must not pin expired data forever.
        await self.purge_expired(now=now)
        async with self._connect() as conn:
            await conn.execute("""
                INSERT INTO astro_report_jobs (
                    job_id, owner_id, fingerprint, service_id, facts_sealed,
                    status, next_run_at, created_at, updated_at, expires_at, consent_version
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, 'astro-consent-v1')
                ON CONFLICT (owner_id, fingerprint) DO NOTHING
            """, (job_id, owner_id, fingerprint, plan.service_id, sealed,
                  now, now, now, now + 86400 * self.policy.retention_days))
            cursor = await conn.execute(
                "SELECT job_id FROM astro_report_jobs WHERE owner_id=? AND fingerprint=?",
                (owner_id, fingerprint),
            )
            row = await cursor.fetchone()
            await conn.commit()
        if not row:
            raise RuntimeError("Astro enqueue did not persist")
        return str(row[0])

    async def retry_failed(
        self, *, owner_id: int, job_id: str, consent: bool,
        now: int | None = None,
    ) -> bool:
        """One owner-authorized restart of recoverable failures; retain checkpoints.

        The conditional UPDATE is the admission lock: duplicate concurrent taps
        never queue a second charged worker. Permanently rejected jobs remain failed.
        """
        if type(owner_id) is not int or owner_id <= 0 or not isinstance(job_id, str):
            return False
        if len(job_id) != 32 or consent is not True:
            return False
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            cursor = await conn.execute("""
                UPDATE astro_report_jobs
                SET status='queued', attempts=0, next_run_at=?, updated_at=?,
                    lease_until=0, worker_id=NULL, error_code=NULL
                WHERE job_id=? AND owner_id=? AND status='failed'
                    AND expires_at > ?
                    AND error_code IN (
                        'temporary_provider_failure', 'internal_retry', 'lease_exhausted'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM astro_report_manual_retry
                        WHERE astro_report_manual_retry.job_id=astro_report_jobs.job_id
                    )
            """, (now, now, job_id, owner_id, now))
            accepted = cursor.rowcount == 1
            if accepted:
                await conn.execute("""
                    INSERT INTO astro_report_manual_retry (job_id, retried_at)
                    VALUES (?, ?)
                """, (job_id, now))
            await conn.commit()
        return accepted

    async def status(self, *, owner_id: int, job_id: str, now: int | None = None) -> dict | None:
        if type(owner_id) is not int or owner_id <= 0 or not isinstance(job_id, str):
            return None
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            cursor = await conn.execute("""
                SELECT service_id, status, attempts, error_code, report_sealed
                FROM astro_report_jobs
                WHERE job_id=? AND owner_id=? AND expires_at > ?
            """, (job_id, owner_id, now))
            row = await cursor.fetchone()
        if not row:
            return None
        output = {"job_id": job_id, "service_id": row[0], "status": row[1],
                  "attempts": row[2], "error_code": row[3]}
        if row[1] == "completed":
            output["report"] = self._unseal(row[4])
        return output

    async def claim(self, *, worker_id: str, now: int | None = None) -> ClaimedAstroJob | None:
        if not worker_id or len(worker_id) > 100:
            raise ValueError("Invalid worker id")
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            # A repeatedly crashed worker must not keep charging provider calls.
            await conn.execute("""
                UPDATE astro_report_jobs SET status='failed', worker_id=NULL,
                    lease_until=0, error_code='lease_exhausted', updated_at=?
                WHERE attempts >= ? AND expires_at > ? AND (
                    (status='running' AND lease_until <= ?) OR
                    (status='queued' AND next_run_at <= ?)
                )
            """, (now, self.policy.max_attempts, now, now, now))
            cursor = await conn.execute("""
                WITH candidate AS (
                    SELECT job_id FROM astro_report_jobs
                    WHERE expires_at > ? AND attempts < ? AND (
                        (status='queued' AND next_run_at <= ?)
                        OR (status='running' AND lease_until <= ?)
                    )
                    ORDER BY next_run_at, created_at, job_id LIMIT 1
                )
                UPDATE astro_report_jobs SET status='running', worker_id=?,
                    lease_until=?, attempts=attempts+1, updated_at=?
                WHERE job_id=(SELECT job_id FROM candidate)
                    AND expires_at > ? AND attempts < ?
                    AND ((status='queued' AND next_run_at <= ?)
                         OR (status='running' AND lease_until <= ?))
                RETURNING job_id, owner_id, fingerprint, service_id,
                          facts_sealed, attempts
            """, (now, self.policy.max_attempts, now, now,
                  worker_id, now + self.policy.lease_seconds, now,
                  now, self.policy.max_attempts, now, now))
            row = await cursor.fetchone()
            await conn.commit()
        if not row:
            return None
        return ClaimedAstroJob(
            job_id=str(row[0]), owner_id=int(row[1]), fingerprint=str(row[2]),
            service_id=str(row[3]), facts=self._unseal(str(row[4])),
            attempt=int(row[5]), worker_id=worker_id,
        )

    async def heartbeat(self, *, job_id: str, worker_id: str, now: int | None = None) -> bool:
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            cursor = await conn.execute("""
                UPDATE astro_report_jobs SET lease_until=?, updated_at=?
                WHERE job_id=? AND worker_id=? AND status='running'
                  AND lease_until > ? AND expires_at > ?
            """, (now + self.policy.lease_seconds, now, job_id, worker_id, now, now))
            await conn.commit()
            return cursor.rowcount == 1

    async def complete(
        self, *, job_id: str, worker_id: str, report: dict, now: int | None = None,
    ) -> bool:
        await self.initialize()
        now = int(time.time()) if now is None else now
        if not isinstance(report, dict) or report.get("status") != "completed":
            raise ValueError("Only fully validated Astro reports can complete")
        # A 10k–18k-word Russian report can exceed 250KB in UTF-8.
        sealed = self._seal(report, max_bytes=3_000_000)
        async with self._connect() as conn:
            cursor = await conn.execute("""
                UPDATE astro_report_jobs SET status='completed',
                    report_sealed=?, facts_sealed='', worker_id=NULL,
                    lease_until=0, updated_at=?
                WHERE job_id=? AND worker_id=? AND status='running'
                  AND lease_until > ? AND expires_at > ?
            """, (sealed, now, job_id, worker_id, now, now))
            await conn.commit()
            return cursor.rowcount == 1

    async def reschedule(
        self, *, job_id: str, worker_id: str, retry: bool,
        error_code: str, now: int | None = None,
    ) -> bool:
        await self.initialize()
        now = int(time.time()) if now is None else now
        if not error_code or len(error_code) > 80 or not error_code.replace("_", "").isalnum():
            raise ValueError("Invalid safe retry error code")
        async with self._connect() as conn:
            cursor = await conn.execute("""
                SELECT attempts FROM astro_report_jobs
                WHERE job_id=? AND worker_id=? AND status='running'
                    AND lease_until > ?
            """, (job_id, worker_id, now))
            row = await cursor.fetchone()
            if not row:
                return False
            attempts = int(row[0])
            resume = retry and attempts < self.policy.max_attempts
            delay = min(self.policy.retry_max_seconds,
                        self.policy.retry_base_seconds * 2 ** (attempts - 1))
            cursor = await conn.execute("""
                UPDATE astro_report_jobs SET status=?, worker_id=NULL,
                    lease_until=0, error_code=?, next_run_at=?, updated_at=?
                WHERE job_id=? AND worker_id=? AND status='running'
                    AND lease_until > ?
            """, ("queued" if resume else "failed", error_code, now + delay,
                  now, job_id, worker_id, now))
            await conn.commit()
            return cursor.rowcount == 1

    async def circuit_allows(self, *, now: int | None = None) -> bool:
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            cursor = await conn.execute(
                "SELECT opened_until FROM astro_report_circuit WHERE provider='kie'"
            )
            row = await cursor.fetchone()
        return bool(row) and int(row[0]) <= now

    async def circuit_failure(self, *, now: int | None = None):
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            await conn.execute("""
                UPDATE astro_report_circuit SET failures=failures+1,
                    opened_until=CASE WHEN failures+1 >= ? THEN ? ELSE opened_until END
                WHERE provider='kie'
            """, (self.policy.circuit_failures,
                  now + self.policy.circuit_cooldown_seconds))
            await conn.commit()

    async def circuit_success(self):
        await self.initialize()
        async with self._connect() as conn:
            await conn.execute("UPDATE astro_report_circuit SET failures=0, opened_until=0 "
                               "WHERE provider='kie'")
            await conn.commit()

    async def list_owner(
        self, *, owner_id: int, service_id: str | None = None,
        limit: int = 30, now: int | None = None,
    ) -> list[dict]:
        """Metadata only; never expose encrypted facts, sections or other owners."""
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid Astro history owner")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid Astro history limit")
        if service_id is not None and service_id not in (
            "natal", "compatibility", "karma", "year", "month", "solar", "lunar",
        ):
            raise ValueError("Invalid Astro history service")
        await self.initialize()
        now = int(time.time()) if now is None else now
        where_service = " AND service_id = ?" if service_id else ""
        params = (owner_id, now, service_id, limit) if service_id else (owner_id, now, limit)
        async with self._connect() as conn:
            cursor = await conn.execute(
                "SELECT job_id, service_id, status, attempts, created_at, "
                "updated_at, error_code FROM astro_report_jobs "
                "WHERE owner_id = ? AND expires_at > ?" + where_service +
                " ORDER BY created_at DESC, job_id DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
        return [{
            "job_id": str(row[0]), "service_id": str(row[1]),
            "status": str(row[2]), "attempts": int(row[3]),
            "created_at": int(row[4]), "updated_at": int(row[5]),
            "error_code": row[6],
        } for row in rows]

    async def delete_owner(self, *, owner_id: int) -> int:
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid owner")
        await self.initialize()
        async with self._connect() as conn:
            await conn.execute("""
                DELETE FROM astro_report_manual_retry WHERE job_id IN (
                    SELECT job_id FROM astro_report_jobs WHERE owner_id=?
                )
            """, (owner_id,))
            cursor = await conn.execute(
                "DELETE FROM astro_report_jobs WHERE owner_id=?", (owner_id,)
            )
            await conn.commit()
            return max(0, int(cursor.rowcount or 0))

    async def purge_expired(self, *, now: int | None = None) -> int:
        await self.initialize()
        now = int(time.time()) if now is None else now
        async with self._connect() as conn:
            cursor = await conn.execute(
                "DELETE FROM astro_report_jobs WHERE expires_at <= ?", (now,)
            )
            await conn.execute("""
                DELETE FROM astro_report_manual_retry WHERE NOT EXISTS (
                    SELECT 1 FROM astro_report_jobs
                    WHERE astro_report_jobs.job_id=astro_report_manual_retry.job_id
                )
            """)
            await conn.commit()
            return max(0, int(cursor.rowcount or 0))
