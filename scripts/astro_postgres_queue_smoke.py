"""Actual isolated PostgreSQL DB smoke for Astro SQL queue and checkpoints."""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import psycopg
from cryptography.fernet import Fernet

from bot import db
from bot.postgres_aiosqlite import PostgresConnection
from bot.services.astro_report_jobs import AstroJobPolicy, AstroReportJobs
from bot.services.astro_report_pipeline import load_report_plan
from bot.services.astro_report_store import AstroReportSqlStore


async def main():
    assert os.getenv("DATABASE_URL", "").startswith("postgresql://")

    @asynccontextmanager
    async def isolated_pg_connection(_unused=None):
        # Skip unrelated app-global PG bootstrap: smoke the Astro DDL and SQL
        # against a real disposable PostgreSQL using the actual translator.
        raw = await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            yield PostgresConnection(raw)
        finally:
            await raw.close()

    db.connect = isolated_pg_connection
    data_key = Fernet.generate_key()
    jobs = AstroReportJobs(
        fingerprint_secret="synthetic-test-secret-astro-pg", data_key=data_key,
        policy=AstroJobPolicy(lease_seconds=15, max_attempts=3),
    )
    store = AstroReportSqlStore()
    await jobs.initialize()
    await store.initialize()
    source = {"schema_version": "astro.natal-facts.v1", "chart": {
        "bodies": {"Sun": {"lon": 61.24}}, "accuracy": {"birth_time_known": True},
    }}
    identifier = await jobs.enqueue(
        owner_id=991234, plan=load_report_plan("natal"), facts=source,
        consent=True,
    )
    assert await jobs.status(owner_id=991234, job_id=identifier)
    assert await jobs.status(owner_id=991235, job_id=identifier) is None
    # Independent connection/pool calls need one and only one claimant.
    now = int(time.time())
    claims = await asyncio.gather(*[
        jobs.claim(worker_id=f"isolated-worker-{i}", now=now) for i in range(8)
    ])
    accepted = [c for c in claims if c is not None]
    assert len(accepted) == 1, f"nonexclusive PG claim, accepted={len(accepted)}"
    claim = accepted[0]
    assert claim.job_id == identifier
    assert await store.save_if_absent(
        owner_id=991234, fingerprint=claim.fingerprint, section_id="intro",
        text="Проверенный синтетический текст",
    ) == "Проверенный синтетический текст"
    assert await store.read(owner_id=991234, fingerprint=claim.fingerprint, section_id="intro")
    await jobs.reschedule(
        job_id=identifier, worker_id=claim.worker_id, now=now + 1,
        retry=False, error_code="test_complete",
    )
    status = await jobs.status(owner_id=991234, job_id=identifier)
    assert status and status["status"] == "failed"
    print("POSTGRES_ASTRO_SQL_OK schema=created claims=1/8 checkpoint=stored owner_filter=yes", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
