"""Read-only task detail respects the verified cross-platform owner."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp, web_auth


def _flow(source=None):
    return {"mode": "link" if source else "login", "source": source, "destination": "/login"}


def _headers(session):
    return {"Cookie": "nm_web_session=" + session.cookies["nm_web_session"].value}


@pytest.mark.asyncio
async def test_task_detail_needs_session_and_rejects_external_owner_parameters(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    browser = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "detail-browser-only", _flow(),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/mini-app/api/web-auth/task?task_id=x")).status == 401
        for q in ("?task_id=x&telegram_id=1", "?task_id=x&account_id=other",
                  "?task_id=" + "a" * 260, "?task_id=%20", ""):
            reply = await client.get("/mini-app/api/web-auth/task" + q,
                                     headers=_headers(browser))
            assert reply.status == 400
        unaffiliated = await client.get("/mini-app/api/web-auth/task?task_id=private",
                                        headers=_headers(browser))
        assert unaffiliated.status == 404


@pytest.mark.asyncio
async def test_task_detail_only_returns_verified_linked_owner_rows(monkeypatch):
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    owner_id, foreign_id = 876555111, 876555199
    owner = await database.get_or_create_user(owner_id)
    stranger = await database.get_or_create_user(foreign_id)
    await database.add_generation_task(
        owner.id, owner_id, "detail-own-task-20261120",
        "image", "synthetic", model="nano_banana", prompt="Owner-only prompt",
    )
    await database.add_generation_task(
        stranger.id, foreign_id, "detail-foreign-task-20261120",
        "image", "synthetic", model="nano_banana", prompt="Secret foreign prompt",
    )
    login = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(owner_id), _flow(),
    )
    account_id = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": login.cookies["nm_web_session"].value,
    }))
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": login.cookies["nm_web_session"].value,
        }), "yandex", "detail-link-yandex", _flow(source=account_id),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        own = await client.get("/mini-app/api/web-auth/task?task_id=detail-own-task-20261120",
                               headers=_headers(linked))
        assert own.status == 200, await own.text()
        obj = await own.json()
        assert obj["task"]["task_id"] == "detail-own-task-20261120"
        assert obj["task"]["prompt"] == "Owner-only prompt"
        assert obj["scope"] == "legacy_telegram"
        foreign = await client.get("/mini-app/api/web-auth/task?task_id=detail-foreign-task-20261120",
                                   headers=_headers(linked))
        assert foreign.status == 404
        assert "Secret foreign prompt" not in await foreign.text()


@pytest.mark.asyncio
async def test_task_detail_unlink_during_read_fails_closed(monkeypatch):
    from bot import db as db_backend

    owner_id = 876555211
    await database.get_or_create_user(owner_id)
    login = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(owner_id), _flow(),
    )
    cookie = login.cookies["nm_web_session"].value
    account_id = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
        "google", "detail-unlink-google", _flow(source=account_id),
    )

    async def unlink_during_load(*args, **kwargs):
        async with db_backend.connect() as db:
            await db.execute("DELETE FROM shared_account_identities "
                             "WHERE account_id=? AND platform='telegram'", (account_id,))
            await db.commit()
        return {"task_id": "previously-owned", "prompt": "top secret"}

    source = AsyncMock(side_effect=unlink_during_load)
    monkeypatch.setattr(miniapp, "_fetch_task_detail", source)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.get("/mini-app/api/web-auth/task?task_id=previously-owned",
                                  headers=_headers(linked))
        assert result.status in (401, 403)
        assert "top secret" not in await result.text()


@pytest.mark.asyncio
async def test_task_detail_private_recipe_runs_native_sanitizer(monkeypatch):
    tg_id = 876555411
    await database.get_or_create_user(tg_id)
    login = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(tg_id), _flow(),
    )
    source = AsyncMock(return_value={
        "task_id": "hidden-owned-recipe",
        "prompt": "sensitive private recipe",
        "request_data": {"source_reference_url": "https://private.example/file"},
        "status": "completed",
    })
    monkeypatch.setattr(miniapp, "_fetch_task_detail", source)
    from bot import trend_task_privacy
    sanitizer = AsyncMock(return_value={
        "ok": True, "task": {"task_id": "hidden-owned-recipe",
                             "prompt": "", "prompt_hidden": True},
    })
    monkeypatch.setattr(trend_task_privacy, "sanitize_task_api_payload", sanitizer)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.get("/mini-app/api/web-auth/task?task_id=hidden-owned-recipe",
                                  headers=_headers(login))
        assert result.status == 200
        assert "sensitive private recipe" not in await result.text()
        assert "private.example" not in await result.text()
    sanitizer.assert_awaited_once()
    source.assert_awaited_once_with(tg_id, "hidden-owned-recipe")


@pytest.mark.asyncio
async def test_task_detail_logout_during_media_lookup_revokes_read(monkeypatch):
    from aiohttp.test_utils import make_mocked_request

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    tg_id = 876555477
    await database.get_or_create_user(tg_id)
    signed = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(tg_id), _flow(),
    )

    async def logout_during_fetch(*args, **kwargs):
        request = make_mocked_request(
            "POST", "/mini-app/api/web-auth/logout",
            headers={
                **_headers(signed),
                "Origin": "https://neuromixbot.com",
            },
        )
        assert (await web_auth.logout(request)).status == 200
        return {"task_id": "revoked-owned-media", "prompt": "Must never leak"}

    monkeypatch.setattr(
        miniapp, "_fetch_task_detail",
        AsyncMock(side_effect=logout_during_fetch),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        reply = await client.get(
            "/mini-app/api/web-auth/task?task_id=revoked-owned-media",
            headers=_headers(signed),
        )
        assert reply.status == 401
        assert "Must never leak" not in await reply.text()
