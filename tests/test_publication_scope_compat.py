from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database
from bot import db as db_backend
from bot.services import feed_persist


def _load_publication_scope_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "bot"
        / "handlers"
        / "publication_scope_compat.py"
    )
    spec = importlib.util.spec_from_file_location(
        "publication_scope_compat_test_module",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_miniapp_share_rejects_malformed_reference_selection(monkeypatch):
    from bot import miniapp

    publication_scope = _load_publication_scope_module()

    async def fake_payload(_request):
        return {
            "task_id": "seedance-task",
            "reference_image_indices": [False],
            "reference_video_indices": [],
        }

    monkeypatch.setattr(miniapp, "_miniapp_payload", fake_payload)

    response = await publication_scope._miniapp_generation_share_scoped(
        miniapp,
        object(),
    )

    assert response.status == 400
    assert "Некорректный выбор референсов" in json.loads(response.text)["error"]


@pytest.mark.asyncio
async def test_vk_scoped_publication_returns_vk_link(monkeypatch):
    from aiohttp import web

    from bot.miniapp_links import feed_link

    publication_scope = _load_publication_scope_module()
    module = SimpleNamespace(
        _miniapp_payload=AsyncMock(return_value={
            "task_id": "vk-publication",
            "publication_scope": "feed",
        }),
        _payload_bool=lambda value, default: default if value is None else bool(value),
        _optional_reference_indices=lambda _body, _key: None,
        _get_user_context=AsyncMock(return_value=(
            123456,
            {
                "user": SimpleNamespace(id=7),
                "platform": "vk",
                "vk_app_id": 54880352,
            },
        )),
        _miniapp_link_kwargs=lambda ctx: {
            "platform": ctx["platform"],
            "vk_app_id": ctx["vk_app_id"],
        },
        build_feed_link=feed_link,
        config=SimpleNamespace(mini_app_url="https://t.me/testbot/app"),
        web=web,
        _miniapp_error_response=lambda error, **_kwargs: web.json_response(
            {"ok": False, "error": str(error)},
            status=500,
        ),
    )
    monkeypatch.setattr(
        publication_scope,
        "share_to_feed_scoped",
        AsyncMock(return_value={
            "id": 42,
            "author_referral_code": "AUTHOR",
        }),
    )
    monkeypatch.setattr(
        publication_scope,
        "_invalidate_publication_caches",
        lambda: None,
    )
    request = SimpleNamespace(app={
        "bot": SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(username="testbot")),
        ),
    })

    response = await publication_scope._miniapp_generation_share_scoped(module, request)

    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["feed_item"]["publication_link"] == (
        "https://vk.com/app54880352#feed_42_ref_AUTHOR"
    )
    assert "t.me" not in payload["feed_item"]["publication_link"]


@pytest.mark.parametrize("scope", ["private", "profile", "feed"])
def test_publication_result_uses_one_stable_publish_action(scope):
    publication_scope = _load_publication_scope_module()
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="old", callback_data="feedpub_task-1")],
            [InlineKeyboardButton(text="repeat", callback_data="repeat_task-1")],
        ]
    )

    markup = publication_scope._replace_publication_button(
        original,
        "task-1",
        scope=scope,
    )

    publication_buttons = [
        button
        for row in markup.inline_keyboard
        for button in row
        if str(button.callback_data or "").startswith("pubscope_")
    ]
    assert len(publication_buttons) == 1
    assert publication_buttons[0].text == "📤 Опубликовать"
    assert publication_buttons[0].callback_data == "pubscope_task-1"


def test_publication_result_deduplicates_legacy_and_normalized_actions():
    publication_scope = _load_publication_scope_module()
    original = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="first", callback_data="pubscope_task-1")],
            [InlineKeyboardButton(text="legacy", callback_data="feedpub_task-1")],
            [InlineKeyboardButton(text="keep", callback_data="repeat_task-1")],
        ]
    )

    markup = publication_scope._replace_publication_button(
        original,
        "task-1",
        scope="private",
    )

    publication_buttons = [
        button
        for row in markup.inline_keyboard
        for button in row
        if str(button.callback_data or "").startswith("pubscope_")
    ]
    assert len(publication_buttons) == 1
    assert publication_buttons[0].text == "📤 Опубликовать"


@pytest.mark.asyncio
async def test_bot_feed_link_falls_back_to_profile_only_post(monkeypatch):
    from bot.handlers import common

    profile_card = {"id": 42, "author_referral_code": "AUTHOR"}
    message = SimpleNamespace(answer=AsyncMock())
    viewer = SimpleNamespace(id=7)
    render = AsyncMock()

    monkeypatch.setattr(common, "get_feed_generation_card", AsyncMock(return_value=None))
    monkeypatch.setattr(
        common,
        "get_profile_generation_card",
        AsyncMock(return_value=profile_card),
    )
    monkeypatch.setattr(
        common,
        "_fetch_profile_feed_cards",
        AsyncMock(return_value=(SimpleNamespace(id=8), [profile_card])),
    )
    monkeypatch.setattr(common, "_render_feed_carousel", render)

    assert await common._render_feed_deeplink(message, viewer, "42") is True
    render.assert_awaited_once_with(
        message,
        [profile_card],
        index=0,
        source_code="m",
        profile_code="AUTHOR",
    )
    message.answer.assert_not_awaited()


