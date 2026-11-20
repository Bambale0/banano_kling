"""Read-only cross-platform history must honor a verified shared account link."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp, web_auth


def _cookies(response):
    return {"Cookie": "nm_web_session=" + response.cookies["nm_web_session"].value}


def _flow(*, source=None):
    return {
        "mode": "link" if source else "login",
        "source": source, "destination": "/login",
    }


@pytest.mark.asyncio
async def test_browser_history_anonymous_and_web_only_cannot_read_legacy_tasks(monkeypatch):
    source = AsyncMock(side_effect=AssertionError("Telegram history must not be queried"))
    monkeypatch.setattr(miniapp, "_fetch_recent_tasks", source)
    account = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "history-web-only-2026", _flow(),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.get("/mini-app/api/web-auth/history")
        assert anonymous.status == 401
        verified = await client.get("/mini-app/api/web-auth/history",
                                    headers=_cookies(account))
        assert verified.status == 200, await verified.text()
        payload = await verified.json()
        assert payload == {
            "ok": True, "scope": "web_only", "recent_tasks": [],
            "next_cursor": None, "cursor_reset": False,
        }
    source.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_telegram_link_reads_only_its_legacy_history_and_sanitizes(monkeypatch):
    telegram_id = 876545501
    other_id = 876545599
    await database.get_or_create_user(telegram_id)
    await database.get_or_create_user(other_id)
    telegram_account = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(telegram_id), _flow(),
    )
    account_id = await web_auth._session_account(
        SimpleNamespace(cookies={
            "nm_web_session": telegram_account.cookies["nm_web_session"].value,
        }),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": telegram_account.cookies["nm_web_session"].value,
        }), "google", "google-history-owner-2026", _flow(source=account_id),
    )
    own_task = {"task_id": "own_" + "a" * 32, "status": "completed",
                "prompt_preview": "private prompt"}
    source = AsyncMock(return_value=[own_task])
    monkeypatch.setattr(miniapp, "_fetch_recent_tasks", source)

    from bot import trend_task_privacy
    sanitize = AsyncMock(side_effect=lambda payload: {
        **payload,
        "recent_tasks": [
            {**task, "prompt_preview": "[redacted]"}
            for task in payload["recent_tasks"]
        ],
    })
    monkeypatch.setattr(trend_task_privacy, "sanitize_task_api_payload", sanitize)

    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/mini-app/api/web-auth/history",
                                    headers=_cookies(linked))
        assert response.status == 200, await response.text()
        data = await response.json()
        assert data["scope"] == "legacy_telegram"
        assert data["recent_tasks"][0]["task_id"] == own_task["task_id"]
        assert data["recent_tasks"][0]["prompt_preview"] == "[redacted]"
        assert data["next_cursor"] is None
    source.assert_awaited_once_with(telegram_id, limit=9, before_task_id=None)
    sanitize.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_rejects_query_account_id_and_revoke_cookie(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    source = AsyncMock(side_effect=AssertionError("untrusted account ID"))
    monkeypatch.setattr(miniapp, "_fetch_recent_tasks", source)
    original = await web_auth._complete_identity(
        SimpleNamespace(), "email", "history-foreign@example.org", _flow(),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        injection = await client.get(
            "/mini-app/api/web-auth/history?telegram_id=876545501",
            headers=_cookies(original),
        )
        assert injection.status == 400
        signed = await client.get(
            "/mini-app/api/web-auth/history?account_id=0" + "a" * 32,
            headers=_cookies(original),
        )
        assert signed.status == 400
        logout = await client.post(
            "/mini-app/api/web-auth/logout",
            headers={**_cookies(original), "Origin": "https://neuromixbot.com"},
        )
        assert logout.status == 200
        stale = await client.get("/mini-app/api/web-auth/history",
                                 headers=_cookies(original))
        assert stale.status == 401
    source.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_cursor_remains_owner_scoped_and_bounded(monkeypatch):
    telegram_id = 876545511
    await database.get_or_create_user(telegram_id)
    signed = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(telegram_id), _flow(),
    )
    account_id = await web_auth._session_account(
        SimpleNamespace(cookies={
            "nm_web_session": signed.cookies["nm_web_session"].value,
        }),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": signed.cookies["nm_web_session"].value,
        }), "yandex", "history-linked-cursor-2026", _flow(source=account_id),
    )
    source = AsyncMock(side_effect=miniapp.TaskHistoryCursorError("Unknown cursor"))
    monkeypatch.setattr(miniapp, "_fetch_recent_tasks", source)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        too_long = await client.get(
            "/mini-app/api/web-auth/history?cursor=" + "X" * 257,
            headers=_cookies(linked),
        )
        assert too_long.status == 400
        # A stale or cross-owner cursor never fetches somebody else's task:
        # it is resolved under the verified Telegram ID only.
        from bot import miniapp as m
        source.side_effect = [
            m.TaskHistoryCursorError("foreign cursor"),
            [{"task_id": "own_" + "c" * 32, "status": "completed"}],
        ]
        response = await client.get("/mini-app/api/web-auth/history?cursor=foreign-1",
                                    headers=_cookies(linked))
        assert response.status == 200, await response.text()
        data = await response.json()
        assert data["cursor_reset"] is True
        assert source.await_args_list[0].args[0] == telegram_id
        assert source.await_args_list[-1].args[0] == telegram_id
        assert data["recent_tasks"][0]["task_id"] == "own_" + "c" * 32


@pytest.mark.asyncio
async def test_real_legacy_task_rows_are_visible_only_after_verified_telegram_link(monkeypatch):
    # Match existing native Mini App history regression's isolated test DB,
    # not production-configured DATABASE_PATH in a read-only container.
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    owner_tg, foreign_tg = 876545721, 876545799
    owner_user = await database.get_or_create_user(owner_tg)
    foreign_user = await database.get_or_create_user(foreign_tg)
    await database.add_generation_task(
        owner_user.id, owner_tg, "linked-web-own-task-20261120",
        "video", "synthetic", model="seedance_2_5", prompt="My own video",
    )
    await database.add_generation_task(
        foreign_user.id, foreign_tg, "linked-web-foreign-task-20261120",
        "video", "synthetic", model="seedance_2_5", prompt="Another user's video",
    )
    telegram = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(owner_tg), _flow(),
    )
    account = await web_auth._session_account(
        SimpleNamespace(cookies={
            "nm_web_session": telegram.cookies["nm_web_session"].value,
        }),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": telegram.cookies["nm_web_session"].value,
        }), "yandex", "legacy-history-owning-yandex", _flow(source=account),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/mini-app/api/web-auth/history",
                                    headers=_cookies(linked))
        assert response.status == 200, await response.text()
        data = await response.json()
        ids = [task["task_id"] for task in data["recent_tasks"]]
        assert "linked-web-own-task-20261120" in ids
        assert "linked-web-foreign-task-20261120" not in ids
        assert data["scope"] == "legacy_telegram"

        # A verified Telegram unlink must revoke legacy-history access even
        # if a stale legacy-links row still exists.
        from bot import db as db_backend
        async with db_backend.connect() as db:
            await db.execute(
                "DELETE FROM shared_account_identities WHERE account_id=? "
                "AND platform='telegram'", (account,),
            )
            await db.commit()
        after = await client.get("/mini-app/api/web-auth/history",
                                 headers=_cookies(linked))
        assert after.status == 200
        limited = await after.json()
        assert limited["scope"] == "web_only"
        assert limited["recent_tasks"] == []


@pytest.mark.asyncio
async def test_logout_during_task_read_never_returns_private_history(monkeypatch):
    import time

    from bot import db as db_backend

    telegram_id = 876545811
    await database.get_or_create_user(telegram_id)
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(telegram_id), _flow(),
    )
    account = await web_auth._session_account(
        SimpleNamespace(cookies={
            "nm_web_session": owner.cookies["nm_web_session"].value,
        }),
    )
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": owner.cookies["nm_web_session"].value,
        }), "yandex", "history-revocation-race-2026", _flow(source=account),
    )
    cookie = linked.cookies["nm_web_session"].value

    async def revoke_before_history_result(*args, **kwargs):
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_auth_sessions SET revoked_at_epoch=? "
                "WHERE token_hash=?", (int(time.time()), web_auth._digest(cookie)),
            )
            await db.commit()
        return [{"task_id": "sensitive-hidden-history", "status": "completed"}]

    monkeypatch.setattr(miniapp, "_fetch_recent_tasks",
                        AsyncMock(side_effect=revoke_before_history_result))
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/mini-app/api/web-auth/history", headers={
            "Cookie": "nm_web_session=" + cookie,
        })
        assert response.status == 401
        assert "sensitive-hidden-history" not in await response.text()


@pytest.mark.asyncio
async def test_unlink_during_task_read_never_returns_prior_telegram_history(monkeypatch):
    from bot import db as db_backend

    telegram_id = 876545832
    await database.get_or_create_user(telegram_id)
    owner = await web_auth._complete_identity(
        SimpleNamespace(), "telegram", str(telegram_id), _flow(),
    )
    account = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": owner.cookies["nm_web_session"].value,
    }))
    linked = await web_auth._complete_identity(
        SimpleNamespace(cookies={
            "nm_web_session": owner.cookies["nm_web_session"].value,
        }),
        "google", "history-unlink-race-2026", _flow(source=account),
    )

    async def unlink_before_history_result(*args, **kwargs):
        async with db_backend.connect() as db:
            await db.execute(
                "DELETE FROM shared_account_identities WHERE account_id=? "
                "AND platform='telegram'", (account,),
            )
            await db.commit()
        return [{"task_id": "old-telegram-sensitive", "status": "completed"}]

    monkeypatch.setattr(
        miniapp, "_fetch_recent_tasks",
        AsyncMock(side_effect=unlink_before_history_result),
    )
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/mini-app/api/web-auth/history",
            headers=_cookies(linked),
        )
        assert response.status in (401, 403)
        assert "old-telegram-sensitive" not in await response.text()
