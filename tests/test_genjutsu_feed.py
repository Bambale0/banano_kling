from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot import db as db_backend
from bot.genjutsu.api import API
from bot.genjutsu.contract import compile_plan, quote_plan
from bot.genjutsu.feed import FeedPublisher
from bot.genjutsu.recipes import RecipeStore
from bot.genjutsu.repository import Repository


async def setup_owned_run(*, variants=1, step_count=1):
    @asynccontextmanager
    async def connect():
        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            yield db

    owner = await database.get_or_create_user(101)
    await database.get_or_create_user(202)
    repo = Repository(connect)
    await repo.migrate()
    recipes = RecipeStore(repo)
    repo.start_validator = recipes.validate_start
    await recipes.migrate()
    settings, version = await repo.settings()
    settings["public_enabled"] = True
    settings["verified_operations"] = ["motion_transfer", "object_swap", "restyle"]
    settings["prices"] = {
        op: {"480p": 1, "720p": 1, "1080p": 1}
        for op in ("motion_transfer", "object_swap", "restyle")
    }
    await repo.update_settings(999, version, settings)
    async with connect() as db:
        # Repeating user must afford the new two-component clip tariff.
        await db.execute("UPDATE users SET credits=1000 WHERE telegram_id IN (101, 202)")
        await db.commit()
    async def asset(kind, user=101):
        return await repo.add_asset(user, kind, uuid4().hex + (".mp4" if kind == "video" else ".png"), {
            "duration_ms": 5000, "size_bytes": 10, "width": 1280, "height": 720,
            "mime": "video/mp4" if kind == "video" else "image/png",
        })
    source, photo, fixed, output = await asset("video"), await asset("image"), await asset("image"), await asset("video")
    plan = {
        "source_asset_id": source["id"], "variants": 1, "continuation": "automatic",
        "steps": [{
            "operation": "object_swap", "resolution": "720p", "prompt": "PRIVATE_PROMPT",
            "preserve": "PRIVATE_PRESERVE", "preset_id": None, "references": [
                {"asset_id": photo["id"], "role": "character", "label": "Ваше фото", "binding": "user"},
                {"asset_id": fixed["id"], "role": "product", "label": "PRIVATE_FIXED_LABEL", "binding": "fixed"},
            ],
        }],
    }
    import copy
    plan["variants"] = variants
    plan["steps"] = [copy.deepcopy(plan["steps"][0]) for _ in range(step_count)]
    project = await repo.save_project(101, "Owned project", plan)
    settings, version = await repo.settings()
    owned = await repo.get_assets(101, {source["id"], photo["id"], fixed["id"]})
    plan = compile_plan(plan, owned, settings)
    quote = await repo.create_quote(101, project["id"], 1, plan, quote_plan(plan, owned, settings), version, settings)
    started = await repo.start(101, "fixture-start", quote["id"])
    run = await repo.get_run(101, started["id"])
    step = run["steps"][0]
    async with repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET state='completed' WHERE id=?", (run["id"],))
        await db.execute("UPDATE genjutsu_steps SET status='completed',output_asset_id=?,actual_credits=10 WHERE run_id=?", (output["id"], run["id"]))
    copy = AsyncMock(return_value="https://example.test/uploads/feed/public-output.mp4")
    publisher = FeedPublisher(repo, recipes, copy)
    pipeline = SimpleNamespace(repository=repo)
    api = API(pipeline, AsyncMock(return_value=(101, False)), recipes=recipes, feed=publisher)
    return SimpleNamespace(owner=owner, repo=repo, recipes=recipes, publisher=publisher, api=api,
                           run=run, step=step, project=project, source=source, photo=photo, fixed=fixed,
                           output=output, asset=asset, copy=copy)


def publication(ctx, **changes):
    return {"action": "feed_publish", "run_id": ctx.run["id"], "step_id": ctx.step["id"],
            "title": "Public example", "source_binding": "user", **changes}


