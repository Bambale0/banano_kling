"""A signed VK-only actor may repeat only editor-approved simple video trends."""
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database, trend_catalog
from bot.shared_accounts import api


PROMPT = {
    "id": 31, "status": "approved", "is_public": True, "tags": ["trend"],
    "prompt_text": "Two friendly foxes wave", "model": "v3_std",
    "generation_settings": {
        "kind": "video", "model": "v3_std", "user_input": "photo",
        "scenario": "imgtxt", "ratio": "16:9", "duration": 5, "count": 1,
    },
}
CATALOG = {
    "ok": True, "photo_models": [], "video_models": [{
        "id": "v3_std", "ratios": ["16:9"], "durations": [5],
        "scenarios": ["imgtxt"], "max_image_references": 1,
    }],
}
PHOTO = "https://neuromixbot.com/uploads/vk-refs/image/2001/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg"
KEY = "vk_0123456789abcdef0123456789abcdef"


def _request():
    return make_mocked_request("POST", "/mini-app/api/account-preview/vk-trend")


def _mock(monkeypatch, *, quote_only=False, assets=None, visible=True):
    monkeypatch.setenv("VK_MINIAPP_VIDEO_WRITES_ENABLED", "1")
    monkeypatch.delenv("VK_MINIAPP_WRITES_ENABLED", raising=False)
    owner = AsyncMock(return_value=2001)
    monkeypatch.setattr(api, "_vk_writer_actor", owner)
    monkeypatch.setattr(api, "_body", AsyncMock(return_value={
        "trend_id": 31, "reference_urls": [PHOTO], "user_values": {},
        "quote_only": quote_only,
        **({} if quote_only else {"client_request_id": KEY, "expected_cost": 12}),
    }))
    monkeypatch.setattr(
        trend_catalog, "public_trend_by_id",
        AsyncMock(return_value=PROMPT if visible else None),
    )
    monkeypatch.setattr(database, "get_prompt_by_id", AsyncMock(return_value=PROMPT))
    monkeypatch.setattr(database, "list_trend_reference_assets", AsyncMock(return_value=assets or []))
    def owned(actor, urls):
        assert actor == 2001 and urls == [PHOTO]
        return [PHOTO]
    monkeypatch.setattr(api, "verified_image_urls", owned)
    monkeypatch.setattr(api, "fetch_native_vk_models", AsyncMock(return_value=CATALOG))
    native = AsyncMock(return_value={"task_id": 77, "cost": 12})
    monkeypatch.setattr(api, "submit_native_vk_video", native)
    image = AsyncMock()
    monkeypatch.setattr(api, "submit_native_vk_image", image)
    return owner, native, image


@pytest.mark.asyncio
async def test_signed_vk_video_trend_uses_owner_wallet_without_leaking_hidden_prompt(monkeypatch):
    owner, native, image = _mock(monkeypatch)
    result = await api.vk_native_trend(_request())
    assert result.status == 200
    assert json.loads(result.text) == {"ok": True, "task_id": 77, "cost": 12}
    native.assert_awaited_once_with(2001, {
        "model": "v3_std", "prompt": "Two friendly foxes wave",
        "aspect": "16:9", "duration": 5,
        "reference_photos": [PHOTO],
        "client_request_id": KEY, "expected_cost": 12,
    })
    owner.assert_awaited_once()
    image.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_video_trend_quote_has_no_charge_or_client_cost(monkeypatch):
    _, native, _ = _mock(monkeypatch, quote_only=True)
    result = await api.vk_native_trend(_request())
    assert result.status == 200
    body = native.await_args.args[1]
    assert body["quote_only"] is True
    assert "expected_cost" not in body
    assert "client_request_id" not in body


@pytest.mark.asyncio
async def test_hidden_editor_assets_block_native_video_execution(monkeypatch):
    _, native, image = _mock(monkeypatch, assets=[{"media_type": "video"}])
    with pytest.raises(ValueError, match="Protected"):
        await api.vk_native_trend(_request())
    native.assert_not_awaited()
    image.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlisted_editor_trend_cannot_be_executed_by_guessing_its_id(monkeypatch):
    _, native, image = _mock(monkeypatch, visible=False)
    with pytest.raises(ValueError, match="unavailable"):
        await api.vk_native_trend(_request())
    native.assert_not_awaited()
    image.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_video_trend_flag_disabled_cannot_execute_paid_request(monkeypatch):
    _, native, image = _mock(monkeypatch)
    monkeypatch.delenv("VK_MINIAPP_VIDEO_WRITES_ENABLED")
    result = await api.vk_native_trend(_request())
    assert result.status == 404
    native.assert_not_awaited()
    image.assert_not_awaited()


def test_video_trend_public_card_advertised_only_when_native_flag_enabled(monkeypatch):
    monkeypatch.delenv("VK_MINIAPP_WRITES_ENABLED", raising=False)
    monkeypatch.delenv("VK_MINIAPP_VIDEO_WRITES_ENABLED", raising=False)
    card = {**PROMPT, "title": "Foxes", "description": "",
            "generation_settings": dict(PROMPT["generation_settings"])}
    closed = api._vk_public_trend_card(card, vk_app_id=54880352)
    assert closed["can_repeat_in_app"] is False
    monkeypatch.setenv("VK_MINIAPP_VIDEO_WRITES_ENABLED", "1")
    allowed = api._vk_public_trend_card(card, vk_app_id=54880352)
    assert allowed["can_repeat_in_app"] is True
    assert "prompt_text" not in allowed
    card["generation_settings"]["reference_contract"] = "hidden"
    assert api._vk_public_trend_card(card, vk_app_id=54880352)["can_repeat_in_app"] is False