def test_profile_publication_requires_explicit_blur_choice():
    publication_scope = _load_publication_scope_module()

    markup = publication_scope._profile_blur_keyboard("task-1")
    buttons = [button for row in markup.inline_keyboard for button in row]

    assert [(button.text, button.callback_data) for button in buttons] == [
        ("👁 Без blur", "profileblur_0_task-1"),
        ("🙈 С blur", "profileblur_1_task-1"),
        ("◀️ Назад", "pubscope_task-1"),
    ]


def test_feed_publication_requires_explicit_privacy_confirmation():
    publication_scope = _load_publication_scope_module()

    text, markup = publication_scope._feed_confirmation_components("task-1")
    buttons = [button for row in markup.inline_keyboard for button in row]

    assert "Prompt: <code>скрыт</code>" in text
    assert "Референсы: <code>скрыты</code>" in text
    assert "Blur: <code>выключен</code>" in text
    assert [(button.text, button.callback_data) for button in buttons] == [
        ("🔒 Prompt", "feedpubopt_task-1_1_0_0"),
        ("🔒 Референсы", "feedpubopt_task-1_0_1_0"),
        ("👁 Blur", "feedpubopt_task-1_0_0_1"),
        ("✅ Опубликовать", "feedpubok_task-1_0_0_0"),
        ("❌ Отмена", "ignore"),
    ]


@pytest.mark.asyncio
async def test_profile_only_publication_lifecycle(tmp_path, monkeypatch):
    if db_backend.is_postgres():
        pytest.skip("SQLite compatibility lifecycle test")

    publication_scope = _load_publication_scope_module()
    database_path = str(tmp_path / "publication-scope.db")
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)
    publication_scope._SCHEMA_READY_PATHS.clear()

    async def keep_result_urls(urls, **_kwargs):
        return list(urls)

    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", keep_result_urls)

    await database.init_db()
    user = await database.get_or_create_user(700001)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "scope-image-1",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Profile-only publication test",
        cost=2,
        request_data={
            "reference_images": [
                "https://example.com/face.png",
                "https://example.com/outfit.png",
            ]
        },
    )
    await database.complete_video_task(
        "scope-image-1",
        "https://example.com/profile-only.png",
    )

    profile_card = await publication_scope.share_to_profile(
        "scope-image-1",
        user.id,
        references_visible=True,
        reference_image_indices=[1],
        reference_video_indices=[],
    )
    assert profile_card is not None
    assert profile_card["publication_scope"] == "profile"
    assert profile_card["is_profile_visible"] is True
    assert profile_card["is_public_feed"] is False
    assert profile_card["feed_interactions_enabled"] is False
    assert profile_card["reference_images"] == ["https://example.com/outfit.png"]

    blurred_profile_card = await publication_scope.share_to_profile(
        "scope-image-1",
        user.id,
        blurred=True,
    )
    assert blurred_profile_card is not None
    assert blurred_profile_card["feed_blurred"] is True

    visible_profile_card = await publication_scope.share_to_profile(
        "scope-image-1",
        user.id,
        blurred=False,
    )
    assert visible_profile_card is not None
    assert visible_profile_card["feed_blurred"] is False

    public_feed = await database.get_feed_generations(limit=20)
    profile_feed = await publication_scope.get_user_profile_generations(
        user.id,
        limit=20,
        profile_visible_only=True,
    )
    assert public_feed == []
    assert [item["task_id"] for item in profile_feed] == ["scope-image-1"]
    assert await database.get_feed_generation_card(profile_card["id"]) is None
    assert await database.get_profile_generation_card(profile_card["id"]) is not None

    public_card = await publication_scope.share_to_feed_scoped(
        "scope-image-1",
        user.id,
    )
    assert public_card is not None
    assert public_card["publication_scope"] == "feed"
    assert public_card["is_profile_visible"] is True
    assert public_card["is_public_feed"] is True
    assert public_card["feed_interactions_enabled"] is True

    public_feed = await database.get_feed_generations(limit=20)
    assert [item["task_id"] for item in public_feed] == ["scope-image-1"]

    downgraded = await publication_scope.remove_from_feed_scoped(
        "scope-image-1",
        user.id,
    )
    assert downgraded is True
    assert await database.get_feed_generations(limit=20) == []
    profile_feed = await publication_scope.get_user_profile_generations(
        user.id,
        limit=20,
    )
    assert [item["publication_scope"] for item in profile_feed] == ["profile"]

    hidden = await publication_scope.remove_publication(
        "scope-image-1",
        user.id,
    )
    assert hidden is True
    assert await database.get_profile_generation_card(profile_card["id"]) is None
    assert await publication_scope.get_user_profile_generations(
        user.id,
        limit=20,
    ) == []


