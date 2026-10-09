"""Feed shares identify the authenticated sharer while retaining the source author."""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp
from bot.config import config
from bot.handlers import (
    common,  # Install the same compatibility wrappers as production.
)


def signed_init_data(telegram_id):
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Test"}),
    }
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def sharing_client(monkeypatch):
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    await database.set_channel_subscription_required(False)
    app = web.Application()
    app["bot"] = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")),
        send_message=AsyncMock(),
    )
    app.router.add_post("/mini-app/api/feed/share", miniapp.miniapp_feed_share)
    app.router.add_get("/api/v1/feed/{gen_id}/link", miniapp.miniapp_feed_share)
    async with TestClient(TestServer(app)) as client:
        yield client


async def published_card(gen_type="image"):
    author = await database.get_or_create_user(82001)
    await database.add_generation_task(
        author.id, author.telegram_id, "shared-feed-fixture", gen_type,
        "miniapp_image" if gen_type == "image" else "miniapp_video",
        model="banana_pro" if gen_type == "image" else "kling",
        prompt="Private source recipe", cost=2,
    )
    await database.complete_video_task(
        "shared-feed-fixture", "https://example.test/synthetic-result.png",
    )
    card = await database.share_to_feed("shared-feed-fixture", author.id)
    assert card is not None
    return author, card


@pytest.mark.asyncio
async def test_copy_link_uses_signed_sharer_and_retains_source_author(sharing_client):
    author, card = await published_card()
    sharer = await database.get_or_create_user(82002)
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": signed_init_data(sharer.telegram_id), "gen_id": card["id"],
        "referral_code": "SPOOF", "user_id": author.id,
    })
    assert response.status == 200
    result = await response.json()
    assert result["miniapp_repeat_link"] == (
        f"https://t.me/test_bot?startapp=remix_{card['id']}_ref_{sharer.referral_code}"
    )
    assert result["feed_item"]["id"] == card["id"]
    assert result["feed_item"]["user_id"] == author.id
    assert result["feed_item"]["author_referral_code"] == author.referral_code
    assert "no-store" in response.headers["Cache-Control"]
    unchanged = await database.get_or_create_user(sharer.telegram_id)
    assert unchanged.referred_by is None
    assert unchanged.credits == sharer.credits


@pytest.mark.asyncio
@pytest.mark.parametrize("gen_type", ["image", "video"])
@pytest.mark.parametrize("surface", ["feed", "profile"])
async def test_all_url_variants_follow_each_sharer_without_cache_leak(sharing_client, gen_type, surface):
    author, card = await published_card(gen_type)
    for telegram_id in (82002, 82003, 82002, author.telegram_id):
        sharer = await database.get_or_create_user(telegram_id)
        response = await sharing_client.post("/mini-app/api/feed/share", json={
            "init_data": signed_init_data(telegram_id), "gen_id": card["id"], "surface": surface,
        })
        assert response.status == 200
        result = await response.json()
        code = sharer.referral_code
        post = f"https://t.me/test_bot?start=feed_{card['id']}_ref_{code}"
        mini_post = f"https://t.me/test_bot?startapp=feed_{card['id']}_ref_{code}"
        mini_repeat = f"https://t.me/test_bot?startapp=remix_{card['id']}_ref_{code}"
        repeat = f"https://t.me/test_bot?start=remix_{card['id']}_ref_{code}" if gen_type == "image" else mini_repeat
        assert {key: result[key] for key in (
            "link", "bot_link", "post_link", "repeat_link", "miniapp_link", "miniapp_post_link", "miniapp_repeat_link",
        )} == {
            "link": repeat, "bot_link": post, "post_link": post if gen_type == "image" else repeat, "repeat_link": repeat,
            "miniapp_link": mini_post, "miniapp_post_link": mini_post, "miniapp_repeat_link": mini_repeat,
        }
        assert result["feed_item"]["author_referral_code"] == author.referral_code
        assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", ["", "user=forged&hash=bad"])
