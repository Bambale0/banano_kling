from __future__ import annotations

from pathlib import Path

import pytest

from bot import postgres_aiosqlite as postgres_backend
from bot.services import trend_success_postgres_compat as compat


class _FakeCursor:
    def __init__(self, statements: list[str]):
        self.statements = statements

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, params=None):
        self.statements.append(" ".join(sql.split()))


class _FakeConnection:
    def __init__(self):
        self.statements: list[str] = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self.statements)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_postgres_trend_success_schema_uses_real_helper_cursor(monkeypatch):
    calls: list[str] = []

    async def original_helpers(conn):
        calls.append("original")

    monkeypatch.setattr(compat.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(postgres_backend, "_ensure_postgres_helpers", original_helpers)
    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(compat, "_HELPERS_EXTENDED", False)

    compat.install_trend_success_postgres_compat()

    conn = _FakeConnection()
    await postgres_backend._ensure_postgres_helpers(conn)

    assert calls == ["original"]
    assert any(
        "CREATE TABLE IF NOT EXISTS trend_generation_runs" in sql
        for sql in conn.statements
    )
    assert any(
        "CREATE INDEX IF NOT EXISTS idx_trend_generation_runs_trend" in sql
        for sql in conn.statements
    )
    assert conn.commits == 1


def test_trend_schema_hook_is_installed_before_metrics_runtime():
    source = Path("bot/handlers/repeat_run_confirm_compat.py").read_text(encoding="utf-8")

    schema_call = source.index("install_trend_success_postgres_compat()")
    metrics_call = source.index("install_trend_success_compat()")
    assert schema_call < metrics_call
