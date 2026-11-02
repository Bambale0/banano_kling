"""Public launch keeps owner, prompt, reference and billing boundaries."""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from bot import database, miniapp
from bot import repeat_personalization as rp
from bot.handlers.publication_scope_compat import _miniapp_generation_share_scoped
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan
from tests.test_wan3_feed_repeat import (
    FIXED,
    SECRET,
    USER_FACE,
    VIDEO,
    published_source,
)
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, balance, user_actor

PUBLIC_FLAG = "REPEAT_PERSONALIZATION_PUBLIC_ENABLED"


@pytest.mark.parametrize("public,preview,admin,actor,allowed", [
    ("1", "0", False, 42, True), ("1", "1", False, 42, True),
    ("0", "1", False, 42, False), ("0", "1", True, 42, True),
    ("0", "0", True, 42, False), ("1", "1", False, 0, False),
])
def test_access_matrix(monkeypatch, public, preview, admin, actor, allowed):
    monkeypatch.setenv(PUBLIC_FLAG, public)
    monkeypatch.setenv(rp.FEATURE_FLAG, preview)
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: admin)
    assert miniapp._repeat_personalization_allowed(actor) is allowed


@pytest.mark.parametrize("foreign", [False, True])
async def test_public_author_save_and_owner_boundary(monkeypatch, foreign):
    monkeypatch.setenv(PUBLIC_FLAG, "1")
    monkeypatch.setenv(rp.FEATURE_FLAG, "0")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: False)
    owner, source_id = await published_source()
    viewer = await user_actor(100, telegram_id=991202) if foreign else owner
    user = await database.get_or_create_user(viewer.telegram_id)
    fields = [{"key":"clothes", "label":"Одежда", "original_value":"clothing",
               "choices":["red dress","black suit"]}]
    body = {"init_data":"signed", "task_id":"wan3_author_source",
            "publication_scope":"feed", "repeat_user_fields":fields,
            "repeat_reference_image_indices":[1], "repeat_reference_video_indices":[0]}
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(viewer.telegram_id, {"user":user})))
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(return_value=body))
    request = SimpleNamespace(app={"bot":SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test")))})
    before = await database.get_generation_task_payload(source_id)
    result = await _miniapp_generation_share_scoped(miniapp, request)
    if foreign:
        assert result.status == 404, result.text
        assert await rp.get_repeat_fields(source_id) == []
        return
    assert result.status == 200, result.text
    saved = await rp.get_repeat_fields(source_id)
    assert saved[0]["choices"] == fields[0]["choices"]
    cards = [{"id":source_id}]
    await miniapp._attach_repeat_personalization(cards, telegram_id=viewer.telegram_id)
    assert cards[0]["repeat_user_fields"][0]["choices"] == fields[0]["choices"]
    assert "original_value" not in json.dumps(cards)
    after = await database.get_generation_task_payload(source_id)
    assert after["prompt"] == before["prompt"] == SECRET
    assert after["request_data"] == before["request_data"]


@pytest.mark.parametrize("model", ["wan_3", "wan_3_prime"])
async def test_public_wan_choice_keeps_media_and_charges_only_once(monkeypatch, model):
    monkeypatch.setenv(PUBLIC_FLAG, "1")
    monkeypatch.setenv(rp.FEATURE_FLAG, "0")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: False)
    owner, source_id = await published_source()
    if model == "wan_3":
        async with database.db_backend.connect(database.DATABASE_PATH) as conn:
            await conn.execute("UPDATE generation_tasks SET model = ? WHERE id = ?", (model, source_id))
            await conn.commit()
    fields = rp.normalize_repeat_fields([{"key":"clothes","label":"Одежда",
        "original_value":"clothing","choices":["red dress"]}], prompt=SECRET)
    await rp.save_repeat_fields(source_id, fields, actor_telegram_id=owner.telegram_id)
    actor = await user_actor(100, telegram_id=991202)
    plan = public_plan(await get_repeat_plan(actor, source_id))
    assert plan["repeat_user_fields"][0]["choices"] == ["red dress"]
    assert "original_value" not in json.dumps(plan) and SECRET not in json.dumps(plan)
    class ModelPrices(Prices):
        def get_video_quality_costs(self, _model):
            return dict(self.rates)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=ModelPrices(), transport=provider)
    recipe = {**plan["recipe"], "source_feed_gen_id":source_id, "repeat_plan_hash":plan["repeat_plan_hash"],
        "repeat_replacements":{"image:0":USER_FACE}, "repeat_user_values":{"clothes":"red dress"}}
    quote = await lifecycle.quote(actor, recipe)
    assert quote.admin_free is False and quote.reserve_credits > 0
    first = await lifecycle.launch(actor, recipe, quote, "public-choice-once")
    second = await lifecycle.launch(actor, recipe, quote, "public-choice-once")
    assert first["task_id"] == second["task_id"] and provider.creates == 1
    assert await balance(actor.user_id) == 100 - quote.reserve_credits
    assert provider.recipe.reference_image_urls == [USER_FACE, FIXED]
    assert provider.recipe.reference_video_urls == [VIDEO]
    assert "red dress" in provider.recipe.prompt and "clothing" not in provider.recipe.prompt


@pytest.mark.parametrize("public,expected", [("1",200),("0",403)])
async def test_public_catalog_upload_gate(monkeypatch, tmp_path, public, expected):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PUBLIC_FLAG, public)
    monkeypatch.setenv(rp.FEATURE_FLAG, "0")
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _id: False)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(42, {})))
    raw = io.BytesIO()
    Image.new("RGB",(3,3),"red").save(raw,format="PNG")
    body={"init_data":"signed","file_kind":"repeat_choice_image","filename":"red.png",
          "content_type":"image/png","data_base64":base64.b64encode(raw.getvalue()).decode()}
    response=await miniapp.miniapp_upload(SimpleNamespace(content_type="application/json",
                                                        json=AsyncMock(return_value=body),app={}))
    assert response.status == expected, response.text
    if public == "1":
        assert "/uploads/repeat-choices/" in json.loads(response.text)["url"]