@pytest.mark.asyncio
async def test_owner_publishes_completed_output_to_feed_and_repeats_privately():
    ctx = await setup_owned_run()
    before = await ctx.repo.balance(101)
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json=publication(ctx))
        assert response.status == 200
        result = await response.json()
    card, recipe = result["card"], result["recipe"]
    assert card["model"] == "genjutsu"
    assert card["gen_type"] == "video"
    assert card["genjutsu_recipe_id"] == recipe["id"]
    assert card["result_url"] == "https://example.test/uploads/feed/public-output.mp4"
    assert recipe["source_slot"]["kind"] == "video"
    assert recipe["slots"] == [{"step_index": 0, "reference_index": 0, "role": "character", "label": "Ваше фото"}]
    assert card["prompt"] == ""
    assert card["reference_images"] == card["reference_videos"] == []
    public = await database.get_feed_generation_card(card["id"])
    assert public["genjutsu_recipe_id"] == recipe["id"]
    for secret in ("PRIVATE_PROMPT", "PRIVATE_PRESERVE", "PRIVATE_FIXED_LABEL", ctx.source["id"], ctx.photo["id"], ctx.fixed["id"], ctx.output["storage_key"]):
        assert secret not in repr(result)
        assert secret not in repr(public)
    assert await ctx.repo.balance(101) == before
    replacement, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    instance = await ctx.recipes.instantiate(202, recipe["id"], [replacement["id"]], {}, source_asset_id=video["id"])
    hidden = await ctx.repo.get_project(202, instance["id"])
    plan, grants, private = await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    assert private is True
    assert plan["source_asset_id"] == video["id"]
    assert plan["steps"][0]["references"][0]["asset_id"] == replacement["id"]
    assert plan["steps"][0]["references"][1]["asset_id"] == ctx.fixed["id"]
    assert grants == {ctx.fixed["id"]}


async def withdraw(ctx, card_id):
    from bot.handlers.publication_scope_compat import remove_publication

    return await remove_publication(card_id, ctx.owner.id)


async def publish(ctx, owner=101, **changes):
    body = publication(ctx, **changes)
    return await ctx.api.dispatch(owner, False, "feed_publish", body)


@pytest.mark.asyncio
async def test_publication_is_idempotent_concurrently_and_rejects_changed_declaration():
    import asyncio

    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    first, second = await asyncio.gather(publish(ctx), publish(ctx))
    assert first["card"]["id"] == second["card"]["id"]
    assert first["recipe"]["id"] == second["recipe"]["id"]
    cards = await database.get_feed_generations()
    assert len(cards) == 1
    assert cards[0]["model"] == "genjutsu"
    with pytest.raises(PipelineError, match="feed_publication_conflict"):
        await publish(ctx, source_binding="fixed")
    with pytest.raises(PipelineError, match="feed_publication_conflict"):
        await publish(ctx, title="A changed declaration")


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,changes,code", [
    (202, {}, "run_unavailable"),
    (101, {"step_id": "foreign-step"}, "completed_output_required"),
    (101, {"source_binding": "automatic"}, "invalid_source_binding"),
    (101, {"title": ""}, "invalid_title"),
])
async def test_publish_rejects_invalid_owner_output_or_declaration(owner, changes, code):
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    with pytest.raises(PipelineError, match=code):
        await publish(ctx, owner=owner, **changes)
    ctx.copy.assert_not_awaited()
    assert await database.get_feed_generations() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state,status", [("running", "completed"), ("partial", "completed"), ("completed", "failed")])
