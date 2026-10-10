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
    assert recipe["current_cost"] == 20


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


@pytest.mark.asyncio
async def test_recipe_user_video_slot_replaces_template_source_and_keeps_fixed_refs_private(tmp_path):
    repo, recipes = await build(tmp_path)
    template_source = await repo.add_asset(999, "video", "a" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    placeholder = await repo.add_asset(999, "image", "b" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    fixed = await repo.add_asset(999, "image", "c" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    user_video = await repo.add_asset(101, "video", "d" * 32 + ".mp4", {
        "duration_ms": 6_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    user_image = await repo.add_asset(101, "image", "e" * 32 + ".png", {
        "size_bytes": 10, "mime": "image/png",
    })
    plan = {
        "source_asset_id": template_source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "Secret", "preserve": "",
            "references": [
                {"asset_id": placeholder["id"], "role": "character", "label": "Ваш герой", "binding": "user"},
                {"asset_id": fixed["id"], "role": "wardrobe", "label": "Скрытая одежда", "binding": "fixed"},
            ],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)

    recipe = await recipes.publish(
        999, project["id"], project["revision"], "Public title", [], "verified-run",
        source_binding="user",
    )

    assert recipe["source_slot"] == {
        "kind": "video",
        "label": "Видео с нужным движением",
    }
    assert template_source["id"] not in repr(recipe)
    assert fixed["id"] not in repr(recipe)

    instance = await recipes.instantiate(
        101,
        recipe["id"],
        [user_image["id"]],
        {},
        source_asset_id=user_video["id"],
    )
    hidden = await repo.get_project(101, instance["id"])
    draft, grants, private = await recipes.resolve_project(101, instance["id"], 1, hidden["plan"])

    assert private is True
    assert draft["source_asset_id"] == user_video["id"]
    assert draft["steps"][0]["references"][0]["asset_id"] == user_image["id"]
    assert fixed["id"] in grants
    assert template_source["id"] not in grants


@pytest.mark.asyncio
async def test_recipe_user_video_slot_rejects_image_as_source(tmp_path):
    repo, recipes = await build(tmp_path)
    template_source = await repo.add_asset(999, "video", "f" * 32 + ".mp4", {
        "duration_ms": 5_000, "size_bytes": 100, "mime": "video/mp4",
        "width": 1280, "height": 720,
    })
    placeholder = await repo.add_asset(999, "image", "1" * 31 + "0.png", {
        "size_bytes": 10, "mime": "image/png",
    })
    wrong_source = await repo.add_asset(101, "image", "2" * 31 + "0.png", {
        "size_bytes": 10, "mime": "image/png",
    })
    user_image = await repo.add_asset(101, "image", "3" * 31 + "0.png", {
        "size_bytes": 10, "mime": "image/png",
    })
    plan = {
        "source_asset_id": template_source["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "Secret", "preserve": "",
            "references": [{
                "asset_id": placeholder["id"], "role": "character", "label": "Ваш герой", "binding": "user",
            }],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await recipes.publish(
        999, project["id"], project["revision"], "Public title", [], "verified-run",
        source_binding="user",
    )

    with pytest.raises(Exception, match="source_unavailable"):
        await recipes.instantiate(
            101,
            recipe["id"],
            [user_image["id"]],
            {},
            source_asset_id=wrong_source["id"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("recipe_state", ["archived", "missing"])
@pytest.mark.parametrize("source_binding", ["user", "fixed"])
async def test_recipe_project_fails_closed_after_recipe_unavailable(
    tmp_path, recipe_state, source_binding,
):
    from types import SimpleNamespace

    from bot.genjutsu.api import API
    from bot.genjutsu.contract import PipelineError
    from bot.genjutsu.pipeline import Pipeline

    repo, recipes = await build(tmp_path)
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    await repo.update_settings(999, version, settings)

    assets = {}
    for name, owner, kind in [
        ("template", 999, "video"),
        ("placeholder", 999, "image"),
        ("user_video", 101, "video"),
        ("user_image", 101, "image"),
    ]:
        assets[name] = await repo.add_asset(owner, kind, name, {
            "duration_ms": 5_000, "size_bytes": 100,
            "width": 1280, "height": 720,
            "mime": "video/mp4" if kind == "video" else "image/png",
        })
    plan = {
        "source_asset_id": assets["template"]["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "Private recipe prompt", "preserve": "Private preserve",
            "references": [{
                "asset_id": assets["placeholder"]["id"],
                "role": "character", "label": "Your photo", "binding": "user",
            }],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await recipes.publish(
        999, project["id"], 1, "Public title", [], "verified-run",
        source_binding=source_binding,
    )
    media = SimpleNamespace(
        configured=True, ensure_asset=AsyncMock(),
        url=lambda asset_id, ttl: f"https://example.invalid/{asset_id}",
    )
    provider = SimpleNamespace(configured=True)
    pipeline = Pipeline(repo, provider, media, plan_resolver=recipes.resolve_project)
    api = API(pipeline, AsyncMock(), recipes=recipes)
    body = {
        "recipe_id": recipe["id"],
        "reference_asset_ids": [assets["user_image"]["id"]],
        "user_values": {},
    }
    if source_binding == "user":
        body["source_asset_id"] = assets["user_video"]["id"]
    quoted = await api.dispatch(101, False, "recipe_quote", body)
    started = await api.dispatch(101, False, "start", {
        "quote_id": quoted["quote"]["id"], "request_key": "private-recipe-run",
    })
    assert started["run"]["private_recipe"] == 1
    assert "plan" not in started["run"]
    bootstrap = await api.dispatch(101, False, "bootstrap", {})
    private_project_id = next(
        run["project_id"] for run in bootstrap["runs"]
        if run["id"] == started["run"]["id"]
    )

    if recipe_state == "archived":
        await recipes.archive(999, recipe["id"])
    else:
        # Exercise an orphaned binding defensively using the isolated SQLite
        # fixture, where foreign-key enforcement is intentionally not enabled.
        async with repo.transaction() as db:
            await db.execute("DELETE FROM genjutsu_recipes WHERE id=?", (recipe["id"],))

    with pytest.raises(PipelineError, match="recipe_unavailable") as caught:
        await api.dispatch(101, False, "quote", {
            "project_id": private_project_id, "revision": 1,
        })
    assert caught.value.status == 404
    existing = await api.run_view(101, started["run"]["id"])
    assert existing["private_recipe"] == 1
    assert "plan" not in existing
    assert "prompt" not in existing["steps"][0]["spec"]

    ordinary = await repo.save_project(101, "Ordinary", {
        **plan,
        "source_asset_id": assets["user_video"]["id"],
        "steps": [{
            **plan["steps"][0],
            "references": [{
                "asset_id": assets["user_image"]["id"],
                "role": "character", "label": "", "binding": "user",
            }],
        }],
    })
    assert (await api.dispatch(101, False, "quote", {
        "project_id": ordinary["id"], "revision": 1,
    }))["quote"]["total_credits"] == 20



@pytest.mark.asyncio
@pytest.mark.parametrize("recipe_state", ["archived", "missing"])
@pytest.mark.parametrize("legacy_stage", ["quote", "run"])
async def test_legacy_recipe_run_redacts_from_project_binding(
    tmp_path, recipe_state, legacy_stage,
):
    from types import SimpleNamespace

    from bot.genjutsu.api import API
    from bot.genjutsu.pipeline import Pipeline

    repo, recipes = await build(tmp_path)
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer"]
    settings["max_active_runs_per_user"] = 10
    await repo.update_settings(999, version, settings)

    assets = {}
    for name, owner, kind in [
        ("template", 999, "video"),
        ("placeholder", 999, "image"),
        ("user_video", 101, "video"),
        ("user_image", 101, "image"),
    ]:
        assets[name] = await repo.add_asset(owner, kind, name, {
            "duration_ms": 5_000, "size_bytes": 100,
            "width": 1280, "height": 720,
            "mime": "video/mp4" if kind == "video" else "image/png",
        })
    plan = {
        "source_asset_id": assets["template"]["id"],
        "steps": [{
            "operation": "motion_transfer", "resolution": "720p",
            "prompt": "Legacy private prompt", "preserve": "Legacy private preserve",
            "references": [{
                "asset_id": assets["placeholder"]["id"],
                "role": "character", "label": "Your photo", "binding": "user",
            }],
            "preset_id": None,
        }],
        "variants": 1, "continuation": "automatic",
    }
    project = await repo.save_project(999, "Template", plan)
    repo.verified_admin_run = AsyncMock(return_value=True)
    recipe = await recipes.publish(
        999, project["id"], 1, "Public title", [], "verified-run",
        source_binding="user",
    )
    media = SimpleNamespace(
        configured=True, ensure_asset=AsyncMock(),
        url=lambda asset_id, ttl: f"https://example.invalid/{asset_id}",
    )
    pipeline = Pipeline(
        repo, SimpleNamespace(configured=True), media,
        plan_resolver=recipes.resolve_project,
    )
    api = API(pipeline, AsyncMock(), recipes=recipes)
    quoted = await api.dispatch(101, False, "recipe_quote", {
        "recipe_id": recipe["id"],
        "reference_asset_ids": [assets["user_image"]["id"]],
        "source_asset_id": assets["user_video"]["id"],
        "user_values": {},
    })
    start_body = {
        "quote_id": quoted["quote"]["id"], "request_key": "legacy-private-run",
    }
    # Reproduce records issued by the old resolver, without using a provider
    # or modifying any real database. Cover both unconsumed quotes and runs.
    async with repo.transaction() as db:
        await db.execute(
            "UPDATE genjutsu_quotes SET private_recipe=0 WHERE id=?",
            (quoted["quote"]["id"],),
        )
    if legacy_stage == "run":
        await repo.start(101, start_body["request_key"], start_body["quote_id"])

    if recipe_state == "archived":
        await recipes.archive(999, recipe["id"])
    else:
        # This isolated SQLite fixture deliberately permits an orphan binding.
        async with repo.transaction() as db:
            await db.execute("DELETE FROM genjutsu_recipes WHERE id=?", (recipe["id"],))

    started = await api.dispatch(101, False, "start", start_body)
    run_id = started["run"]["id"]
    stored = await repo.get_run(101, run_id)
    assert stored["private_recipe"] == 0  # The guard requires no data migration.

    def assert_private(run):
        assert run["private_recipe"] == 1
        assert "plan" not in run
        assert "project_id" not in run
        assert "source_asset" not in run["steps"][0]
        assert run["steps"][0]["spec"] == {
            "operation": "motion_transfer", "resolution": "720p",
        }
        assert "Legacy private prompt" not in repr(run)
        assert "Legacy private preserve" not in repr(run)
        assert assets["user_video"]["id"] not in repr(run)
        assert assets["user_image"]["id"] not in repr(run)

    assert_private(started["run"])
    assert_private((await api.dispatch(101, False, "start", start_body))["run"])
    assert_private((await api.dispatch(101, False, "run", {"run_id": run_id}))["run"])
    assert_private((await api.dispatch(101, True, "run", {"run_id": run_id}))["run"])

    privileged = (await api.dispatch(999, True, "run", {
        "run_id": run_id, "admin_view": True,
    }))["run"]
    assert privileged["owner"] == 101
    assert privileged["private_recipe"] == 1
    assert privileged["project_id"] == stored["project_id"]
    assert privileged["plan"] == stored["plan"]
    assert privileged["steps"][0]["spec"]["prompt"] == "Legacy private prompt"
    assert privileged["steps"][0]["spec"]["preserve"] == "Legacy private preserve"
    assert privileged["steps"][0]["source_asset"]["id"] == assets["user_video"]["id"]

    ordinary = await repo.save_project(101, "Ordinary", stored["plan"])
    ordinary_quote = await api.dispatch(101, False, "quote", {
        "project_id": ordinary["id"], "revision": 1,
    })
    ordinary_run = (await api.dispatch(101, False, "start", {
        "quote_id": ordinary_quote["quote"]["id"], "request_key": "ordinary-run",
    }))["run"]
    assert ordinary_run["private_recipe"] == 0
    assert ordinary_run["project_id"] == ordinary["id"]
    assert ordinary_run["plan"] == stored["plan"]
    assert ordinary_run["steps"][0]["spec"]["prompt"] == "Legacy private prompt"
    assert ordinary_run["steps"][0]["spec"]["preserve"] == "Legacy private preserve"
    assert ordinary_run["steps"][0]["source_asset"]["id"] == assets["user_video"]["id"]
    assert_private((await api.dispatch(101, False, "cancel", {"run_id": run_id}))["run"])
