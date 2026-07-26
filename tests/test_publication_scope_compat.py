from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
async def test_profile_only_publication_lifecycle(tmp_path, monkeypatch):
    if db_backend.is_postgres():
        pytest.skip("SQLite compatibility lifecycle test")

    publication_scope = _load_publication_scope_module()
    database_path = str(tmp_path / "publication-scope.db")
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)
    publication_scope._SCHEMA_READY = False

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

    public_feed = await database.get_feed_generations(limit=20)
    profile_feed = await publication_scope.get_user_profile_generations(
        user.id,
        limit=20,
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