async def test_publish_requires_completed_run_and_step(state, status):
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET state=? WHERE id=?", (state, ctx.run["id"]))
        await db.execute("UPDATE genjutsu_steps SET status=? WHERE id=?", (status, ctx.step["id"]))
    with pytest.raises(PipelineError, match="completed_output_required"):
        await publish(ctx)
    ctx.copy.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_rejects_intermediate_output_and_foreign_output():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_steps SET ordinal=1 WHERE id=?", (ctx.step["id"],))
    with pytest.raises(PipelineError, match="completed_output_required"):
        await publish(ctx)
    foreign = await ctx.asset("video", 202)
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_steps SET ordinal=0,output_asset_id=? WHERE id=?", (foreign["id"], ctx.step["id"]))
    with pytest.raises(PipelineError, match="asset_unavailable"):
        await publish(ctx)
    ctx.copy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_private_recipe_binding_cannot_be_copied_even_with_stale_privacy_flag(archived):
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    original = await publish(ctx)
    async with ctx.repo.transaction() as db:
        await db.execute("INSERT INTO genjutsu_recipe_projects(project_id,recipe_id) VALUES(?,?)",
                         (ctx.project["id"], original["recipe"]["id"]))
        await db.execute("UPDATE genjutsu_runs SET private_recipe=0 WHERE id=?", (ctx.run["id"],))
    if archived:
        await ctx.recipes.archive(101, original["recipe"]["id"])
    ctx.copy.reset_mock()
    with pytest.raises(PipelineError, match="private_recipe_publication_forbidden"):
        await publish(ctx)
    ctx.copy.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_flag_and_archived_recipe_fail_closed():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET private_recipe=1 WHERE id=?", (ctx.run["id"],))
    with pytest.raises(PipelineError, match="private_recipe_publication_forbidden"):
        await publish(ctx)
    ctx.copy.assert_not_awaited()
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET private_recipe=0 WHERE id=?", (ctx.run["id"],))
    original = await publish(ctx)
    await ctx.recipes.archive(101, original["recipe"]["id"])
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await publish(ctx)


@pytest.mark.asyncio
async def test_replacements_require_exact_owned_media_and_preserve_fixed_bindings():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    result = await publish(ctx, source_binding="fixed")
    recipe_id = result["recipe"]["id"]
    assert result["recipe"]["source_slot"] is None
    image, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    for refs, source, code in [
        ([], None, "recipe_reference_count"),
        ([image["id"], image["id"]], None, "recipe_reference_count"),
        ([ctx.photo["id"]], None, "asset_unavailable"),
        ([video["id"]], None, "reference_unavailable"),
        ([image["id"]], video["id"], "source_not_replaceable"),
    ]:
        with pytest.raises(PipelineError, match=code):
            await ctx.recipes.instantiate(202, recipe_id, refs, {}, source_asset_id=source)
    instance = await ctx.recipes.instantiate(202, recipe_id, [image["id"]], {})
    hidden = await ctx.repo.get_project(202, instance["id"])
    plan, grants, private = await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    assert private is True
    assert grants == {ctx.source["id"], ctx.fixed["id"]}
    assert plan["source_asset_id"] == ctx.source["id"]
    assert plan["steps"][0]["references"][0]["asset_id"] == image["id"]
    assert plan["steps"][0]["references"][1]["asset_id"] == ctx.fixed["id"]


@pytest.mark.asyncio
async def test_user_video_slot_rejects_missing_foreign_or_image_source():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    result = await publish(ctx)
    image = await ctx.asset("image", 202)
    for source, code in [(None, "source_required"), (ctx.source["id"], "source_unavailable"), (image["id"], "source_unavailable")]:
        with pytest.raises(PipelineError, match=code):
            await ctx.recipes.instantiate(202, result["recipe"]["id"], [image["id"]], {}, source_asset_id=source)


@pytest.mark.asyncio
async def test_feed_withdrawal_revokes_repeats_and_stale_publish_cannot_resurrect():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    result = await publish(ctx)
    image, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    instance = await ctx.recipes.instantiate(202, result["recipe"]["id"], [image["id"]], {}, source_asset_id=video["id"])
    hidden = await ctx.repo.get_project(202, instance["id"])
    assert await withdraw(ctx, result["card"]["id"])
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await ctx.recipes.public(result["recipe"]["id"])
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    with pytest.raises(PipelineError, match="feed_publication_withdrawn"):
        await publish(ctx)
    assert await database.get_feed_generation_card(result["card"]["id"]) is None
    # The owner's explicit, existing publication editor can restore the post.
    again = await database.share_to_feed(result["card"]["id"], ctx.owner.id)
    assert again["id"] == result["card"]["id"]
    assert (await ctx.recipes.public(result["recipe"]["id"]))["id"] == result["recipe"]["id"]