async def test_share_rejects_invalid_signature_before_increment(sharing_client, auth):
    _author, card = await published_card()
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": auth, "gen_id": card["id"],
    })
    assert response.status >= 400
    assert "link" not in await response.json()
    unchanged = await database.get_feed_generation_card(card["id"])
    assert unchanged["shares_count"] == card["shares_count"]


@pytest.mark.asyncio
async def test_unknown_publication_has_no_link(sharing_client):
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": signed_init_data(82002), "gen_id": 999999,
    })
    assert response.status == 404
    assert "link" not in await response.json()


@pytest.mark.asyncio
async def test_shared_source_repeat_reward_stays_with_original_creator(sharing_client):
    author, card = await published_card()
    sharer = await database.get_or_create_user(82002)
    repeater = await database.get_or_create_user(82003)
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": signed_init_data(sharer.telegram_id), "gen_id": card["id"],
    })
    result = await response.json()
    assert result["miniapp_repeat_link"].endswith(f"_ref_{sharer.referral_code}")
    # Exercise the public reward service on a synthetic, isolated SQLite fixture.
    # No generation request, provider call, or real balance is involved.
    assert await database.credit_feed_prompt_repeat(
        result["feed_item"]["id"], repeater.id,
        repeat_task_id="synthetic-repeat", credits_spent=10,
    )
    assert not await database.credit_feed_prompt_repeat(
        result["feed_item"]["id"], repeater.id,
        repeat_task_id="synthetic-repeat", credits_spent=10,
    )
    rewarded = await database.get_or_create_user(author.telegram_id)
    unchanged = await database.get_or_create_user(sharer.telegram_id)
    assert rewarded.prompt_repeat_total_rub > author.prompt_repeat_total_rub
    assert unchanged.prompt_repeat_total_rub == sharer.prompt_repeat_total_rub


@pytest.mark.asyncio
async def test_bot_share_callback_uses_clicking_user_not_author():
    author, card = await published_card()
    sharer = await database.get_or_create_user(82002)
    callback = SimpleNamespace(
        data=f"bfs:{card['id']}", from_user=SimpleNamespace(id=sharer.telegram_id),
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
        answer=AsyncMock(),
    )
    await common.share_feed_card(callback)
    text = callback.answer.call_args.kwargs["text"]
    assert f"start=feed_{card['id']}_ref_{sharer.referral_code}" in text
    assert f"startapp=feed_{card['id']}_ref_{sharer.referral_code}" in text
    assert author.referral_code not in text


@pytest.mark.asyncio
async def test_bot_copy_button_uses_viewer_even_with_shared_card():
    author, card = await published_card()
    bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")))
    for telegram_id in (82002, 82003, author.telegram_id):
        viewer = await database.get_or_create_user(telegram_id)
        markup = await common._build_feed_keyboard(
            bot=bot, card=card, index=0, total=1, photo_index=0, photos_count=1,
            source_code="r", viewer_telegram_id=viewer.telegram_id,
        )
        copied = [button.copy_text.text for row in markup.inline_keyboard for button in row if button.copy_text]
        assert copied == [f"https://t.me/test_bot?start=feed_{card['id']}_ref_{viewer.referral_code}"]
        assert card["author_referral_code"] == author.referral_code


@pytest.mark.asyncio
async def test_v1_link_alias_uses_authenticated_sharer(sharing_client):
    _author, card = await published_card()
    sharer = await database.get_or_create_user(82002)
    response = await sharing_client.get(
        f"/api/v1/feed/{card['id']}/link",
        headers={"X-Telegram-Init-Data": signed_init_data(sharer.telegram_id)},
    )
    assert response.status == 200
    assert (await response.json())["miniapp_repeat_link"] == (
        f"https://t.me/test_bot?startapp=remix_{card['id']}_ref_{sharer.referral_code}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [None, "", "   "])
async def test_missing_sharer_code_never_falls_back_to_author(sharing_client, monkeypatch, code):
    author, card = await published_card()
    user = SimpleNamespace(id=2, referral_code=code)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(82002, {"user": user})))
    response = await sharing_client.post("/mini-app/api/feed/share", json={
        "init_data": signed_init_data(82002), "gen_id": card["id"], "referral_code": "SPOOF",
    })
    assert response.status == 200
    result = await response.json()
    assert result["miniapp_repeat_link"] == f"https://t.me/test_bot?startapp=remix_{card['id']}"
    assert all("_ref_" not in result[key] for key in result if key.endswith("link"))
    assert result["feed_item"]["author_referral_code"] == author.referral_code


