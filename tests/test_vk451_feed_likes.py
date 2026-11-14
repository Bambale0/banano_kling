"""VK #451: platform-own public feed likes, atomic SQLite and signed HTTP."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database
from bot.shared_accounts import api
from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.vk_feed_likes import like_public_vk_feed


@pytest.fixture
def native_feed_db(tmp_path, monkeypatch):
    path = str(tmp_path / "vk-feed-likes.db")
    monkeypatch.setattr(database, "DATABASE_PATH", path)
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE generation_tasks (
            id INTEGER PRIMARY KEY, type TEXT, status TEXT,
            result_url TEXT, is_public_feed INTEGER, is_adult_content INTEGER,
            likes_count INTEGER DEFAULT 0
        )""")
        db.execute("""CREATE TABLE vk_feed_generation_likes (
            vk_user_id BIGINT NOT NULL, generation_task_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(vk_user_id, generation_task_id),
            FOREIGN KEY(generation_task_id) REFERENCES generation_tasks(id) ON DELETE CASCADE
        )""")
        db.executemany(
            """INSERT INTO generation_tasks
               (id, type, status, result_url, is_public_feed, is_adult_content, likes_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (41, "image", "completed", "https://example.test/41.jpg", 1, 0, 3),
                (42, "image", "completed", "https://example.test/private.jpg", 0, 0, 0),
                (43, "video", "completed", "https://example.test/43.mp4", 1, 1, 0),
            ],
        )
        db.commit()
    # The full DB card checks retained media, disclosure and publication
    # privacy. The test fixture only needs to isolate the atomic like ledger.
    async def public_card(gen_id, *, viewer_user_id=None):
        assert viewer_user_id is None
        return {"id": gen_id, "publication_scope": "feed"} if gen_id != 42 else None
    monkeypatch.setattr(database, "get_feed_generation_card", public_card)
    return path


@pytest.mark.asyncio
async def test_vk_feed_like_once_per_platform_identity(native_feed_db):
    assert await like_public_vk_feed(2001, 41) == 4
    assert await like_public_vk_feed(2001, 41) == 4
    assert await like_public_vk_feed(2002, 41) == 5
    with sqlite3.connect(native_feed_db) as db:
        assert db.execute("SELECT likes_count FROM generation_tasks WHERE id=41").fetchone()[0] == 5
        assert db.execute(
            "SELECT count(*) FROM vk_feed_generation_likes WHERE generation_task_id=41",
        ).fetchone()[0] == 2
        # No Telegram users table is even present: a native actor cannot
        # accidentally use a fake TG identity for this operation.
        assert db.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone() is None


@pytest.mark.asyncio
async def test_vk_feed_like_concurrent_retries_update_counter_exactly_once(native_feed_db):
    totals = await asyncio.gather(*(like_public_vk_feed(2099, 41) for _ in range(4)))
    assert all(value in {4} for value in totals)
    with sqlite3.connect(native_feed_db) as db:
        assert db.execute("SELECT likes_count FROM generation_tasks WHERE id=41").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM vk_feed_generation_likes").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_vk_feed_like_many_simultaneous_actors_keep_independent_reactions(native_feed_db):
    """Regression: SQLite WAL initialization must not race before busy_timeout."""
    actors = [2090, 2091, 2092, 2093, 2094]
    # Each actor has several concurrent retries. Every DB open must finish,
    # every unique actor should increment exactly once and no worker thread
    # may remain blocked by a failed PRAGMA journal_mode change.
    requests = [like_public_vk_feed(actor, 41) for actor in actors for _ in range(5)]
    totals = await asyncio.wait_for(asyncio.gather(*requests), timeout=8)
    assert all(type(total) is int and 4 <= total <= 8 for total in totals)
    with sqlite3.connect(native_feed_db) as conn:
        assert conn.execute("SELECT likes_count FROM generation_tasks WHERE id=41").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM vk_feed_generation_likes").fetchone()[0] == 5


@pytest.mark.asyncio
async def test_vk_likes_fail_closed_for_unpublished_or_adult_source(native_feed_db):
    assert await like_public_vk_feed(2001, 42) is None
    assert await like_public_vk_feed(2001, 43) is None
    with sqlite3.connect(native_feed_db) as db:
        assert db.execute("SELECT count(*) FROM vk_feed_generation_likes").fetchone()[0] == 0


@pytest.mark.parametrize("actor,gen", [
    (0, 41), (-1, 41), (True, 41), (2001, False),
    (2001, -1), (2001, 2**63), ("2001", 41),
])
@pytest.mark.asyncio
async def test_invalid_actor_or_feed_id_never_mutates(native_feed_db, actor, gen):
    with pytest.raises(ValueError):
        await like_public_vk_feed(actor, gen)
    with sqlite3.connect(native_feed_db) as db:
        assert db.execute("SELECT count(*) FROM vk_feed_generation_likes").fetchone()[0] == 0


def _request():
    return make_mocked_request("POST", "/mini-app/api/account-preview/vk-feed-like")


@pytest.mark.asyncio
async def test_signed_vk_http_like_uses_only_resolved_native_actor(monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_FEED_LIKES_ENABLED", "1")
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="shared-1",
        linked_platforms=("vk", "telegram"), linked_telegram_id=7001,
    )
    auth = AsyncMock(return_value=actor)
    like = AsyncMock(return_value=12)
    monkeypatch.setattr(api, "resolve_platform_actor", auth)
    monkeypatch.setattr(api, "_bearer", lambda request: "signed")
    monkeypatch.setattr(api, "_body", AsyncMock(return_value={"feed_gen_id": 41}))
    monkeypatch.setattr(api, "like_public_vk_feed", like)
    result = await api.vk_public_feed_like(_request())
    assert result.status == 200
    assert json.loads(result.text) == {"ok": True, "liked": True, "likes_count": 12}
    auth.assert_awaited_once_with("signed", expected_platform="vk")
    like.assert_awaited_once_with(2001, 41)


@pytest.mark.asyncio
async def test_vk_like_closed_flag_has_no_writes(monkeypatch):
    monkeypatch.delenv("VK_MINIAPP_FEED_LIKES_ENABLED", raising=False)
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="shared-1",
        linked_platforms=("vk",), linked_telegram_id=None,
    )
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(api, "_bearer", lambda request: "signed")
    like = AsyncMock(return_value=12)
    monkeypatch.setattr(api, "like_public_vk_feed", like)
    result = await api.vk_public_feed_like(_request())
    assert result.status == 404
    like.assert_not_awaited()


@pytest.mark.parametrize("gen_id", [True, 0, -1, "41"])
@pytest.mark.asyncio
async def test_vk_like_rejects_client_actor_or_malformed_id(monkeypatch, gen_id):
    monkeypatch.setenv("VK_MINIAPP_FEED_LIKES_ENABLED", "1")
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="shared-1",
        linked_platforms=("vk",), linked_telegram_id=None,
    )
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(api, "_bearer", lambda request: "signed")
    monkeypatch.setattr(api, "_body", AsyncMock(return_value={"feed_gen_id": gen_id}))
    monkeypatch.setattr(api, "like_public_vk_feed", AsyncMock())
    with pytest.raises(ValueError):
        await api.vk_public_feed_like(_request())
    api.like_public_vk_feed.assert_not_awaited()


def test_public_feed_like_flag_only_advertised_by_server(monkeypatch):
    card = {
        "id": 41, "gen_type": "image", "likes_count": 3,
        "shares_count": 0, "comments_count": 0, "result_url": "https://example.test/41.jpg",
    }
    monkeypatch.delenv("VK_MINIAPP_FEED_LIKES_ENABLED", raising=False)
    assert api._vk_public_feed_card(card, vk_app_id=123)["can_like_in_app"] is False
    monkeypatch.setenv("VK_MINIAPP_FEED_LIKES_ENABLED", "1")
    c = api._vk_public_feed_card(card, vk_app_id=123)
    assert c["can_like_in_app"] is True
    assert "prompt" not in c and "reference_images" not in c


@pytest.mark.asyncio
async def test_vk_feed_likes_sqlite_ddl_is_executed(monkeypatch):
    monkeypatch.setattr(database.db_backend, "is_postgres", lambda: False)
    conn = SimpleNamespace(execute=AsyncMock())
    await database._ensure_vk_feed_likes_schema(conn)
    statement = conn.execute.await_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS vk_feed_generation_likes" in statement
    assert "PRIMARY KEY (vk_user_id, generation_task_id)" in statement
    assert "REFERENCES generation_tasks (id) ON DELETE CASCADE" in statement
    assert "REFERENCES users" not in statement


@pytest.mark.asyncio
async def test_vk_feed_likes_postgres_migration_bypasses_sqlite_ddl_translation(monkeypatch):
    monkeypatch.setattr(database.db_backend, "is_postgres", lambda: True)
    conn = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("SQLite CREATE is skipped on PostgreSQL")),
        execute_native_ddl=AsyncMock(),
    )
    await database._ensure_vk_feed_likes_schema(conn)
    conn.execute.assert_not_awaited()
    statement = conn.execute_native_ddl.await_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS vk_feed_generation_likes" in statement
    assert "PRIMARY KEY (vk_user_id, generation_task_id)" in statement
    assert "REFERENCES generation_tasks (id) ON DELETE CASCADE" in statement
    assert "REFERENCES users" not in statement


def test_postgres_initial_bootstrap_includes_vk_feed_likes():
    schema = (Path(__file__).resolve().parents[1] / "schema_postgres.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS vk_feed_generation_likes" in schema
    assert "PRIMARY KEY (vk_user_id, generation_task_id)" in schema
    assert "REFERENCES generation_tasks(id) ON DELETE CASCADE" in schema