@pytest.mark.asyncio
async def test_quote_withdraw_start_is_rejected_before_reserving_credits():
    from bot.genjutsu.contract import PipelineError, asset_ids

    ctx = await setup_owned_run()
    result = await publish(ctx)
    image, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    instance = await ctx.recipes.instantiate(202, result["recipe"]["id"], [image["id"]], {}, source_asset_id=video["id"])
    hidden = await ctx.repo.get_project(202, instance["id"])
    plan, grants, private = await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    settings, version = await ctx.repo.settings()
    assets = await ctx.repo.get_assets(202, asset_ids(plan), grants=grants)
    quote = await ctx.repo.create_quote(202, instance["id"], 1, plan, quote_plan(plan, assets, settings), version, settings, private_recipe=private)
    before = await ctx.repo.balance(202)
    await withdraw(ctx, result["card"]["id"])
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await ctx.repo.start(202, "revoked-quote", quote["id"])
    assert await ctx.repo.balance(202) == before
    assert (await ctx.repo.get_run(101, ctx.run["id"]))["state"] == "completed"


@pytest.mark.asyncio
async def test_output_copy_is_durable_and_does_not_copy_originals(tmp_path):
    from bot.genjutsu.feed import copy_public_output
    from bot.genjutsu.media import MediaStore

    media = MediaStore(tmp_path / "private", "https://example.test", "s" * 32)
    original = media.path("a" * 32 + ".mp4")
    final = media.path("b" * 32 + ".mp4")
    original.write_bytes(b"private-original")
    final.write_bytes(b"public-final")
    output = {"kind": "video", "storage_key": final.name}
    directory = tmp_path / "public-feed"
    first = await copy_public_output(media, output, "step-fixture", directory=directory, base_url="https://cdn.example.test")
    second = await copy_public_output(media, output, "step-fixture", directory=directory, base_url="https://cdn.example.test")
    assert first == second
    assert len(list(directory.iterdir())) == 1
    assert next(directory.iterdir()).read_bytes() == b"public-final"
    assert original.read_bytes() == b"private-original"
    assert original.name not in first
    assert final.name not in first


@pytest.mark.asyncio
async def test_ordinary_owner_cannot_use_admin_recipe_publication():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    with pytest.raises(PipelineError, match="admin_required"):
        await ctx.recipes.dispatch(101, False, "recipe_publish", {
            "project_id": ctx.project["id"], "revision": 1, "title": "Title",
            "verification_run_id": ctx.run["id"],
        }, ctx.api)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["quick_repeat_video_result", "repeat_advanced_video_result"])
async def test_legacy_telegram_repeat_redirects_before_billing(handler_name, monkeypatch):
    from bot.handlers import generation, video_generation_compat

    ctx = await setup_owned_run()
    result = await publish(ctx)
    module = generation if handler_name == "quick_repeat_video_result" else video_generation_compat
    deduct, launch = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module, "deduct_credits", deduct)
    monkeypatch.setattr(module, "run_no_preset_video_from_callback", launch)
    callback = SimpleNamespace(data="repeat_video_result_" + result["card"]["task_id"],
                               from_user=SimpleNamespace(id=202), answer=AsyncMock(),
                               message=SimpleNamespace(answer=AsyncMock()))
    await getattr(module, handler_name)(callback, SimpleNamespace())
    deduct.assert_not_awaited()
    launch.assert_not_awaited()
    markup = callback.message.answer.await_args.kwargs["reply_markup"]
    from urllib.parse import parse_qs, urlsplit

    url = markup.inline_keyboard[0][0].web_app.url
    assert parse_qs(urlsplit(url).query)["startapp"] == [
        f'feed_{result["card"]["id"]}_ref_{ctx.owner.referral_code}'
    ]
    assert "genjutsu_recipe" not in url


