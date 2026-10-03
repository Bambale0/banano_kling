from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from bot.genjutsu.recipes import RecipeStore
from bot.genjutsu.repository import Repository


async def build(tmp_path):
    path = tmp_path / "recipes.sqlite3"

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
        await db.executemany("INSERT INTO users VALUES (?, ?)", [(999, 1000), (101, 1000)])
        await db.commit()
    repo = Repository(connect)
    await repo.migrate()
    recipes = RecipeStore(repo)
    await recipes.migrate()
    settings, version = await repo.settings()
    settings["prices"] = {
        "motion_transfer": {"480p": 1, "720p": 2, "1080p": 3},
        "object_swap": {"480p": 1, "720p": 2, "1080p": 3},
        "restyle": {"480p": 1, "720p": 2, "1080p": 3},
    }
    await repo.update_settings(999, version, settings)
    return repo, recipes


@pytest.mark.asyncio
async def test_recipe_public_contract_hides_prompt_and_fixed_asset_ids(tmp_path):
    repo, recipes = await build(tmp_path)
    source = await repo.add_asset(999, "video", "1" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    user_slot = await repo.add_asset(999, "image", "2" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    fixed = await repo.add_asset(999, "image", "3" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    plan = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "object_swap", "resolution": "720p",
            "prompt": "Secret prompt for {{Имя}}", "preserve": "secret preserve",
            "references": [
                {"asset_id": user_slot["id"], "role": "character", "label": "Ваше фото", "binding": "user"},
                {"asset_id": fixed["id"], "role": "product", "label": "Секретный товар", "binding": "fixed"},
            ],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await recipes.publish(
        999, project["id"], project["revision"], "Public title",
        [{"key": "Имя", "label": "Имя"}], "verified-run",
    )
    encoded = repr(recipe)
    assert "Secret prompt" not in encoded
    assert source["id"] not in encoded
    assert fixed["id"] not in encoded
    assert recipe["slots"] == [{
        "step_index": 0, "reference_index": 0, "role": "character", "label": "Ваше фото",
    }]
    assert recipe["current_cost"] == 10


@pytest.mark.asyncio
async def test_recipe_instance_replaces_only_user_slots_and_grants_fixed_assets(tmp_path):
    repo, recipes = await build(tmp_path)
    source = await repo.add_asset(999, "video", "4" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    placeholder = await repo.add_asset(999, "image", "5" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    fixed = await repo.add_asset(999, "image", "6" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    user_image = await repo.add_asset(101, "image", "7" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    plan = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "object_swap", "resolution": "720p",
            "prompt": "Use {{Имя}}", "preserve": "",
            "references": [
                {"asset_id": placeholder["id"], "role": "character", "label": "Ваше фото", "binding": "user"},
                {"asset_id": fixed["id"], "role": "product", "label": "Товар", "binding": "fixed"},
            ],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await recipes.publish(
        999, project["id"], project["revision"], "Public title",
        [{"key": "Имя", "label": "Имя"}], "verified-run",
    )
    instance = await recipes.instantiate(101, recipe["id"], [user_image["id"]], {"Имя": "Анна"})
    hidden = await repo.get_project(101, instance["id"])
    draft, grants, private = await recipes.resolve_project(101, instance["id"], 1, hidden["plan"])
    assert private is True
    assert draft["source_asset_id"] == source["id"]
    assert draft["steps"][0]["references"][0]["asset_id"] == user_image["id"]
    assert draft["steps"][0]["references"][1]["asset_id"] == fixed["id"]
    assert "Анна" in draft["steps"][0]["prompt"]
    assert grants == {source["id"], fixed["id"]}
    assert await recipes.is_private_project(instance["id"]) is True
    assert all(item["id"] != instance["id"] for item in await repo.list_projects(101))


@pytest.mark.asyncio
async def test_recipe_publish_requires_completed_matching_admin_run(tmp_path):
    repo, recipes = await build(tmp_path)
    source = await repo.add_asset(999, "video", "8" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    ref = await repo.add_asset(999, "image", "9" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    plan = {
        "source_asset_id": source["id"],
        "steps": [{
            "operation": "object_swap", "resolution": "720p",
            "prompt": "Swap", "preserve": "",
            "references": [{"asset_id": ref["id"], "role": "character", "label": "Фото", "binding": "user"}],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=False)
    with pytest.raises(Exception, match="recipe_live_verification_required"):
        await recipes.publish(
            999, project["id"], project["revision"], "Public title", [], "not-verified",
        )
