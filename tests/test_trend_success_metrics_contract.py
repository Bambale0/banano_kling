from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.handlers import trend_success_compat


def test_public_trend_counter_is_separate_from_accepted_uses_count() -> None:
    prompt = {
        "id": 42,
        "tags": ["trend"],
        "description": "Портрет по вашему фото",
        "uses_count": 99,
    }
    enriched = trend_success_compat._public_counter_description(prompt, 7)

    assert enriched["successful_runs_count"] == 7
    assert enriched["uses_count"] == 99
    assert enriched["description"].startswith("✅ Успешных запусков: 7")
    assert prompt["description"] == "Портрет по вашему фото"


@pytest.mark.asyncio
async def test_successful_launch_links_exact_task_to_trend(monkeypatch) -> None:
    recorded: list[dict] = []

    async def fake_register(**kwargs):
        recorded.append(kwargs)
        return True

    monkeypatch.setattr(
        trend_success_compat,
        "register_trend_generation_run",
        fake_register,
    )
    response = SimpleNamespace(
        body=json.dumps({"ok": True, "task_id": "provider_task_123"}).encode()
    )

    await trend_success_compat._record_response_task(
        response,
        SimpleNamespace(trend_id=55),
        SimpleNamespace(id=77),
    )

    assert recorded == [
        {"task_id": "provider_task_123", "trend_id": 55, "user_id": 77}
    ]


@pytest.mark.asyncio
async def test_failed_launch_does_not_register_success_candidate(monkeypatch) -> None:
    called = False

    async def fake_register(**_kwargs):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(
        trend_success_compat,
        "register_trend_generation_run",
        fake_register,
    )
    response = SimpleNamespace(
        body=json.dumps({"ok": False, "task_id": "failed_task"}).encode()
    )

    await trend_success_compat._record_response_task(
        response,
        SimpleNamespace(trend_id=55),
        SimpleNamespace(id=77),
    )

    assert called is False


def test_success_count_query_uses_completed_generation_rows() -> None:
    source = Path("bot/handlers/trend_success_compat.py").read_text(encoding="utf-8")
    assert "task_id TEXT PRIMARY KEY" in source
    assert "JOIN generation_tasks g ON g.task_id = r.task_id" in source
    assert "g.status = 'completed'" in source


@pytest.mark.asyncio
async def test_trend_run_schema_tracks_active_sqlite_database(tmp_path, monkeypatch):
    # The same server process can move between independent SQLite DBs during
    # tests/reconfiguration; a global boolean must not attach to the wrong DB.
    import aiosqlite

    from bot import database
    from bot import db as db_backend

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_LOCK", None)
    files = [tmp_path / "user-a.sqlite", tmp_path / "user-b.sqlite"]
    for file in files:
        monkeypatch.setattr(database, "DATABASE_PATH", str(file))
        monkeypatch.setattr(db_backend, "DATABASE_PATH", str(file))
        await database.init_db()
        await trend_success_compat.ensure_trend_generation_run_schema()
        async with aiosqlite.connect(file) as db:
            row = await (await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'trend_generation_runs'"
            )).fetchone()
            assert row is not None, f"trend run table was not created in {file.name}"


@pytest.mark.asyncio
async def test_pg_trend_success_helpers_run_again_in_another_schema(monkeypatch):
    from bot import postgres_aiosqlite as pg
    from bot.services import trend_success_postgres_compat as compat

    monkeypatch.setattr(compat.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(compat, "_HELPERS_EXTENDED_SCHEMAS", set())
    monkeypatch.setattr(compat, "_HELPERS_EXTENSION_LOCK", None)

    async def original(_conn):
        return None
    monkeypatch.setattr(pg, "_ensure_postgres_helpers", original)

    class Conn:
        def __init__(self, schema):
            self.schema = schema
            self.commands = []
            self.last = ""
        def cursor(self):
            return self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def execute(self, query):
            self.last = query
            self.commands.append(query)
        async def fetchone(self):
            return ("test_db", self.schema)
        async def commit(self):
            pass

    compat.install_trend_success_postgres_compat()
    first, second = Conn("test_schema_a"), Conn("test_schema_b")
    await pg._ensure_postgres_helpers(first)
    await pg._ensure_postgres_helpers(second)
    assert sum("CREATE TABLE IF NOT EXISTS trend_generation_runs" in sql
               for sql in first.commands) == 1
    assert sum("CREATE TABLE IF NOT EXISTS trend_generation_runs" in sql
               for sql in second.commands) == 1
