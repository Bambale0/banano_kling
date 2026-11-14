"""VK #451: actor-neutral public feed comments, signed writes and idempotency."""
from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot.shared_accounts import api
from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.vk_feed_comments import (
    VkCommentConflict, VkCommentCooldown, create_public_vk_comment,
)

ACTOR = PlatformActor("vk", 2001, "independent-vk", ("vk",), None)


@pytest.fixture
def feed_db(tmp_path, monkeypatch):
    location = str(tmp_path / "native-vk-comments.db")
    monkeypatch.setattr(database, "DATABASE_PATH", location)
    with sqlite3.connect(location) as conn:
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE generation_tasks (
                id INTEGER PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL,
                result_url TEXT, is_public_feed INTEGER, is_adult_content INTEGER
            );
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, telegram_id INTEGER,
                username TEXT, first_name TEXT, last_name TEXT, referral_code TEXT
            );
            CREATE TABLE feed_comments (
                id INTEGER PRIMARY KEY, generation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL, text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO users VALUES (31, 481, 'tg_name', 'Telegram', NULL, 'PROMO');
            INSERT INTO generation_tasks VALUES (41,'image','completed','https://example.test/41.jpg',1,0);
            INSERT INTO generation_tasks VALUES (42,'image','completed','https://example.test/42.jpg',0,0);
            INSERT INTO generation_tasks VALUES (43,'video','completed','https://example.test/43.mp4',1,1);
            INSERT INTO feed_comments (id,generation_id,user_id,text) VALUES (7,41,31,'С Telegram');
            CREATE TABLE vk_feed_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id BIGINT NOT NULL REFERENCES generation_tasks(id) ON DELETE CASCADE,
                vk_user_id BIGINT NOT NULL,
                text TEXT NOT NULL,
                client_request_id TEXT NOT NULL,
                cooldown_bucket BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (vk_user_id, client_request_id),
                UNIQUE (vk_user_id, cooldown_bucket)
            );
        """)
    async def public_card(gen_id, *, viewer_user_id=None, include_unavailable=False):
        assert viewer_user_id is None
        return {"id": gen_id, "publication_scope": "feed"} if gen_id == 41 else None
    monkeypatch.setattr(database, "get_feed_generation_card", public_card)
    return location


@pytest.mark.asyncio
async def test_native_vk_comment_is_visible_in_both_legacy_and_native_feed_without_tg_identity(feed_db, monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS", "10")
    first = await create_public_vk_comment(2001, 41, "  Привет   из VK ", "vk_comment_create_000000001")
    assert first is not None and first["comment"]["id"].startswith("vk:")
    assert first["comment"]["text"] == "Привет из VK"
    assert first["comment"]["is_mine"] is True
    assert first["comments_count"] == 2
    second = await create_public_vk_comment(2001, 41, "Привет из VK", "vk_comment_create_000000001")
    assert second == first
    native = await database.get_feed_comments(41, viewer_vk_user_id=2001)
    assert len(native) == 2
    assert any(c["text"] == "С Telegram" and c["id"] == 7 and c["is_mine"] is False for c in native)
    assert any(c["text"] == "Привет из VK" and c["id"] == first["comment"]["id"]
               and c["is_mine"] is True for c in native)
    legacy = await database.get_feed_comments(41, viewer_user_id=31)
    assert any(c["text"] == "С Telegram" and c["is_mine"] is True for c in legacy)
    vk = next(c for c in legacy if c["text"] == "Привет из VK")
    assert vk["is_mine"] is False
    assert vk["author_referral_code"] is None
    assert "telegram_id" not in vk and "vk_user_id" not in vk
    with sqlite3.connect(feed_db) as db:
        assert db.execute("SELECT count(*) FROM vk_feed_comments").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_vk_comment_idempotency_under_concurrent_network_retry(feed_db):
    key = "vk_comment_parallel_000001"
    results = await asyncio.gather(*(create_public_vk_comment(2001, 41, "Один", key) for _ in range(4)))
    assert all(result == results[0] for result in results)
    with sqlite3.connect(feed_db) as db:
        assert db.execute("SELECT COUNT(*) FROM vk_feed_comments").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_vk_comment_idempotency_key_cannot_be_rebound_to_another_body(feed_db):
    key = "vk_comment_replay_000000001"
    await create_public_vk_comment(2001, 41, "Старый текст", key)
    with pytest.raises(VkCommentConflict):
        await create_public_vk_comment(2001, 41, "Изменённый текст", key)


@pytest.mark.asyncio
async def test_vk_comment_atomic_per_actor_bucket_spam_limit(feed_db, monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS", "60")
    await create_public_vk_comment(2001, 41, "Один", "vk_comment_rate_00000000001")
    with pytest.raises(VkCommentCooldown):
        await create_public_vk_comment(2001, 41, "Два", "vk_comment_rate_00000000002")
    # Two independent VK actors may comment in the same bucket.
    other = await create_public_vk_comment(2002, 41, "Другой", "vk_comment_rate_00000000003")
    assert other["comments_count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("id", [42, 43, 99])
async def test_vk_comment_rejects_private_adult_or_unknown_feed(feed_db, id):
    assert await create_public_vk_comment(2001, id, "Текст", "vk_comment_hidden_00000001") is None
    with sqlite3.connect(feed_db) as db:
        assert db.execute("SELECT COUNT(*) FROM vk_feed_comments").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,id,text,key", [
    (False, 41, "text", "vk_comment_bad_000000001"),
    (2001, False, "text", "vk_comment_bad_000000001"),
    (2001, 41, " ", "vk_comment_bad_000000001"),
    (2001, 41, "x" * 501, "vk_comment_bad_000000001"),
    (2001, 41, 101, "vk_comment_bad_000000001"),
    (2001, 41, "text", "tiny"),
    (2001, 41, "text", "non safe key spaces"),
])
async def test_malformed_native_vk_comments_fail_before_mutation(feed_db, actor, id, text, key):
    with pytest.raises((ValueError, TypeError)):
        await create_public_vk_comment(actor, id, text, key)
    with sqlite3.connect(feed_db) as db:
        assert db.execute("SELECT COUNT(*) FROM vk_feed_comments").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_native_vk_comment_http_uses_signed_owner_and_flag_off_fail_closed(feed_db, monkeypatch):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=type("P", (), {"enabled": True})()))
    signed = AsyncMock(return_value=ACTOR)
    monkeypatch.setattr(api, "resolve_platform_actor", signed)
    app = web.Application()
    app.router.add_post("/mini-app/api/account-preview/vk-feed-comment", api._guard(api.vk_public_feed_comment_add))
    async with TestClient(TestServer(app)) as client:
        payload = {"feed_gen_id": 41, "text": "Привет", "client_request_id": "vk_comment_web_0000000001"}
        disabled = await client.post("/mini-app/api/account-preview/vk-feed-comment", json=payload)
        assert disabled.status == 404
        monkeypatch.setenv("VK_MINIAPP_FEED_COMMENTS_ENABLED", "1")
        response = await client.post("/mini-app/api/account-preview/vk-feed-comment",
                                     json=payload, headers={"Authorization": "Bearer scoped"})
        assert response.status == 200
        posted = await response.json()
        assert posted["comment"]["id"].startswith("vk:")
        assert "user_id" not in json.dumps(posted) and posted["comment"]["author_referral_code"] is None
        signed.assert_awaited_with("scoped", expected_platform="vk")
        # A frontend cannot choose another owner, even if the bearer is valid.
        forged = await client.post("/mini-app/api/account-preview/vk-feed-comment",
                                   json={**payload, "vk_user_id": 2002},
                                   headers={"Authorization": "Bearer scoped"})
        assert forged.status == 400


def test_native_vk_comments_schema_supports_postgres_migration_and_bootstrap():
    source = inspect.getsource(database._ensure_vk_feed_comments_schema)
    schema = (Path(database.__file__).parents[1] / "schema_postgres.sql").read_text()
    assert "execute_native_ddl" in source
    assert "CREATE TABLE IF NOT EXISTS vk_feed_comments" in source
    assert "CREATE TABLE IF NOT EXISTS vk_feed_comments" in schema
    assert "ON DELETE CASCADE" in source
    assert "UNIQUE (vk_user_id, client_request_id)" in source
    assert "UNIQUE (vk_user_id, cooldown_bucket)" in source

@pytest.mark.asyncio
async def test_vk_native_comments_sqlite_migration_is_idempotent_and_cascades(tmp_path, monkeypatch):
    from bot import db as backend
    location = str(tmp_path / "schema.db")
    with sqlite3.connect(location) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE generation_tasks (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO generation_tasks(id) VALUES(41)")
        db.commit()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    async with backend.connect(location) as db:
        await database._ensure_vk_feed_comments_schema(db)
        await database._ensure_vk_feed_comments_schema(db)
        await db.execute(
            "INSERT INTO vk_feed_comments"
            "(generation_id,vk_user_id,text,client_request_id,cooldown_bucket)"
            "VALUES(41,2001,'Hello','vk_comment_schema_00000001',100)")
        await db.commit()
        await db.execute("DELETE FROM generation_tasks WHERE id=41")
        left = await (await db.execute("SELECT count(*) FROM vk_feed_comments")).fetchone()
        assert left[0] == 0
        await db.commit()


@pytest.mark.asyncio
async def test_disabled_vk_comment_http_does_not_call_native_write(feed_db, monkeypatch):
    monkeypatch.delenv("VK_MINIAPP_FEED_COMMENTS_ENABLED", raising=False)
    write = AsyncMock()
    monkeypatch.setattr(api, "create_public_vk_comment", write)
    app = web.Application()
    app.router.add_post("/mini-app/api/account-preview/vk-feed-comment", api._guard(api.vk_public_feed_comment_add))
    async with TestClient(TestServer(app)) as client:
        result = await client.post("/mini-app/api/account-preview/vk-feed-comment", json={
            "feed_gen_id": 41, "text": "No publish", "client_request_id": "vk_comment_disabled_00000001"
        })
        assert result.status == 404
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_vk_comment_http_rejects_spam_and_replays_same_accepted_write(feed_db, monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_FEED_COMMENTS_ENABLED", "1")
    monkeypatch.setenv("VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS", "60")
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=type("P", (), {"enabled": True})()))
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=ACTOR))
    app = web.Application()
    app.router.add_post("/mini-app/api/account-preview/vk-feed-comment", api._guard(api.vk_public_feed_comment_add))
    path = "/mini-app/api/account-preview/vk-feed-comment"
    headers = {"Authorization": "Bearer scoped"}
    first = {"feed_gen_id": 41, "text": "Hello", "client_request_id": "vk_comment_http_rate_000001"}
    async with TestClient(TestServer(app)) as client:
        response = await client.post(path, json=first, headers=headers)
        assert response.status == 200
        data = await response.json()
        assert (await client.post(path, json=first, headers=headers)).status == 200
        too_quick = await client.post(path, json={
            **first, "client_request_id": "vk_comment_http_rate_000002"
        }, headers=headers)
        assert too_quick.status == 429
        assert (await too_quick.json())["error_code"] == "comment_rate_limited"
        conflict = await client.post(path, json={**first, "text": "Changed"}, headers=headers)
        assert conflict.status == 409
        assert (await conflict.json())["error_code"] == "comment_replay_conflict"
        assert data["comments_count"] == 2


@pytest.mark.asyncio
async def test_native_vk_comment_invalid_cooldown_config_prevents_writes(feed_db, monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_FEED_COMMENT_COOLDOWN_SECONDS", "bad")
    with pytest.raises(RuntimeError):
        await create_public_vk_comment(2001, 41, "Test", "vk_comment_invalid_config_000001")
    with sqlite3.connect(feed_db) as db:
        assert db.execute("SELECT count(*) FROM vk_feed_comments").fetchone()[0] == 0
