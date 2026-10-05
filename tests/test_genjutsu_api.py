"""Project metadata regressions at the authenticated Mini App HTTP boundary."""
import logging
from contextlib import asynccontextmanager
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.genjutsu.api import API
from bot.genjutsu.contract import PipelineError
from bot.genjutsu.pipeline import Pipeline
from bot.genjutsu.recipes import RecipeStore
from bot.genjutsu.repository import Repository


@pytest.fixture
async def project_api(tmp_path):
    path = tmp_path / "project-api.sqlite3"

    @asynccontextmanager
    async def connect():
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    async with connect() as db:
        await db.execute("CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, credits REAL NOT NULL)")
        await db.executemany("INSERT INTO users VALUES (?, ?)", [(101, 1000), (999, 1000)])
        await db.commit()
    repo = Repository(connect, clock=count(1_000_000).__next__)
    await repo.migrate()
    recipes = RecipeStore(repo)
    await recipes.migrate()
    media = SimpleNamespace(
        configured=False, url=Mock(side_effect=AssertionError("No signed URLs")),
        ensure_asset=AsyncMock(),
    )
    pipeline = Pipeline(repo, SimpleNamespace(configured=False), media)
    authenticate = AsyncMock(return_value=(101, False))
    app = web.Application()
    API(pipeline, authenticate, recipes=recipes).register(app)
    async with TestClient(TestServer(app)) as client:
        yield SimpleNamespace(
            repo=repo, recipes=recipes, client=client, authenticate=authenticate, media=media,
        )


async def add_video(repo, owner=101, *, name="source", duration_ms=8_750):
    return await repo.add_asset(owner, "video", f"private/{name}.mp4", {
        "duration_ms": duration_ms, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
        "url": "https://example.invalid/private-signed-url",
    })


async def read_project(api, project_id, **body):
    response = await api.client.post("/mini-app/api/genjutsu", json={
        "action": "project", "project_id": project_id, **body,
    })
    return response, await response.json()


@pytest.mark.asyncio
async def test_project_returns_exact_source_metadata_beyond_latest_100_assets(project_api):
    api = project_api
    source = await add_video(api.repo)
    plan = {"source_asset_id": source["id"], "steps": []}
    project = await api.repo.save_project(101, "Older video", plan)
    for index in range(101):
        await api.repo.add_asset(101, "image", f"new-{index}.png", {"size_bytes": 1})

    response = await api.client.post("/mini-app/api/genjutsu", json={"action": "bootstrap"})
    assert response.status == 200
    bootstrap = await response.json()
    assert len(bootstrap["assets"]) == 100
    assert source["id"] not in {asset["id"] for asset in bootstrap["assets"]}

    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert body["project"]["plan"] == plan
    assert body["source_asset"] == {
        "id": source["id"], "kind": "video", "duration_ms": 8_750,
    }
    assert "private/source.mp4" not in repr(body)
    assert "private-signed-url" not in repr(body)
    api.media.url.assert_not_called()


@pytest.mark.asyncio
async def test_project_metadata_matches_requested_revision(project_api):
    api = project_api
    original = await add_video(api.repo)
    newer = await add_video(api.repo, name="newer", duration_ms=12_400)
    project = await api.repo.save_project(101, "Original", {"source_asset_id": original["id"]})
    await api.repo.save_project(101, "Changed", {"source_asset_id": newer["id"]},
                                project_id=project["id"], expected_revision=1)
    response, body = await read_project(api, project["id"], revision=1)
    assert response.status == 200
    assert body["project"]["revision"] == 1
    assert body["source_asset"] == {
        "id": original["id"], "kind": "video", "duration_ms": 8_750,
    }
    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert body["source_asset"] == {
        "id": newer["id"], "kind": "video", "duration_ms": 12_400,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", [None, "", "missing", [], {}])
async def test_project_without_available_source_stays_readable(project_api, source_id):
    api = project_api
    plan = {"source_asset_id": source_id}
    project = await api.repo.save_project(101, "Repairable draft", plan)
    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert body["project"]["plan"] == plan
    assert body["source_asset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_project_cannot_expose_foreign_source_metadata(project_api, admin):
    api = project_api
    api.authenticate.return_value = (101, admin)
    source = await add_video(api.repo, owner=999, duration_ms=17_654)
    project = await api.repo.save_project(101, "Owned draft with foreign source", {
        "source_asset_id": source["id"],
    })
    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert body["source_asset"] is None
    assert "17654" not in repr(body)
    assert "private/source.mp4" not in repr(body)
    assert "private-signed-url" not in repr(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"size_bytes": 100}, {"size_bytes": 100, "duration_ms": None}])
async def test_owned_source_without_duration_does_not_invent_one(project_api, metadata):
    api = project_api
    source = await api.repo.add_asset(101, "video", "legacy.mp4", metadata)
    project = await api.repo.save_project(101, "Legacy metadata", {"source_asset_id": source["id"]})
    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert body["source_asset"] == {"id": source["id"], "kind": "video"}


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_project_requires_ownership_even_when_source_is_owned(project_api, admin):
    api = project_api
    api.authenticate.return_value = (101, admin)
    source = await add_video(api.repo)
    project = await api.repo.save_project(999, "Foreign project", {"source_asset_id": source["id"]})
    response, body = await read_project(api, project["id"])
    assert response.status == 404
    assert body["code"] == "project_unavailable"
    assert "project" not in body
    assert "source_asset" not in body
    assert source["id"] not in repr(body)


