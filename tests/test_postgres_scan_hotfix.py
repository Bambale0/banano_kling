"""Bound PostgreSQL maintenance scans without weakening referral crediting."""

from contextlib import asynccontextmanager

import pytest

from bot import partner_policy
from bot.services import wan3_prime_result_retention as retention


@pytest.mark.asyncio
async def test_postgres_result_cleanup_defers_unsafe_unindexed_scan(monkeypatch):
    monkeypatch.setattr(retention.db_backend, "is_postgres", lambda: True)
    monkeypatch.delenv("WAN3_PG_RESULT_FULL_SCAN_ENABLED", raising=False)

    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError("cleanup may not lock or scan generation_tasks")

    monkeypatch.setattr(retention.db_backend, "connect", unexpected_connect)
    assert await retention.cleanup_results(limit=50) == 0


@pytest.mark.asyncio
async def test_postgres_referral_reconciliation_advances_ineligible_fair_batch(monkeypatch):
    executed = []
    commits = []

    class Cursor:
        async def fetchall(self):
            return [{"referred_id": 42, "generation_id": None}]

    class DB:
        row_factory = None

        async def execute(self, query, params):
            executed.append((query, params))
            return Cursor()

        async def commit(self):
            commits.append(True)

    @asynccontextmanager
    async def connect(*_args, **_kwargs):
        yield DB()

    monkeypatch.setattr(partner_policy.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(partner_policy.db_backend, "connect", connect)
    assert await partner_policy.reconcile_pending_invite_bonuses(limit=1) == 0
    assert len(executed) == 1
    sql, params = executed[0]
    assert params == (1,)
    assert "WITH due AS MATERIALIZED" in sql
    assert "LEFT JOIN LATERAL" in sql
    assert "RETURNING bonus.referred_id, bonus.after_generation_id" in sql
    assert "SET last_checked_at = CURRENT_TIMESTAMP" in sql
    assert "ORDER BY task.id LIMIT 1" in sql
    assert commits == [True]