@pytest.mark.asyncio
async def test_withdrawn_legacy_repeat_does_not_launch_or_charge(monkeypatch):
    from bot.handlers import video_generation_compat as module

    ctx = await setup_owned_run()
    result = await publish(ctx)
    await withdraw(ctx, result["card"]["id"])
    deduct = AsyncMock()
    monkeypatch.setattr(module, "deduct_credits", deduct)
    callback = SimpleNamespace(data="repeat_video_result_" + result["card"]["task_id"],
                               from_user=SimpleNamespace(id=202), answer=AsyncMock(),
                               message=SimpleNamespace(answer=AsyncMock()))
    await module.repeat_advanced_video_result(callback, SimpleNamespace())
    deduct.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
    assert callback.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_generic_miniapp_repeat_requires_genjutsu_recipe_before_provider(monkeypatch):
    import json

    from bot import miniapp

    ctx = await setup_owned_run()
    result = await publish(ctx)
    user = await database.get_or_create_user(202)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(202, {"user": user})))
    request = SimpleNamespace(json=AsyncMock(return_value={
        "init_data": "fixture", "source_feed_gen_id": result["card"]["id"],
    }), app={})
    before = await ctx.repo.balance(202)
    response = await miniapp.miniapp_generate_video(request)
    assert response.status == 409
    body = json.loads(response.text)
    assert body["code"] == "genjutsu_recipe_required"
    assert body["recipe_id"] == result["recipe"]["id"]
    assert await ctx.repo.balance(202) == before


@pytest.mark.asyncio
async def test_feed_keyboard_opens_genjutsu_preview_with_author_referral():
    from bot.handlers.common import _build_feed_keyboard

    ctx = await setup_owned_run()
    result = await publish(ctx)
    markup = await _build_feed_keyboard(bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="fixture_bot"))), card=result["card"], source_code="r", index=0, total=1, photo_index=0, photos_count=1)
    buttons = [button for row in markup.inline_keyboard for button in row]
    repeat = next(button for button in buttons if button.text == "🔁 Повторить в Genjutsu")
    from urllib.parse import parse_qs, urlsplit

    assert parse_qs(urlsplit(repeat.web_app.url).query)["startapp"] == [
        f'feed_{result["card"]["id"]}_ref_{ctx.owner.referral_code}'
    ]
    assert "genjutsu_recipe" not in repeat.web_app.url


@pytest.mark.asyncio
async def test_migrations_are_repeatable_and_publish_failure_leaves_no_partial_recipe():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run()
    await ctx.recipes.migrate()
    await ctx.recipes.migrate()
    ctx.copy.side_effect = PipelineError("feed_storage_failed", status=503)
    with pytest.raises(PipelineError, match="feed_storage_failed"):
        await publish(ctx)
    assert await ctx.recipes.list_admin(101) == []
    assert await database.get_feed_generations() == []


@pytest.mark.asyncio
async def test_only_final_step_publishes_and_repeat_preserves_chain_and_variant_count():
    from bot.genjutsu.contract import PipelineError

    ctx = await setup_owned_run(variants=2, step_count=2)
    with pytest.raises(PipelineError, match="completed_output_required"):
        await publish(ctx)
    final_step = ctx.run["steps"][-1]
    result = await publish(ctx, step_id=final_step["id"], source_binding="fixed")
    assert result["recipe"]["variants"] == 2
    assert len(result["recipe"]["steps"]) == 2
    assert len(result["recipe"]["slots"]) == 2
    assert result["recipe"]["current_cost"] > 10
    task = await database.get_task_by_id(result["card"]["task_id"])
    assert task.cost == 20  # The selected variant's two completed steps only.


