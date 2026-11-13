"""Regression: VK feed repeat is not an editorial trend and never owns TG money."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database
from bot.shared_accounts import api
from bot.shared_accounts.vk_feed_repeat import (
    build_vk_feed_repeat,
    native_vk_feed_repeat_model,
)

KEY = "vk_feed_repeat_0123456789abcdef"
PHOTO = "https://neuromixbot.com/uploads/vk-refs/image/2001/owned.jpg"
CARD = {
    "id": 345, "gen_type": "image", "model": "banana_pro",
    "publication_scope": "feed", "prompt_hidden": False,
    "feed_prompt_visible": True, "prompt_actions_allowed": True,
    "feed_blurred": False, "media_unavailable": False,
    "prompt": "A brightly lit portrait", "aspect_ratio": "1:1",
    # Private historical inputs must NEVER appear in the worker payload.
    "reference_images": ["https://private.invalid/author-face.jpg"],
    "reference_videos": [],
}
CATALOG = {
    "ok": True, "video_models": [], "photo_models": [{
        "id": "nano_banana_pro", "ratios": ["1:1", "16:9"],
        "resolutions": ["4K", "2K"], "max_references": 3,
    }],
}


def test_only_explicitly_public_image_recipe_can_be_repeated():
    assert native_vk_feed_repeat_model(CARD) == "nano_banana_pro"
    for override in (
        {"gen_type": "video"},
        {"publication_scope": "profile"},
        {"prompt_hidden": True},
        {"feed_prompt_visible": False},
        {"prompt_actions_allowed": False},
        {"feed_blurred": True},
        {"media_unavailable": True},
        {"prompt": ""},
        {"model": "unauthorized_model"},
    ):
        assert native_vk_feed_repeat_model({**CARD, **override}) is None


def test_native_worker_uses_visible_server_prompt_and_fresh_vk_owned_inputs():
    result = build_vk_feed_repeat(
        CARD, CATALOG, [PHOTO], quote_only=False,
        client_request_id=KEY, expected_cost=7.5,
    )
    assert result == {
        "model": "nano_banana_pro", "prompt": "A brightly lit portrait",
        "aspect": "1:1", "resolution": "4K", "reference_photos": [PHOTO],
        "client_request_id": KEY, "expected_cost": 7.5,
    }
    assert "https://private.invalid/author-face.jpg" not in str(result)
    assert "telegram_id" not in result
    assert "feed_gen_id" not in result


def test_quote_does_not_commit_or_include_client_cost_or_key():
    result = build_vk_feed_repeat(
        CARD, CATALOG, [], quote_only=True,
        client_request_id=None, expected_cost=None,
    )
    assert result["quote_only"] is True
    assert "expected_cost" not in result
    assert "client_request_id" not in result


@pytest.mark.parametrize("catalog,refs", [
    ({**CATALOG, "ok": False}, []),
    ({"ok": True, "photo_models": []}, []),
    (CATALOG, [PHOTO] * 2),
    (CATALOG, [f"https://example.invalid/{i}.jpg" for i in range(4)]),
    ({"ok": True, "photo_models": [{
        "id": "nano_banana_pro", "ratios": ["9:16"], "resolutions": ["2K"],
        "max_references": 3,
    }]}, []),
])
def test_native_catalog_and_input_restrictions_fail_closed(catalog, refs):
    with pytest.raises(ValueError):
        build_vk_feed_repeat(
            CARD, catalog, refs, quote_only=True,
            client_request_id=None, expected_cost=None,
        )


@pytest.mark.parametrize("key,cost", [
    ("short", 7),
    (KEY, -1),
    (KEY, 0),
    (KEY, float("nan")),
    (KEY, True),
])
def test_paid_feed_repeat_requires_stable_claim_and_native_quote(key, cost):
    with pytest.raises(ValueError):
        build_vk_feed_repeat(
            CARD, CATALOG, [], quote_only=False,
            client_request_id=key, expected_cost=cost,
        )


def _request():
    return make_mocked_request("POST", "/mini-app/api/account-preview/vk-feed-repeat")


def _mock(monkeypatch, *, source=CARD, quote=False, assets=None):
    monkeypatch.setenv("VK_MINIAPP_FEED_REPEAT_ENABLED", "1")
    monkeypatch.setenv("VK_MINIAPP_WRITES_ENABLED", "1")
    actor = AsyncMock(return_value=2001)
    monkeypatch.setattr(api, "_vk_writer_actor", actor)
    monkeypatch.setattr(api, "_body", AsyncMock(return_value={
        "feed_gen_id": 345, "reference_urls": [PHOTO],
        "quote_only": quote,
        **({} if quote else {"client_request_id": KEY, "expected_cost": 7.5}),
    }))
    source_read = AsyncMock(return_value=source)
    monkeypatch.setattr(database, "get_feed_generation_card", source_read)
    def verify(owner, urls):
        assert owner == 2001 and urls == [PHOTO]
        return [PHOTO]
    monkeypatch.setattr(api, "verified_image_urls", verify)
    model_read = AsyncMock(return_value=CATALOG)
    monkeypatch.setattr(api, "fetch_native_vk_models", model_read)
    submit = AsyncMock(return_value={"task_id": 84, "cost": 7.5})
    monkeypatch.setattr(api, "submit_native_vk_image", submit)
    return actor, source_read, model_read, submit


@pytest.mark.asyncio
async def test_signed_native_vk_repeat_uses_only_owner_verified_refs(monkeypatch):
    actor, source_read, _, submit = _mock(monkeypatch)
    response = await api.vk_native_feed_repeat(_request())
    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "task_id": 84, "cost": 7.5}
    actor.assert_awaited_once()
    source_read.assert_awaited_once_with(345, viewer_user_id=None)
    submit.assert_awaited_once_with(2001, {
        "model": "nano_banana_pro", "prompt": CARD["prompt"],
        "aspect": "1:1", "resolution": "4K", "reference_photos": [PHOTO],
        "client_request_id": KEY, "expected_cost": 7.5,
    })


@pytest.mark.asyncio
async def test_vk_feed_repeat_quote_cannot_charge_and_uses_live_worker_price(monkeypatch):
    _, _, _, submit = _mock(monkeypatch, quote=True)
    response = await api.vk_native_feed_repeat(_request())
    assert response.status == 200
    payload = submit.await_args.args[1]
    assert payload["quote_only"] is True
    assert "expected_cost" not in payload
    assert "client_request_id" not in payload


@pytest.mark.asyncio
async def test_private_feed_recipe_rejected_before_provider_or_catalog(monkeypatch):
    _, _, model_read, submit = _mock(monkeypatch, source={**CARD, "prompt_hidden": True})
    with pytest.raises(ValueError, match="not permitted"):
        await api.vk_native_feed_repeat(_request())
    model_read.assert_not_awaited()
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_unpublishes_between_quote_and_submit(monkeypatch):
    _, source_read, _, submit = _mock(monkeypatch)
    source_read.side_effect = [CARD, None]
    first = await api.vk_native_feed_repeat(_request())
    assert first.status == 200
    with pytest.raises(ValueError, match="not permitted"):
        await api.vk_native_feed_repeat(_request())
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_feed_repeat_requires_both_flags_even_for_quote(monkeypatch):
    _, source_read, _, submit = _mock(monkeypatch)
    monkeypatch.delenv("VK_MINIAPP_FEED_REPEAT_ENABLED")
    response = await api.vk_native_feed_repeat(_request())
    assert response.status == 404
    source_read.assert_not_awaited()
    submit.assert_not_awaited()


def test_public_feed_card_advertises_only_server_checked_repeat(monkeypatch):
    monkeypatch.setenv("VK_MINIAPP_WRITES_ENABLED", "1")
    monkeypatch.delenv("VK_MINIAPP_FEED_REPEAT_ENABLED", raising=False)
    card = {**CARD, "likes_count": 4, "shares_count": 0, "comments_count": 0,
            "result_url": "https://example.test/public.jpg", "preview_url": None}
    denied = api._vk_public_feed_card(card, vk_app_id=123)
    assert denied["can_repeat_in_app"] is False
    monkeypatch.setenv("VK_MINIAPP_FEED_REPEAT_ENABLED", "1")
    allowed = api._vk_public_feed_card(card, vk_app_id=123)
    assert allowed["can_repeat_in_app"] is True
    assert "prompt" not in allowed
    assert "reference_images" not in allowed
    card["prompt_hidden"] = True
    assert api._vk_public_feed_card(card, vk_app_id=123)["can_repeat_in_app"] is False
