"""Owned Studio history beyond bootstrap, using signed HTTP and synthetic DB."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp
from bot.config import config


def signed(telegram_id):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": telegram_id})}
    key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def seed_tasks(monkeypatch, count=19):
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    owner = await database.get_or_create_user(971285001)
    other = await database.get_or_create_user(971285002)
    for index in range(count):
        await database.add_generation_task(
            owner.id, owner.telegram_id, f"history-{index:02}", "video", "synthetic",
            model="seedance_2_5", prompt=f"Own video {index}",
            request_data={"reference_images": ["https://example.test/own-face.jpg"]},
        )
    await database.add_generation_task(other.id, other.telegram_id, "foreign-task", "video", "synthetic", model="wan_3")
    await database.add_generation_task(owner.id, owner.telegram_id, "dedicated-genjutsu", "video", "synthetic", model="genjutsu")
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        # Same timestamp exercises the stable tie-break; no sleeps or clock races.
        await db.execute("UPDATE generation_tasks SET created_at = ?", ("2026-10-21 10:00:00",))
        await db.commit()
    return owner, other


@pytest.mark.asyncio
async def test_signed_history_reaches_every_video_beyond_eight_and_ignores_forged_owner(monkeypatch):
    owner, other = await seed_tasks(monkeypatch)
    app = web.Application()
    app.router.add_post("/history", miniapp.miniapp_task_history)
    initial = await miniapp._fetch_recent_tasks(owner.telegram_id)
    assert len(initial) == 8
    assert initial[0]["task_id"] == "history-18"
    seen = [item["task_id"] for item in initial]
    cursor = seen[-1]
    # New rows at the head do not shift the anchored older page.
    await database.add_generation_task(owner.id, owner.telegram_id, "newly-created", "video", "synthetic", model="wan_3")
    async with TestClient(TestServer(app)) as client:
        while cursor:
            response = await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": cursor, "telegram_id": other.telegram_id, "user_id": other.id})
            assert response.status == 200, await response.text()
            assert response.headers.get("Cache-Control") == "no-store"
            page = await response.json()
            assert len(page["recent_tasks"]) <= 8
            seen.extend(item["task_id"] for item in page["recent_tasks"])
            cursor = page["next_cursor"]
    assert seen == [f"history-{i:02}" for i in reversed(range(19))]


@pytest.mark.asyncio
async def test_old_bot_publication_reopens_with_own_reference_settings(monkeypatch):
    owner, _ = await seed_tasks(monkeypatch, count=12)
    await database.complete_video_task("history-00", "https://example.test/own-result.mp4")
    published = await database.share_to_feed("history-00", owner.id, references_visible=False)
    assert published is not None
    app = web.Application()
    app.router.add_post("/history", miniapp.miniapp_task_history)
    app.router.add_post("/detail", miniapp.miniapp_task_detail)
    async with TestClient(TestServer(app)) as client:
        initial = await miniapp._fetch_recent_tasks(owner.telegram_id)
        response = await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": initial[-1]["task_id"]})
        assert response.status == 200
        assert "history-00" in [item["task_id"] for item in (await response.json())["recent_tasks"]]
        detail = await client.post("/detail", json={"init_data": signed(owner.telegram_id), "task_id": "history-00"})
        assert detail.status == 200
        task = (await detail.json())["task"]
        assert task["is_public_feed"] is True
        assert task["publication_reference_images"] == ["https://example.test/own-face.jpg"]


@pytest.mark.asyncio
async def test_history_rejects_invalid_auth_foreign_and_malformed_cursors(monkeypatch):
    owner, _ = await seed_tasks(monkeypatch)
    app = web.Application()
    app.router.add_post("/history", miniapp.miniapp_task_history)
    async with TestClient(TestServer(app)) as client:
        assert (await client.post("/history", json={"init_data": "forged"})).status == 401
        for cursor in ["foreign-task", "missing-task", "dedicated-genjutsu"]:
            response = await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": cursor})
            assert response.status == 200
            page = await response.json()
            assert page["cursor_reset"] is True
            assert [item["task_id"] for item in page["recent_tasks"]] == [f"history-{i:02}" for i in range(18, 10, -1)]
        for cursor in [[], {}, True]:
            response = await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": cursor})
            assert response.status == 400
        assert (await client.post("/history", json=[])).status == 400
        assert (await client.post("/history", data="[broken", headers={"Content-Type": "application/json"})).status == 400


@pytest.mark.asyncio
async def test_deleted_cursor_restarts_safely_and_private_recipe_stays_hidden(monkeypatch):
    owner, _ = await seed_tasks(monkeypatch)
    initial = await miniapp._fetch_recent_tasks(owner.telegram_id)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("DELETE FROM generation_tasks WHERE task_id = ?", (initial[-1]["task_id"],))
        await db.execute("UPDATE generation_tasks SET request_data = ? WHERE task_id = ?", (json.dumps({"private_recipe": True}), "history-00"))
        await db.commit()
    app = web.Application()
    app.router.add_post("/history", miniapp.miniapp_task_history)
    async with TestClient(TestServer(app)) as client:
        first = await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": initial[-1]["task_id"]})
        assert first.status == 200
        page = await first.json()
        assert page["cursor_reset"] is True
        cursor = page["next_cursor"]
        seen = page["recent_tasks"]
        while cursor:
            page = await (await client.post("/history", json={"init_data": signed(owner.telegram_id), "cursor": cursor})).json()
            seen.extend(page["recent_tasks"])
            cursor = page["next_cursor"]
    assert len({row["task_id"] for row in seen}) == 18
    private = next(row for row in seen if row["task_id"] == "history-00")
    assert private["prompt_hidden"] is True and private["prompt_preview"] == ""