@pytest.mark.asyncio
async def test_feed_withdrawal_preserves_already_accepted_repeat_and_request_idempotency():
    from bot.genjutsu.contract import asset_ids

    ctx = await setup_owned_run()
    result = await publish(ctx)
    image, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    instance = await ctx.recipes.instantiate(202, result["recipe"]["id"], [image["id"]], {}, source_asset_id=video["id"])
    hidden = await ctx.repo.get_project(202, instance["id"])
    plan, grants, private = await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    settings, version = await ctx.repo.settings()
    assets = await ctx.repo.get_assets(202, asset_ids(plan), grants=grants)
    quote = await ctx.repo.create_quote(202, instance["id"], 1, plan, quote_plan(plan, assets, settings), version, settings, private_recipe=private)
    accepted = await ctx.repo.start(202, "accepted-before-withdrawal", quote["id"])
    balance = await ctx.repo.balance(202)
    before = await ctx.repo.get_run(202, accepted["id"])
    await withdraw(ctx, result["card"]["id"])
    retry = await ctx.repo.start(202, "accepted-before-withdrawal", quote["id"])
    assert retry["id"] == accepted["id"]
    assert await ctx.repo.get_run(202, accepted["id"]) == before
    assert await ctx.repo.balance(202) == balance


@pytest.mark.asyncio
async def test_synthetic_task_does_not_enter_delivery_recovery():
    from bot.services.delivery_state import has_retryable_result

    ctx = await setup_owned_run()
    result = await publish(ctx)
    task = await database.get_task_by_id(result["card"]["task_id"])
    assert has_retryable_result(task) is False


@pytest.mark.asyncio
async def test_profile_only_publication_remains_repeatable_and_full_withdrawal_revokes():
    from bot.genjutsu.contract import PipelineError, asset_ids

    ctx = await setup_owned_run()
    result = await publish(ctx)
    profile = await database.share_to_feed(result["card"]["id"], ctx.owner.id, publication_scope="profile")
    assert profile["publication_scope"] == "profile"
    assert profile["genjutsu_recipe_id"] == result["recipe"]["id"]
    assert await database.get_feed_generation_card(profile["id"]) is None
    assert (await ctx.recipes.public(result["recipe"]["id"]))["id"] == result["recipe"]["id"]
    image, video = await ctx.asset("image", 202), await ctx.asset("video", 202)
    instance = await ctx.recipes.instantiate(202, result["recipe"]["id"], [image["id"]], {}, source_asset_id=video["id"])
    hidden = await ctx.repo.get_project(202, instance["id"])
    plan, grants, private = await ctx.recipes.resolve_project(202, instance["id"], 1, hidden["plan"])
    settings, version = await ctx.repo.settings()
    assets = await ctx.repo.get_assets(202, asset_ids(plan), grants=grants)
    quote = await ctx.repo.create_quote(202, instance["id"], 1, plan, quote_plan(plan, assets, settings), version, settings, private_recipe=private)
    started = await ctx.repo.start(202, "profile-only-repeat", quote["id"])
    assert started["id"]
    with pytest.raises(PipelineError, match="feed_publication_withdrawn"):
        await publish(ctx)
    await withdraw(ctx, profile["id"])
    with pytest.raises(PipelineError, match="recipe_unavailable"):
        await ctx.recipes.public(result["recipe"]["id"])


@pytest.mark.asyncio
async def test_adapter_hidden_from_generic_history_but_owner_publication_detail_is_safe(monkeypatch):
    from bot import miniapp

    ctx = await setup_owned_run()
    result = await publish(ctx)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    recent = await miniapp._fetch_recent_tasks(101)
    assert all(item["task_id"] != result["card"]["task_id"] for item in recent)
    detail = await miniapp._fetch_task_detail(101, result["card"]["task_id"])
    assert detail and detail["status"] == "completed"
    for secret in ("PRIVATE_PROMPT", "PRIVATE_PRESERVE", ctx.source["id"], ctx.fixed["id"]):
        assert secret not in repr(detail)


