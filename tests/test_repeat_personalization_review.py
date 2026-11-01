"""Regression coverage for the installed publication/repeat paths (PR 382 review)."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from bot import database, miniapp
from bot import repeat_personalization as personalization
from bot.handlers import feed_model_filter_compat, publication_scope_compat
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan
from tests.test_wan3_feed_repeat import (
    FIXED,
    SECRET,
    USER_FACE,
    VIDEO,
    published_source,
)
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, balance, user_actor


@pytest.mark.parametrize("endpoint", ["feed", "profile"])
@pytest.mark.parametrize("admin,flag", [(True, "1"), (False, "1"), (True, "0")])
async def test_installed_feed_wrappers_attach_only_admin_safe_fields(monkeypatch, endpoint, admin, flag):
    monkeypatch.setenv(personalization.FEATURE_FLAG, flag)
    fields = personalization.normalize_repeat_fields([{
        "key": "clothes", "label": "Одежда", "original_value": "blue coat", "choices": ["red dress"],
    }], prompt="Private scene in a blue coat")
    await personalization.save_repeat_fields(42, fields, actor_telegram_id=123)
    viewer = SimpleNamespace(id=7, referral_code="MINE")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: admin)
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value={"referral_code": "MINE"}))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": viewer})))
    cards = [{"id": 42, "model": "banana_pro", "gen_type": "image"}]
    monkeypatch.setattr(feed_model_filter_compat, "filter_feed_cards", AsyncMock(return_value=cards))
    monkeypatch.setattr(feed_model_filter_compat, "_published_model_ids", AsyncMock(return_value=["banana_pro"]))
    monkeypatch.setattr(miniapp, "get_user_feed_generations", AsyncMock(return_value=cards))
    monkeypatch.setattr(miniapp, "get_user_feed_summary", AsyncMock(return_value={}))
    monkeypatch.setattr(miniapp, "_miniapp_profile_payload", lambda *_args, **_kw: {})
    async def response(payload, _telegram_id):
        return web.json_response(payload)
    monkeypatch.setattr(miniapp.creator_tariff_display, "priced_feed_response", response)
    request = SimpleNamespace(app={"bot": SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test")))})
    result = await (miniapp.miniapp_feed if endpoint == "feed" else miniapp.miniapp_profile_feed)(request)
    assert result.status == 200, result.text
    card = json.loads(result.text)["feed"][0]
    if admin and flag == "1":
        assert card["repeat_user_fields"][0]["choices"] == ["red dress"]
    else:
        assert "repeat_user_fields" not in card
    assert "original_value" not in result.text and "blue coat" not in result.text


def test_invalid_numeric_choice_rejected_when_author_saves():
    with pytest.raises(ValueError, match="числом"):
        personalization.normalize_repeat_fields([{
            "key": "age", "label": "Возраст", "original_value": "18", "choices": ["18 лет"],
        }], prompt="Birthday age 18")


@pytest.mark.parametrize("path", ["telegram_hide", "admin_remove"])
async def test_every_full_removal_clears_fields_with_flag_off(monkeypatch, path):
    owner, source_id = await published_source()
    fields = personalization.normalize_repeat_fields([{
        "key": "clothes", "label": "Одежда", "original_value": "clothing", "choices": ["red dress"],
    }], prompt=SECRET)
    await personalization.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)
    monkeypatch.setenv(personalization.FEATURE_FLAG, "0")
    if path == "telegram_hide":
        assert await publication_scope_compat.remove_publication("wan3_author_source", owner.user_id)
    else:
        assert await publication_scope_compat.remove_from_feed_scoped("wan3_author_source", owner.user_id, allow_any_user=True)
    assert await personalization.get_repeat_fields(source_id) == []


@pytest.mark.parametrize("model", ["wan_3", "wan_3_prime"])
async def test_wan_admin_repeat_applies_choices_preserves_prompt_refs_and_idempotency(monkeypatch, model):
    monkeypatch.setenv(personalization.FEATURE_FLAG, "1")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda tid: tid == 991202)
    owner, source_id = await published_source()
    if model == "wan_3":
        async with database.db_backend.connect(database.DATABASE_PATH) as db:
            await db.execute("UPDATE generation_tasks SET model = ? WHERE id = ?", (model, source_id))
            await db.commit()
    actor = await user_actor(100, telegram_id=991202)
    fields = personalization.normalize_repeat_fields([{
        "key": "clothes", "label": "Одежда", "original_value": "clothing", "choices": ["red dress"],
    }], prompt=SECRET)
    await personalization.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)
    plan = public_plan(await get_repeat_plan(actor, source_id))
    assert plan["repeat_user_fields"][0]["choices"] == ["red dress"]
    assert SECRET not in json.dumps(plan) and "original_value" not in json.dumps(plan)
    class ModelPrices(Prices):
        def get_video_quality_costs(self, _model):
            return dict(self.rates)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=ModelPrices(), transport=provider)
    recipe = {**plan["recipe"], "source_feed_gen_id": source_id, "repeat_plan_hash": plan["repeat_plan_hash"],
              "repeat_replacements": {"image:0": USER_FACE}, "prompt": "Keep the camera",
              "repeat_user_values": {"clothes": "red dress"}}
    quote = await lifecycle.quote(actor, recipe)
    launched = await lifecycle.launch(actor, recipe, quote, "personalized-once")
    assert "red dress" in provider.recipe.prompt and "clothing" not in provider.recipe.prompt
    assert "Author private editing recipe" in provider.recipe.prompt and "Keep the camera" in provider.recipe.prompt
    assert provider.recipe.reference_video_urls == [VIDEO]
    assert provider.recipe.reference_image_urls == [USER_FACE, FIXED]
    again = await lifecycle.launch(actor, recipe, quote, "personalized-once")
    assert again["task_id"] == launched["task_id"] and provider.creates == 1
    source = await database.get_generation_task_payload(source_id)
    assert source["prompt"] == SECRET


@pytest.mark.parametrize("admin,flag", [(False, "1"), (True, "0")])
@pytest.mark.parametrize("source", [False, True])
async def test_wan_structured_payload_denied_before_probe_or_billing(monkeypatch, admin, flag, source):
    monkeypatch.setenv(personalization.FEATURE_FLAG, flag)
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: admin)
    actor = await user_actor(100, telegram_id=991202)
    probe = Probe()
    probe.probe_url = AsyncMock(side_effect=AssertionError("must reject before media/provider"))
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=probe, preset_manager=Prices(), transport=provider)
    recipe = {"model": "wan_3_prime", "scenario": "text", "prompt": "scene", "duration": 5,
              "repeat_user_values": {"clothes": "red dress"}}
    if source:
        recipe["source_feed_gen_id"] = 42
    with pytest.raises(Wan3PrimeValidationError) as error:
        await lifecycle.quote(actor, recipe)
    assert error.value.status == 403
    assert provider.creates == 0 and await balance(actor.user_id) == 100
    probe.probe_url.assert_not_awaited()

def test_replacement_cannot_change_another_fields_inserted_value():
    fields = personalization.normalize_repeat_fields([
        {"key": "clothes", "label": "Одежда", "original_value": "blue coat", "choices": ["chocolate cake"]},
        {"key": "object", "label": "Предмет", "original_value": "chocolate cake", "choices": ["apple"]},
    ], prompt="A blue coat and a chocolate cake")
    rendered = personalization.render_repeat_base("A blue coat and a chocolate cake", fields,
                                                 {"clothes": "chocolate cake", "object": "apple"})
    assert rendered.startswith("A chocolate cake and a apple")


async def test_postgres_cleanup_locks_parent_before_config(monkeypatch):
    calls = []
    class DB:
        async def execute(self, sql, params=()):
            calls.append(" ".join(sql.split()))
    monkeypatch.setattr(publication_scope_compat.db_backend, "is_postgres", lambda: True)
    await publication_scope_compat._clear_repeat_fields_in_transaction(DB(), 42, 7)
    assert calls[0] == "SELECT id FROM generation_tasks WHERE id = ? FOR UPDATE"
    assert calls[1].startswith("UPDATE generation_repeat_personalization")


async def test_wan_config_change_after_compilation_is_rejected_in_reservation(monkeypatch):
    from bot.services.wan3_prime_repeat import verify_repeat_in_transaction
    monkeypatch.setenv(personalization.FEATURE_FLAG, "1")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: True)
    owner, source_id = await published_source()
    actor = await user_actor(100, telegram_id=991202)
    raw = [{"key": "clothes", "label": "Одежда", "original_value": "clothing", "choices": ["red dress"]}]
    fields = personalization.normalize_repeat_fields(raw, prompt=SECRET)
    await personalization.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)
    plan = public_plan(await get_repeat_plan(actor, source_id))
    body = {**plan["recipe"], "source_feed_gen_id": source_id, "repeat_plan_hash": plan["repeat_plan_hash"],
            "repeat_replacements": {"image:0": USER_FACE}, "repeat_user_values": {"clothes": "red dress"}}
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=Provider())
    compiled = await lifecycle._validated_recipe(actor, body)
    fields[0]["choices"] = ["black suit"]
    await personalization.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = database.db_backend.Row
        with pytest.raises(Wan3PrimeValidationError, match="Параметры повтора изменились"):
            await verify_repeat_in_transaction(db, compiled.repeat_context)
    assert await balance(actor.user_id) == 100
