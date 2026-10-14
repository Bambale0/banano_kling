"""HTTP regression checks for the editorial trends catalog."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot.browser_auth import trend_prompt_privacy_middleware
from bot.trend_catalog_api import setup_trend_catalog_routes
from tests.test_trend_referral_links import signed_init_data


@pytest.fixture
async def catalog_client():
    app = web.Application(middlewares=[trend_prompt_privacy_middleware])
    app["trend_prompt_privacy_root"] = "/mini-app"
    app["bot"] = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))
    )
    setup_trend_catalog_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        yield client


async def make_trend():
    user = await database.get_or_create_user(999999999)
    obj = await database.create_prompt(
        author_id=user.id,
        title="Свечи",
        description="День рождения",
        prompt_text="Private scene of a cake with 37 golden candles",
        model="banana_pro",
        category="photo",
        is_public=True,
        tags=["trend"],
        generation_settings={
            "kind": "image",
            "user_fields": [
                {"key": "Возраст", "label": "Возраст", "original_value": "37"}
            ],
        },
    )
    return await database.approve_prompt(obj["id"])


@pytest.mark.asyncio
async def test_catalog_viewer_privacy_and_admin_access(catalog_client):
    await make_trend()
    denied = await catalog_client.post("/mini-app/api/trends/catalog", json={})
    assert denied.status in {400, 401, 403}

    user = signed_init_data(8311001)
    denied_admin = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={"init_data": user, "op": "create", "title": "Secret", "emoji": "🎂"},
    )
    assert denied_admin.status == 403

    visible = await catalog_client.post(
        "/mini-app/api/trends/catalog", json={"init_data": user}
    )
    assert visible.status == 200
    catalog = (await visible.json())["categories"]
    assert catalog[0]["id"] == "unassigned"
    card = catalog[0]["items"][0]
    assert card["prompt_text"] == ""
    assert card["model"] is None
    assert "Private scene" not in str(catalog)
    assert "original_value" not in str(catalog)
    assert visible.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_admin_create_hide_conflict_and_delete_preserves_trend(catalog_client):
    prompt = await make_trend()
    admin = signed_init_data(999999999)
    viewer = signed_init_data(8311002)

    create = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={
            "init_data": admin,
            "op": "create",
            "title": "День рождения",
            "emoji": "🎂",
        },
    )
    assert create.status == 200, await create.text()
    category = (await create.json())["result"]

    assign = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={
            "init_data": admin,
            "op": "set_trend_categories",
            "trend_id": prompt["id"],
            "category_ids": [category["id"]],
        },
    )
    assert assign.status == 200
    result = await catalog_client.post(
        "/mini-app/api/trends/catalog", json={"init_data": viewer}
    )
    current = (await result.json())["categories"][0]
    assert current["items"][0]["id"] == prompt["id"]

    hide = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={
            "init_data": admin,
            "op": "update",
            "category_id": category["id"],
            "revision": current["revision"],
            "is_visible": False,
        },
    )
    assert hide.status == 200, await hide.text()
    hidden = (await hide.json())["result"]
    result = await catalog_client.post(
        "/mini-app/api/trends/catalog", json={"init_data": viewer}
    )
    assert (await result.json())["categories"] == []
    direct = await catalog_client.post(
        "/mini-app/api/trends/category",
        json={"init_data": viewer, "category_id": category["id"]},
    )
    assert direct.status == 404
    stale = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={
            "init_data": admin,
            "op": "update",
            "category_id": category["id"],
            "revision": category["revision"],
            "is_visible": True,
        },
    )
    assert stale.status == 409

    delete = await catalog_client.post(
        "/mini-app/api/admin/trends/categories",
        json={
            "init_data": admin,
            "op": "delete",
            "category_id": category["id"],
            "revision": hidden["revision"],
        },
    )
    assert delete.status == 200
    result = await catalog_client.post(
        "/mini-app/api/trends/catalog", json={"init_data": viewer}
    )
    assert (await result.json())["categories"][0]["items"][0]["id"] == prompt["id"]


@pytest.mark.asyncio
async def test_legacy_api_sanitizes_viewer_response_even_with_valid_auth():
    item = await make_trend()
    app = web.Application(middlewares=[trend_prompt_privacy_middleware])
    app["trend_prompt_privacy_root"] = "/mini-app"

    async def raw(_request):
        return web.json_response(
            {"ok": True, "prompt": await database.get_prompt_by_id(item["id"])}
        )

    app.router.add_get("/api/v1/prompts/1", raw)
    async with TestClient(TestServer(app)) as client:
        response = await client.get(
            "/api/v1/prompts/1",
            headers={"X-Telegram-Init-Data": signed_init_data(8311003)},
        )
        assert response.status == 200
        data = (await response.json())["prompt"]
        assert data["prompt_text"] == ""
        assert data["model"] is None
        assert "original_value" not in str(data)


@pytest.fixture(autouse=True)
async def isolated_trend_metrics_database(isolated_database, monkeypatch):
    """Avoid frozen legacy metrics DB paths when the whole suite is collected.

    Global handler installers run during collection of other modules; each
    catalog test receives its own SQLite database via isolated_database.
    """
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)


@pytest.mark.asyncio
async def test_required_channel_denial_is_actionable_for_catalog(
    catalog_client, monkeypatch
):
    from bot import trend_catalog_api

    async def no_subscription(request, payload):
        raise PermissionError(
            "Подпишитесь на @fixture_channel, чтобы пользоваться ботом."
        )

    monkeypatch.setattr(trend_catalog_api, "_context", no_subscription)
    response = await catalog_client.post(
        "/mini-app/api/trends/catalog",
        json={"init_data": signed_init_data(8311099)},
    )
    assert response.status == 403
    body = await response.json()
    assert body["code"] == "catalog_auth_error"
    assert "@fixture_channel" in body["error"]


@pytest.mark.asyncio
async def test_legacy_get_preserves_signed_admin_prompt_but_redacts_viewer():
    item = await make_trend()
    app = web.Application(middlewares=[trend_prompt_privacy_middleware])
    app["trend_prompt_privacy_root"] = "/mini-app"

    async def raw(_request):
        return web.json_response(
            {"ok": True, "prompt": await database.get_prompt_by_id(item["id"])}
        )

    app.router.add_get("/api/v1/prompts/1", raw)
    async with TestClient(TestServer(app)) as client:
        admin = await client.get(
            "/api/v1/prompts/1",
            headers={"X-Telegram-Init-Data": signed_init_data(999999999)},
        )
        assert admin.status == 200
        assert (await admin.json())["prompt"]["prompt_text"].startswith("Private scene")
        viewer = await client.get(
            "/api/v1/prompts/1",
            headers={"X-Telegram-Init-Data": signed_init_data(8311098)},
        )
        assert viewer.status == 200
        assert (await viewer.json())["prompt"]["prompt_text"] == ""