def test_feed_reference_schema_is_inside_transaction():
    from pathlib import Path

    schema = (Path(__file__).parents[1] / "schema_postgres.sql").read_text()
    assert schema.index("CREATE TABLE IF NOT EXISTS genjutsu_feed_publications") < schema.rindex("COMMIT;")


@pytest.mark.asyncio
async def test_feed_removal_keeps_shared_profile_recipe_available():
    from bot.handlers.publication_scope_compat import remove_from_feed_scoped

    ctx = await setup_owned_run()
    result = await publish(ctx)
    assert await remove_from_feed_scoped(result["card"]["id"], ctx.owner.id)
    assert await database.get_feed_generation_card(result["card"]["id"]) is None
    profile = await database.get_profile_generation_card(result["card"]["id"])
    assert profile["genjutsu_recipe_id"] == result["recipe"]["id"]
    assert (await ctx.recipes.public(result["recipe"]["id"]))["id"] == result["recipe"]["id"]


@pytest.mark.asyncio
async def test_admin_recipe_list_keeps_curated_recipes_when_feed_publication_is_withdrawn():
    ctx = await setup_owned_run()
    published = await publish(ctx)
    ctx.repo.verified_admin_run = AsyncMock(return_value=True)
    curated = await ctx.recipes.publish(
        101, ctx.project["id"], 1, "Curated recipe", [], ctx.run["id"],
    )
    await withdraw(ctx, published["card"]["id"])
    response = await ctx.api.dispatch(101, True, "recipe_list", {"action": "recipe_list"})
    assert [item["id"] for item in response["items"]] == [curated["id"]]
    assert response["items"][0]["title"] == "Curated recipe"


@pytest.mark.asyncio
@pytest.mark.parametrize("viewer,admin", [(101, False), (202, False), (202, True)])
@pytest.mark.parametrize("profile_only", [False, True])
async def test_recipe_link_preview_returns_public_card_without_private_inputs(viewer, admin, profile_only):
    ctx = await setup_owned_run()
    published = await publish(ctx)
    if profile_only:
        published["card"] = await database.share_to_feed(published["card"]["id"], ctx.owner.id, publication_scope="profile")
    ctx.api.authenticate = AsyncMock(return_value=(viewer, admin))
    before = await ctx.repo.balance(viewer)
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={
            "action": "recipe_preview", "recipe_id": published["recipe"]["id"], "init_data": "fixture",
        })
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"
        result = await response.json()
    assert set(result) == {"ok", "card"}
    card = result["card"]
    assert card["id"] == published["card"]["id"]
    assert card["genjutsu_recipe_id"] == published["recipe"]["id"]
    assert card["result_url"] == published["card"]["result_url"]
    assert card["author_referral_code"] == ctx.owner.referral_code
    assert card["is_mine"] is (viewer == 101)
    assert bool(card.get("can_remove")) is admin
    assert bool(card.get("can_blur")) is (admin or viewer == 101)
    assert card["prompt"] == ""
    assert card["reference_images"] == card["reference_videos"] == []
    for secret in ("PRIVATE_PROMPT", "PRIVATE_PRESERVE", "PRIVATE_FIXED_LABEL",
                   ctx.source["id"], ctx.photo["id"], ctx.fixed["id"], ctx.output["storage_key"]):
        assert secret not in repr(result)
    assert await ctx.repo.balance(viewer) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("state", [
    "withdrawn", "deleted", "archived", "failed", "missing_media", "wrong_model", "wrong_recipe", "empty_binding",
])
async def test_bound_recipe_preview_fails_closed_instead_of_opening_editor(state, admin):
    from bot.genjutsu.repository import encode

    ctx = await setup_owned_run()
    published = await publish(ctx)
    card_id, recipe_id = published["card"]["id"], published["recipe"]["id"]
    ctx.api.authenticate = AsyncMock(return_value=(202, admin))
    if state == "withdrawn":
        await withdraw(ctx, card_id)
    elif state == "archived":
        await ctx.recipes.archive(101, recipe_id)
    else:
        async with ctx.repo.transaction() as db:
            if state == "deleted":
                await db.execute("DELETE FROM generation_tasks WHERE id=?", (card_id,))
            elif state == "failed":
                await db.execute("UPDATE generation_tasks SET status='failed' WHERE id=?", (card_id,))
            elif state == "missing_media":
                await db.execute("UPDATE generation_tasks SET result_url=NULL,result_urls='[]' WHERE id=?", (card_id,))
            elif state == "wrong_model":
                await db.execute("UPDATE generation_tasks SET model='kling' WHERE id=?", (card_id,))
            elif state == "empty_binding":
                await db.execute("UPDATE genjutsu_feed_publications SET task_id='' WHERE recipe_id=?", (recipe_id,))
            else:
                await db.execute("UPDATE generation_tasks SET request_data=? WHERE id=?",
                                 (encode({"genjutsu_recipe_id": "0" * 32}), card_id))
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={
            "action": "recipe_preview", "recipe_id": recipe_id,
        })
        assert response.status == 404
        result = await response.json()
    assert result["code"] == "recipe_unavailable"
    assert "card" not in result
    assert "PRIVATE_" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_unbound_curated_recipe_preview_preserves_editor_only_while_active(archived):
    ctx = await setup_owned_run()
    async with ctx.repo.transaction() as db:
        await db.execute("UPDATE genjutsu_runs SET admin_free=1 WHERE id=?", (ctx.run["id"],))
    recipe = await ctx.recipes.publish(
        101, ctx.project["id"], 1, "Curated recipe", [], ctx.run["id"],
    )
    if archived:
        await ctx.recipes.archive(101, recipe["id"])
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={
            "action": "recipe_preview", "recipe_id": recipe["id"],
        })
        result = await response.json()
    if archived:
        assert response.status == 404
        assert result["code"] == "recipe_unavailable"
    else:
        assert response.status == 200
        assert result == {"ok": True, "card": None}