@pytest.mark.asyncio
async def test_project_requires_authentication(project_api):
    api = project_api
    source = await add_video(api.repo)
    project = await api.repo.save_project(101, "Owned project", {"source_asset_id": source["id"]})
    api.authenticate.side_effect = PipelineError("unauthorized", status=401)
    response, body = await read_project(api, project["id"])
    assert response.status == 401
    assert body["code"] == "unauthorized"
    assert "project" not in body
    assert "source_asset" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["active", "archived", "missing"])
@pytest.mark.parametrize("source_binding", ["fixed", "user"])
@pytest.mark.parametrize("admin", [False, True])
async def test_private_recipe_project_never_exposes_source_metadata(
    project_api, state, source_binding, admin,
):
    api = project_api
    api.authenticate.return_value = (101, admin)
    source = await add_video(api.repo, owner=999, duration_ms=5_000)
    user_source = await add_video(api.repo, name="user-source", duration_ms=5_000)
    reference = await api.repo.add_asset(999, "image", "private/fixed.png", {"size_bytes": 10})
    plan = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "PRIVATE_RECIPE_PROMPT", "preserve": "",
            "references": [{"asset_id": reference["id"], "role": "character", "binding": "fixed"}],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    template = await api.repo.save_project(999, "Template", plan)
    api.repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await api.recipes.publish(
        999, template["id"], 1, "Public title", [], "verified-run", source_binding=source_binding,
    )
    instance = await api.recipes.instantiate(
        101, recipe["id"], [], {},
        source_asset_id=user_source["id"] if source_binding == "user" else None,
    )
    if state == "archived":
        await api.recipes.archive(999, recipe["id"])
    elif state == "missing":
        # The isolated SQLite fixture permits an orphaned binding to model legacy data.
        async with api.repo.transaction() as db:
            await db.execute("DELETE FROM genjutsu_recipes WHERE id=?", (recipe["id"],))

    response, body = await read_project(api, instance["id"])
    assert response.status == 404
    assert body["code"] == "project_unavailable"
    assert "project" not in body
    assert "source_asset" not in body
    for private_value in (source["id"], user_source["id"], reference["id"], "PRIVATE_RECIPE_PROMPT"):
        assert private_value not in repr(body)


@pytest.mark.asyncio
async def test_quote_reference_error_is_actionable_and_logs_only_safe_context(project_api, caplog):
    api = project_api
    settings, version = await api.repo.settings()
    settings["public_enabled"] = True
    await api.repo.update_settings(999, version, settings)
    source = await add_video(api.repo)
    project = await api.repo.save_project(101, "SENSITIVE_TITLE", {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "SENSITIVE_PROMPT", "preserve": "SENSITIVE_PRESERVE", "references": [],
        }],
    })
    with caplog.at_level("WARNING", logger="bot.genjutsu.api"):
        response = await api.client.post("/mini-app/api/genjutsu", json={
            "action": "quote", "project_id": project["id"], "revision": 1,
            "init_data": "SENSITIVE_INIT_DATA",
        })
    body = await response.json()
    assert response.status == 400
    assert body["code"] == "invalid_reference_count"
    assert body["error"] == "Проверьте количество фото-референсов для выбранного режима: добавьте недостающие или удалите лишние фото."
    records = [record for record in caplog.records if record.name == "bot.genjutsu.api"]
    assert len(records) == 1
    record = records[0]
    assert logging.Formatter("%(message)s").format(record) == (
        "genjutsu_api_error action=quote code=invalid_reference_count status=400 error_type=PipelineError"
    )
    assert (record.action, record.code, record.status, record.error_type) == (
        "quote", "invalid_reference_count", 400, "PipelineError",
    )
    assert record.exc_info is None
    for sensitive_value in (
        "SENSITIVE_TITLE", "SENSITIVE_PROMPT", "SENSITIVE_PRESERVE", "SENSITIVE_INIT_DATA",
        source["id"], project["id"], "private/source.mp4", "private-signed-url",
    ):
        assert sensitive_value not in repr(record.__dict__)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "audio"])
async def test_non_video_source_does_not_supply_video_duration(project_api, kind):
    api = project_api
    source = await api.repo.add_asset(101, kind, f"source.{kind}", {"duration_ms": 8_750})
    project = await api.repo.save_project(101, "Wrong source kind", {"source_asset_id": source["id"]})
    response, body = await read_project(api, project["id"])
    assert response.status == 200
    assert body["source_asset"] is None


