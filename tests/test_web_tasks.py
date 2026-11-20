"""Web-native history is isolated by a verified browser session, never Telegram ID."""
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import web_auth, web_tasks


def flow():
    return {"mode": "login", "source": None, "destination": "/login"}


async def signed_account(subject: str):
    redirect = await web_auth._complete_identity(SimpleNamespace(), "yandex", subject, flow())
    cookie = redirect.cookies["nm_web_session"].value
    account_id = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    return account_id, cookie


async def add_task(account_id: str, *, index: int, epoch: int, media_type="image",
                   result_url=None):
    task_id = "web_" + f"{index:032x}"
    await web_tasks.ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        await db.execute(
            """INSERT INTO web_generation_tasks
               (task_id,account_id,media_type,model,status,
                result_url,created_at_epoch,updated_at_epoch)
               VALUES (?,?,?,'test-model','completed',?,?,?)""",
            (task_id, account_id, media_type, result_url, epoch, epoch),
        )
        await db.commit()
    return task_id


@pytest.mark.asyncio
async def test_web_history_is_private_and_never_uses_telegram_identity():
    owner_id, owner_cookie = await signed_account("owner-yandex")
    stranger_id, stranger_cookie = await signed_account("stranger-yandex")
    task_id = await add_task(owner_id, index=7, epoch=1700000000,
                             result_url="https://cdn.example.com/web-result.png")
    await add_task(stranger_id, index=8, epoch=1700000000)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.get("/mini-app/api/web-auth/history")
        assert anonymous.status == 401
        result = await client.get(
            "/mini-app/api/web-auth/history", headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert result.status == 200
        payload = await result.json()
        assert payload["next_cursor"] is None
        assert [row["task_id"] for row in payload["recent_tasks"]] == [task_id]
        assert payload["recent_tasks"][0]["result_url"] == "https://cdn.example.com/web-result.png"
        own_detail = await client.get(
            "/mini-app/api/web-auth/task/" + task_id,
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert (await own_detail.json())["task"]["task_id"] == task_id
        stranger = await client.get(
            "/mini-app/api/web-auth/task/" + task_id,
            headers={"Cookie": f"nm_web_session={stranger_cookie}"},
        )
        assert stranger.status == 404
        invalid = await client.get(
            "/mini-app/api/web-auth/history?cursor=1%27%20OR%201%3D1",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert invalid.status == 400


@pytest.mark.asyncio
async def test_web_history_pagination_never_loses_equal_timestamp_tasks():
    owner_id, owner_cookie = await signed_account("history-cursor-owner")
    for number in range(1, 25):
        await add_task(owner_id, index=number, epoch=1800000000)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        first = await client.get(
            "/mini-app/api/web-auth/history",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        data = await first.json()
        assert len(data["recent_tasks"]) == 20
        assert data["next_cursor"]
        second = await client.get(
            "/mini-app/api/web-auth/history",
            params={"cursor": data["next_cursor"]},
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        data2 = await second.json()
        assert len(data2["recent_tasks"]) == 4
        combined = [row["task_id"] for row in data["recent_tasks"] + data2["recent_tasks"]]
        assert len(combined) == len(set(combined)) == 24
        assert data2["next_cursor"] is None


@pytest.mark.asyncio
async def test_web_result_history_never_leaks_unsafe_urls():
    owner_id, owner_cookie = await signed_account("untrusted-url-owner")
    await add_task(owner_id, index=2, epoch=1900000000,
                   result_url="javascript:alert(1)")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/mini-app/api/web-auth/history",
            headers={"Cookie": f"nm_web_session={owner_cookie}"},
        )
        assert (await response.json())["recent_tasks"][0]["result_url"] is None
