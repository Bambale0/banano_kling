from __future__ import annotations

import importlib.util
from pathlib import Path

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

    async def keep_result_urls(urls):
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
    )
    await database.complete_video_task(
        "scope-image-1",
        "https://example.com/profile-only.png",
    )

    profile_card = await publication_scope.share_to_profile(
        "scope-image-1",
        user.id,
    )
    assert profile_card is not None
    assert profile_card["publication_scope"] == "profile"
    assert profile_card["is_profile_visible"] is True
    assert profile_card["is_public_feed"] is False
    assert profile_card["feed_interactions_enabled"] is False

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
    assert await publication_scope.get_user_profile_generations(
        user.id,
        limit=20,
    ) == []