@pytest.mark.asyncio
async def test_recipe_preview_requires_authentication_before_resolving_any_card():
    ctx = await setup_owned_run()
    published = await publish(ctx)
    ctx.api.authenticate = AsyncMock(side_effect=PermissionError("fixture unauthenticated"))
    preview = AsyncMock()
    ctx.recipes.preview = preview
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={
            "action": "recipe_preview", "recipe_id": published["recipe"]["id"],
        })
        assert response.status == 403
        assert (await response.json())["code"] == "unauthorized"
    preview.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [
    ({"recipe_id": "0" * 32}, 404),
    ({"recipe_id": "short"}, 404),
    ({}, 400),
    ({"recipe_id": None}, 400),
    ({"recipe_id": "0" * 32, "viewer_user_id": 1}, 400),
    ({"recipe_id": "0" * 32, "admin": True}, 400),
    ({"recipe_id": "0" * 32, "plan": {}}, 400),
])
async def test_recipe_preview_rejects_unknown_recipe_and_untrusted_fields(body, status):
    ctx = await setup_owned_run()
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={"action": "recipe_preview", **body})
        assert response.status == status
        assert "card" not in await response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["archive", "withdraw"])
async def test_recipe_preview_fails_closed_if_publication_is_revoked_during_resolution(change, monkeypatch):
    ctx = await setup_owned_run()
    published = await publish(ctx)
    get_card = database.get_profile_generation_card

    async def revoke_after_card(*args, **kwargs):
        card = await get_card(*args, **kwargs)
        if change == "archive":
            await ctx.recipes.archive(101, published["recipe"]["id"])
        else:
            await withdraw(ctx, published["card"]["id"])
        return card

    monkeypatch.setattr(database, "get_profile_generation_card", revoke_after_card)
    app = web.Application()
    ctx.api.register(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mini-app/api/genjutsu", json={
            "action": "recipe_preview", "recipe_id": published["recipe"]["id"],
        })
        assert response.status == 404
        assert (await response.json())["code"] == "recipe_unavailable"