@pytest.mark.asyncio
async def test_bot_copy_without_known_viewer_has_no_referral_fallback():
    author, card = await published_card()
    bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")))
    markup = await common._build_feed_keyboard(
        bot=bot, card=card, index=0, total=1, photo_index=0, photos_count=1, source_code="r",
    )
    copied = [button.copy_text.text for row in markup.inline_keyboard for button in row if button.copy_text]
    assert copied == []
    assert any(button.callback_data == f"bfs:{card['id']}" for row in markup.inline_keyboard for button in row)
    assert card["author_referral_code"] == author.referral_code


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type,chat_id", [("group", -82000), ("supergroup", -10082000), ("private", 82002)])
async def test_rendered_chat_uses_private_owner_or_per_click_share(monkeypatch, chat_type, chat_id):
    _author, card = await published_card()
    viewer = await database.get_or_create_user(82002)
    lookup = AsyncMock(wraps=database.get_or_create_user)
    monkeypatch.setattr(common, "get_or_create_user", lookup)
    monkeypatch.setattr(common, "_download_preview_photo", AsyncMock(return_value="synthetic-photo"))
    message = SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
        answer_photo=AsyncMock(),
    )
    await common._render_feed_carousel(message, [card])
    markup = message.answer_photo.call_args.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    copied = [button.copy_text.text for button in buttons if button.copy_text]
    if chat_type == "private":
        assert copied == [f"https://t.me/test_bot?start=feed_{card['id']}_ref_{viewer.referral_code}"]
        lookup.assert_awaited_once_with(viewer.telegram_id)
    else:
        assert copied == []
        assert any(button.callback_data == f"bfs:{card['id']}" for button in buttons)
        lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_only_share_uses_viewer_and_rejects_feed_surface(sharing_client):
    from bot.handlers import publication_scope_compat

    author, card = await published_card()
    assert await publication_scope_compat.remove_from_feed_scoped("shared-feed-fixture", author.id)
    sharer = await database.get_or_create_user(82002)
    for surface, expected_status in (("feed", 404), ("profile", 200)):
        response = await sharing_client.post("/mini-app/api/feed/share", json={
            "init_data": signed_init_data(sharer.telegram_id), "gen_id": card["id"], "surface": surface,
        })
        assert response.status == expected_status
        if surface == "profile":
            assert (await response.json())["miniapp_repeat_link"].endswith(f"_ref_{sharer.referral_code}")
    callback = SimpleNamespace(
        data=f"bfs:{card['id']}", from_user=SimpleNamespace(id=sharer.telegram_id),
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
        answer=AsyncMock(),
    )
    await common.share_feed_card(callback)
    assert f"startapp=feed_{card['id']}_ref_{sharer.referral_code}" in callback.answer.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_bot_callback_rejects_withdrawn_publication():
    from bot.handlers import publication_scope_compat

    author, card = await published_card()
    assert await publication_scope_compat.remove_publication("shared-feed-fixture", author.id)
    callback = SimpleNamespace(
        data=f"bfs:{card['id']}", from_user=SimpleNamespace(id=82002),
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
        answer=AsyncMock(),
    )
    await common.share_feed_card(callback)
    assert callback.answer.call_args.kwargs["text"] == "Пост не найден"
    callback.bot.get_me.assert_not_awaited()
