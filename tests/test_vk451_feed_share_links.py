"""VK #451: publicly published feed links must open native VK, never TG."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database
from bot.shared_accounts import api


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vk_app_id,vk_community_id,expected_link",
    [
        (54880352, 239915802, "https://vk.com/app54880352_-239915802#feed_145"),
        (54880352, None, "https://vk.com/app54880352#feed_145"),
        (None, None, None),
    ],
)
async def test_native_vk_feed_list_links_are_public_actor_scoped_and_do_not_leak_recipe(
    monkeypatch, vk_app_id, vk_community_id, expected_link,
):
    policy = SimpleNamespace(
        enabled=True,
        revision=1,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
        allows_public=lambda actor: actor.platform == "vk",
    )
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=policy))
    monkeypatch.setattr(
        api, "get_session",
        AsyncMock(return_value=SimpleNamespace(
            identity=SimpleNamespace(platform="vk"),
        )),
    )
    rows = AsyncMock(return_value=[{
        "id": 145, "gen_type": "video",
        "preview_url": "https://example.invalid/preview.jpg",
        "result_url": "https://example.invalid/movie.mp4",
        "likes_count": 4,
        "prompt": "PRIVATE FULL PROMPT",
        "reference_images": ["https://example.invalid/private.jpg"],
    }])
    monkeypatch.setattr(database, "get_feed_generations", rows)
    req = make_mocked_request(
        "GET", "/mini-app/api/account-preview/trends?view=feed",
        headers={"Authorization": "Bearer valid-session"},
    )
    result = await api.vk_public_discovery(req)
    assert result.status == 200
    data = json.loads(result.text)
    assert data["ok"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["id"] == 145
    assert item["generation_type"] == "video"
    assert item["share_link"] == expected_link
    assert "prompt" not in item
    assert "reference_images" not in item
    assert "PRIVATE FULL PROMPT" not in result.text
    assert "t.me/" not in result.text
    rows.assert_awaited_once_with(
        limit=18, source="recent", viewer_user_id=None,
        include_unavailable=False,
    )