@pytest.mark.asyncio
async def test_project_source_lookup_does_not_suppress_unexpected_errors(project_api, monkeypatch):
    api = project_api
    source = await add_video(api.repo)
    project = await api.repo.save_project(101, "Source", {"source_asset_id": source["id"]})
    monkeypatch.setattr(api.repo, "get_assets", AsyncMock(side_effect=PipelineError("lookup_failed", status=503)))
    response, body = await read_project(api, project["id"])
    assert response.status == 503
    assert body["code"] == "lookup_failed"
    assert "source_asset" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["SENSITIVE_ACTION", {"SENSITIVE_ACTION": "SENSITIVE_VALUE"}])
async def test_error_logs_allowlist_action_instead_of_request_data(project_api, caplog, action):
    api = project_api
    with caplog.at_level("WARNING", logger="bot.genjutsu.api"):
        response = await api.client.post("/mini-app/api/genjutsu", json={
            "action": action, "init_data": "SENSITIVE_INIT_DATA",
        })
    assert response.status == 400
    assert (await response.json())["code"] == "invalid_action"
    records = [record for record in caplog.records if record.name == "bot.genjutsu.api"]
    assert len(records) == 1
    assert (records[0].action, records[0].code, records[0].status) == ("unknown", "invalid_action", 400)
    assert "SENSITIVE" not in repr(records[0].__dict__)


@pytest.mark.asyncio
async def test_upload_error_logs_fixed_action_without_auth_header(project_api, caplog):
    api = project_api
    api.authenticate.side_effect = PermissionError("SENSITIVE_EXCEPTION")
    with caplog.at_level("WARNING", logger="bot.genjutsu.api"):
        response = await api.client.post("/mini-app/api/genjutsu/upload", headers={
            "X-Telegram-Init-Data": "SENSITIVE_AUTH_HEADER",
        })
    assert response.status == 403
    record = next(record for record in caplog.records if record.name == "bot.genjutsu.api")
    assert (record.action, record.code, record.status, record.error_type) == (
        "upload", "unauthorized", 403, "PermissionError",
    )
    assert "SENSITIVE" not in repr(record.__dict__)
    assert record.exc_info is None


@pytest.mark.asyncio
async def test_unexpected_error_logs_type_without_raw_exception(project_api, caplog):
    api = project_api
    api.authenticate.side_effect = RuntimeError("SENSITIVE_EXCEPTION https://example.invalid/private")
    with caplog.at_level("ERROR", logger="bot.genjutsu.api"):
        response, body = await read_project(api, "SENSITIVE_PROJECT_ID", init_data="SENSITIVE_AUTH")
    assert response.status == 500
    assert body["code"] == "internal_error"
    record = next(record for record in caplog.records if record.name == "bot.genjutsu.api")
    assert (record.action, record.code, record.status, record.error_type) == (
        "unknown", "internal_error", 500, "RuntimeError",
    )
    assert "SENSITIVE" not in repr(record.__dict__)
    assert "https://example.invalid/private" not in repr(record.__dict__)
    assert record.exc_info is None


@pytest.mark.asyncio
async def test_title_and_missing_asset_errors_are_actionable(project_api):
    api = project_api
    settings, version = await api.repo.settings()
    settings["public_enabled"] = True
    await api.repo.update_settings(999, version, settings)
    response = await api.client.post("/mini-app/api/genjutsu", json={
        "action": "save_project", "title": "", "plan": {},
    })
    body = await response.json()
    assert response.status == 400
    assert body["code"] == "invalid_title"
    assert body["error"] == "Введите название проекта от 1 до 120 символов."
    project = await api.repo.save_project(101, "Missing source", {"source_asset_id": "missing", "steps": []})
    response = await api.client.post("/mini-app/api/genjutsu", json={
        "action": "quote", "project_id": project["id"], "revision": 1,
    })
    body = await response.json()
    assert response.status == 404
    assert body["code"] == "asset_unavailable"
    assert body["error"] == "Один из исходных файлов недоступен. Загрузите видео или фото заново."


@pytest.mark.asyncio
async def test_notification_templates_are_admin_settings_not_bootstrap_limits(project_api):
    api = project_api
    for admin in (False, True):
        api.authenticate.return_value = (101, admin)
        response = await api.client.post("/mini-app/api/genjutsu", json={"action": "bootstrap"})
        assert response.status == 200
        assert "notification_templates" not in (await response.json())["limits"]
    response = await api.client.post("/mini-app/api/genjutsu", json={"action": "settings"})
    assert response.status == 200
    assert (await response.json())["settings"]["notification_templates"]
    api.authenticate.return_value = (101, False)
    response = await api.client.post("/mini-app/api/genjutsu", json={"action": "settings"})
    assert response.status == 403


@pytest.mark.asyncio
async def test_invalid_notification_templates_have_safe_admin_message(project_api):
    api = project_api
    api.authenticate.return_value = (999, True)
    settings, version = await api.repo.settings()
    settings["notification_templates"] = {"invalid": "SENSITIVE_TEMPLATE"}
    response = await api.client.post("/mini-app/api/genjutsu", json={
        "action": "save_settings", "settings": settings, "expected_version": version,
    })
    body = await response.json()
    assert response.status == 400
    assert body["code"] == "invalid_notification_templates"
    assert body["error"] == "Проверьте тексты уведомлений и обязательные поля в фигурных скобках."
    assert "SENSITIVE_TEMPLATE" not in repr(body)
