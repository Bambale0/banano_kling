"""VK-only actors can read common public-feed comments without TG identity."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import database
from bot.shared_accounts import api
from bot.shared_accounts.actor import PlatformActor


def _request(gen_id="41"):
    return make_mocked_request(
        "GET", "/mini-app/api/account-preview/vk-feed-comments?feed_gen_id=" + gen_id,
        headers={"Authorization": "Bearer vk-only-session"},
    )


@pytest.mark.asyncio
async def test_native_vk_reads_only_public_common_feed_comments(monkeypatch):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="independent-vk",
        linked_platforms=("vk",), linked_telegram_id=None,
    )
    auth = AsyncMock(return_value=actor)
    card = AsyncMock(return_value={"id": 41, "publication_scope": "feed", "comments_count": 3})
    comments = AsyncMock(return_value=[
        {"id": 9, "gen_id": 41, "author": "Автор", "text": "Отличное фото",
         "created_at": "2026-11-14 09:00:00", "author_referral_code": "PRIVATE_REF",
         "user_id": 81233, "telegram_id": 912345, "is_mine": True},
    ])
    monkeypatch.setattr(api, "resolve_platform_actor", auth)
    monkeypatch.setattr(database, "get_feed_generation_card", card)
    monkeypatch.setattr(database, "get_feed_comments", comments)

    result = await api.vk_public_feed_comments(_request())
    assert result.status == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert json.loads(result.text) == {
        "ok": True, "comments_count": 3,
        "comments": [{"id": 9, "author": "Автор", "text": "Отличное фото",
                      "created_at": "2026-11-14 09:00:00"}],
    }
    assert "PRIVATE_REF" not in result.text
    assert "telegram_id" not in result.text
    auth.assert_awaited_once_with("vk-only-session", expected_platform="vk")
    card.assert_awaited_once_with(41, viewer_user_id=None, include_unavailable=False)
    comments.assert_awaited_once_with(41, limit=80, viewer_user_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("card_value", [None, {"id": 41, "publication_scope": "profile"}])
async def test_native_vk_cannot_read_private_or_profile_comments(monkeypatch, card_value):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=PlatformActor(
        platform="vk", external_id=2001, shared_account_id="vk",
        linked_platforms=("vk",), linked_telegram_id=None,
    )))
    comments = AsyncMock()
    monkeypatch.setattr(database, "get_feed_generation_card", AsyncMock(return_value=card_value))
    monkeypatch.setattr(database, "get_feed_comments", comments)
    result = await api.vk_public_feed_comments(_request())
    assert result.status == 404
    comments.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["0", "-2", "1e3", "123abc", "９", "9" * 18])
async def test_native_vk_feed_comments_reject_malformed_ids(monkeypatch, bad_id):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=PlatformActor(
        platform="vk", external_id=2001, shared_account_id="vk",
        linked_platforms=("vk",), linked_telegram_id=None,
    )))
    with pytest.raises(ValueError):
        await api.vk_public_feed_comments(_request(bad_id))


@pytest.mark.asyncio
async def test_native_vk_comment_read_rejects_invalid_platform(monkeypatch):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    auth = AsyncMock(side_effect=PermissionError("Not VK"))
    monkeypatch.setattr(api, "resolve_platform_actor", auth)
    with pytest.raises(PermissionError):
        await api.vk_public_feed_comments(_request())
    auth.assert_awaited_once_with("vk-only-session", expected_platform="vk")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_limit", ["0", "151", "-1", "1.5", "invalid", "９"])
async def test_native_vk_public_comments_limit_matches_common_feed_safety_cap(monkeypatch, bad_limit):
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=PlatformActor(
        platform="vk", external_id=2001, shared_account_id="vk",
        linked_platforms=("vk",), linked_telegram_id=None,
    )))
    raw = f"/mini-app/api/account-preview/vk-feed-comments?feed_gen_id=41&limit={bad_limit}"
    with pytest.raises(ValueError):
        await api.vk_public_feed_comments(
            make_mocked_request("GET", raw, headers={"Authorization": "Bearer vk-only-session"}),
        )


def test_vk_public_comment_read_route_is_registered_without_paid_gate():
    from aiohttp import web
    app = web.Application()
    api.setup_shared_account_routes(app, '/mini-app')
    routes = [(route.method, route.resource.canonical) for route in app.router.routes()]
    assert ('GET', '/mini-app/api/account-preview/vk-feed-comments') in routes
    assert ('POST', '/mini-app/api/account-preview/vk-feed-comments') not in routes