@pytest.mark.asyncio
async def test_miniapp_task_detail_keeps_profile_only_scope(monkeypatch):
    if db_backend.is_postgres():
        pytest.skip("SQLite compatibility lifecycle test")

    from bot import miniapp
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)

    async def keep_result_urls(urls, **_kwargs):
        return list(urls)

    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", keep_result_urls)

    user = await database.get_or_create_user(700002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "scope-detail-1",
        "image",
        "miniapp_image",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="Profile-only task detail test",
        cost=2,
    )
    await database.complete_video_task(
        "scope-detail-1",
        "https://example.com/profile-only-detail.png",
    )

    profile_card = await database.share_to_feed(
        "scope-detail-1",
        user.id,
        publication_scope="profile",
    )
    assert profile_card is not None

    detail = await miniapp._fetch_task_detail(user.telegram_id, "scope-detail-1")

    assert detail is not None
    assert detail["publication_scope"] == "profile"
    assert detail["is_profile_visible"] is True
    assert detail["is_public_feed"] is False
    assert detail["feed_interactions_enabled"] is False


@pytest.mark.asyncio
async def test_miniapp_feed_remix_falls_back_to_profile_only_source(monkeypatch):
    from bot import miniapp

    profile_card = {
        "id": 42,
        "gen_type": "image",
        "publication_scope": "profile",
        "is_profile_visible": True,
        "is_public_feed": False,
    }
    public_lookup = AsyncMock(return_value=None)
    profile_lookup = AsyncMock(return_value=profile_card)

    monkeypatch.setattr(miniapp, "get_feed_generation_card", public_lookup)
    monkeypatch.setattr(miniapp, "get_profile_generation_card", profile_lookup)

    card = await miniapp._get_feed_remix_source_card(
        42,
        viewer_user_id=7,
        allow_profile=False,
    )

    assert card == profile_card
    public_lookup.assert_awaited_once_with(
        42,
        viewer_user_id=7,
        include_unavailable=True,
    )
    profile_lookup.assert_awaited_once_with(
        42,
        viewer_user_id=7,
        include_unavailable=True,
    )


@pytest.mark.asyncio
async def test_postgres_schema_fastpath_is_read_only_under_concurrent_requests(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager

    publication = _load_publication_scope_module()
    monkeypatch.setattr(publication.database, "DATABASE_PATH", "pg-publication-fastpath-test")
    monkeypatch.setattr(publication.db_backend, "is_postgres", lambda: True)

    columns = [
        ("is_profile_visible",),
        ("profile_published_at",),
        ("feed_reference_selection",),
        ("feed_repeat_reference_selection",),
    ]
    queries = []
    connections = []

    class Cursor:
        async def fetchall(self):
            return columns

    class DB:
        async def execute(self, statement, *args):
            queries.append(statement)
            assert "information_schema.columns" in statement, (
                "existing PostgreSQL schema must not run ALTER TABLE / full-table backfill"
            )
            await asyncio.sleep(0.01)
            return Cursor()

        async def commit(self):
            raise AssertionError("read-only existing schema must not commit")

    @asynccontextmanager
    async def connection(*args, **kwargs):
        connections.append((args, kwargs))
        yield DB()

    monkeypatch.setattr(publication.db_backend, "connect", connection)
    await asyncio.gather(*(publication._ensure_publication_scope_schema() for _ in range(12)))
    assert len(connections) == 1
    assert len(queries) == 1
    assert "pg-publication-fastpath-test" in publication._SCHEMA_READY_PATHS


@pytest.mark.asyncio
async def test_postgres_schema_missing_column_still_migrates(monkeypatch):
    from contextlib import asynccontextmanager

    publication = _load_publication_scope_module()
    monkeypatch.setattr(publication.database, "DATABASE_PATH", "pg-publication-migration-test")
    monkeypatch.setattr(publication.db_backend, "is_postgres", lambda: True)
    queries = []
    committed = []

    class Cursor:
        async def fetchall(self):
            return [
                ("is_profile_visible",),
                ("profile_published_at",),
                ("feed_reference_selection",),
            ]

    class DB:
        async def execute(self, statement, *args):
            queries.append(statement)
            return Cursor()

        async def commit(self):
            committed.append(True)

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield DB()

    monkeypatch.setattr(publication.db_backend, "connect", connection)
    await publication._ensure_publication_scope_schema()
    ddl = [query for query in queries if query.startswith("DO $$")]
    assert len(ddl) == 1
    assert "ADD COLUMN feed_repeat_reference_selection" in ddl[0]
    assert any("UPDATE generation_tasks" in query for query in queries)
    assert committed == [True]
