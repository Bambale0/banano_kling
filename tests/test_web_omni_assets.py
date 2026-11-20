"""Browser identity-bound Omni audio/character assets are paid exactly once."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth, web_generation
from bot.services.gemini_omni_service import gemini_omni_service
from bot.shared_accounts.wallet import WalletService


async def _login(subject):
    result = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", subject,
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = result.cookies["nm_web_session"].value
    account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    return account, {"Origin": "https://neuromixbot.com",
                     "Cookie": "nm_web_session=" + cookie}


@pytest.mark.asyncio
async def test_web_omni_audio_creation_bills_exactly_once_and_blocks_other_accounts(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    provider = AsyncMock(return_value={"status": "done", "asset_id": "provider-audio-99"})
    monkeypatch.setattr(gemini_omni_service, "create_audio", provider)
    owner, owner_headers = await _login("web-omni-audio-owner")
    _another, other_headers = await _login("web-omni-audio-other")
    await WalletService("live").apply(owner, "credit", "20", "omni-audio-start-credit")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    root = "/mini-app/api/web-auth/web-omni/assets"
    payload = {"kind": "audio", "name": "Fox Voice", "base_voice": "achernar",
               "voice_description": "Warm engaging narration"}
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(root + "/quote", json=payload, headers=owner_headers)
        assert quote.status == 200, await quote.text()
        price = (await quote.json())["price"]
        assert price == "3"
        created = await client.post(root + "/create", json={
            **payload, "request_key": "omni-audio-unique-2026",
            "expected_price": price,
        }, headers=owner_headers)
        assert created.status == 202, await created.text()
        identifier = (await created.json())["task_id"]
        repeated = await client.post(root + "/create", json={
            **payload, "request_key": "omni-audio-unique-2026",
            "expected_price": price,
        }, headers=owner_headers)
        assert repeated.status == 200
        assert (await repeated.json())["task_id"] == identifier
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "3.0000"
        assert await web_generation.run_worker_tick() == [identifier]
        provider.assert_awaited_once()
        listing = await client.get(root, headers=owner_headers)
        assert listing.status == 200
        record = (await listing.json())["assets"][0]
        assert record["kind"] == "audio"
        assert record["asset_id"].startswith("oa_")
        assert "provider-audio-99" not in str(await listing.text())
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "17.0000"
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "0.0000"
        no_others = await client.get(root, headers=other_headers)
        assert (await no_others.json())["assets"] == []
        foreign = await client.post("/mini-app/api/web-auth/web-generation/quote",
            headers=other_headers, json={
                "model": "gemini_omni", "prompt": "A speaking fox",
                "duration": 6, "quality": "720p",
                "omni_audio_asset_ids": [record["asset_id"]],
            })
        assert foreign.status in (400, 403)


@pytest.mark.asyncio
async def test_omni_character_uses_owned_uploaded_image_and_optional_owned_audio(monkeypatch):
    from bot import web_references
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_references, "owned_reference_urls", AsyncMock(
        return_value=["https://neuromixbot.com/uploads/web_refs/character.png"],
    ))
    provider = AsyncMock(return_value={"status": "done", "asset_id": "provider-character-11"})
    monkeypatch.setattr(gemini_omni_service, "create_character", provider)
    owner, headers = await _login("web-omni-character-owner")
    await WalletService("live").apply(owner, "credit", "15", "omni-char-start-credit")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    root = "/mini-app/api/web-auth/web-omni/assets"
    payload = {
        "kind": "character", "character_name": "Nora",
        "description": "A bright fox with a stylish jacket",
        "image_reference_id": "wr_" + "a" * 32,
    }
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(root + "/quote", json=payload, headers=headers)
        assert quote.status == 200, await quote.text()
        assert (await quote.json())["price"] == "5"
        created = await client.post(root + "/create", headers=headers, json={
            **payload, "request_key": "omni-char-unique-2026",
            "expected_price": "5",
        })
        assert created.status == 202, await created.text()
        identifier = (await created.json())["task_id"]
        assert await web_generation.run_worker_tick() == [identifier]
        args = provider.await_args.kwargs
        assert args["image_urls"] == ["https://neuromixbot.com/uploads/web_refs/character.png"]
        assert args["character_name"] == "Nora"
        assert "user_id" not in args and "telegram_id" not in args
        assets = (await (await client.get(root, headers=headers)).json())["assets"]
        assert len(assets) == 1 and assets[0]["kind"] == "character"
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "10.0000"


@pytest.mark.asyncio
async def test_video_uses_only_own_audio_id_and_character_id_not_untrusted_provider_ids(
    monkeypatch,
):
    from bot import web_references

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    user, headers = await _login("web-video-owned-omni-assets")
    _second, second_headers = await _login("web-video-other-account")
    await WalletService("live").apply(user, "credit", "35", "web-omni-video-credit")
    monkeypatch.setattr(gemini_omni_service, "create_audio", AsyncMock(
        return_value={"status": "done", "asset_id": "verified-audio-301"},
    ))
    monkeypatch.setattr(gemini_omni_service, "create_character", AsyncMock(
        return_value={"status": "done", "asset_id": "verified-character-41"},
    ))
    fake_video = AsyncMock(return_value={"task_id": "real-omni-video-id"})
    monkeypatch.setattr(gemini_omni_service, "generate_video", fake_video)
    monkeypatch.setattr(web_references, "owned_reference_urls", AsyncMock(
        side_effect=lambda account, refs, *, kind:
            ["https://neuromixbot.com/uploads/web_refs/photo.png"]
            if kind == "image" and refs else [],
    ))
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    root = "/mini-app/api/web-auth/web-omni/assets"
    async with TestClient(TestServer(app)) as client:
        for record in (
            {"kind": "audio", "name": "Clean Voice", "base_voice": "achernar"},
            {"kind": "character", "character_name": "Nora",
             "description": "An engaging character",
             "image_reference_id": "wr_" + "a" * 32},
        ):
            quote = await client.post(root + "/quote", json=record, headers=headers)
            price = (await quote.json())["price"]
            created = await client.post(root + "/create",
                json={**record, "request_key": "asset-create-" + record["kind"] + "-2026",
                      "expected_price": price}, headers=headers)
            assert created.status == 202, await created.text()
            task_id = (await created.json())["task_id"]
            assert await web_generation.run_worker_tick() == [task_id]
        assets = (await (await client.get(root, headers=headers)).json())["assets"]
        audio = next(x["asset_id"] for x in assets if x["kind"] == "audio")
        character = next(x["asset_id"] for x in assets if x["kind"] == "character")
        payload = {
            "model": "gemini_omni", "prompt": "Nora speaks in her own voice",
            "quality": "720p", "duration": 6,
            "omni_audio_asset_ids": [audio],
            "omni_character_asset_ids": [character],
            "omni_seed": 12345,
        }
        forbidden = await client.post("/mini-app/api/web-auth/web-generation/quote",
            json=payload, headers=second_headers)
        assert forbidden.status == 403, await forbidden.text()
        quote = await client.post("/mini-app/api/web-auth/web-generation/quote",
            json=payload, headers=headers)
        assert quote.status == 200, await quote.text()
        created = await client.post("/mini-app/api/web-auth/web-generation/create",
            json={**payload, "request_key": "omni-owned-video-unique",
                  "expected_price": (await quote.json())["price"]}, headers=headers)
        assert created.status == 202, await created.text()
        assert await web_generation.run_worker_tick() == [(await created.json())["task_id"]]
        submitted = fake_video.await_args.kwargs
        assert submitted["audio_ids"] == ["verified-audio-301"]
        assert submitted["character_ids"] == ["verified-character-41"]
        assert submitted["seed"] == 12345
        assert "account_id" not in submitted and "telegram_id" not in submitted
        assert "provider_audio_ids" not in payload


@pytest.mark.asyncio
async def test_omni_pending_audio_provider_task_polls_and_settles_once(monkeypatch):
    from bot import db as db_backend
    from bot.services.kie_market_service import kie_market_service

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    create_provider = AsyncMock(return_value={
        "status": "pending", "task_id": "kie-omni-async-audio-789",
    })
    monkeypatch.setattr(gemini_omni_service, "create_audio", create_provider)
    poll = AsyncMock(return_value={
        "taskId": "kie-omni-async-audio-789",
        "state": "success",
        "resultJson": '{"audioId":"resolved-async-audio-12"}',
    })
    monkeypatch.setattr(kie_market_service, "get_task_status", poll)
    account, headers = await _login("web-omni-pending-id")
    await WalletService("live").apply(account, "credit", "10", "omni-async-start")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    root = "/mini-app/api/web-auth/web-omni/assets"
    async with TestClient(TestServer(app)) as client:
        created = await client.post(root + "/create", headers=headers, json={
            "kind": "audio", "name": "Queued Voice", "base_voice": "achernar",
            "request_key": "omni-queued-asset-request-2026",
            "expected_price": "3",
        })
        assert created.status == 202, await created.text()
        task_id = (await created.json())["task_id"]
        assert await web_generation.run_worker_tick() == [task_id]
        first = await WalletService("live").snapshot(account)
        assert first["balance"]["reserved"] == "3.0000"
        assert poll.await_count == 0
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?",
                (task_id,),
            )
            await db.commit()
        assert await web_generation.run_worker_tick() == [task_id]
        assert create_provider.await_count == 1
        assert poll.await_count == 1
        state = await WalletService("live").snapshot(account)
        assert state["balance"]["available"] == "7.0000"
        assert state["balance"]["reserved"] == "0.0000"
        assert len([x for x in state["entries"] if x["kind"] == "capture"]) == 1
        assert (await (await client.get(root, headers=headers)).json())["assets"][0]["kind"] == "audio"
        assert await web_generation.run_worker_tick() == []


@pytest.mark.asyncio
async def test_web_omni_asset_provider_never_retries_transient_post(monkeypatch):
    post_once = AsyncMock(return_value={
        "error": "temporarily_unavailable", "status_code": 503,
    })
    retrying_post = AsyncMock()
    monkeypatch.setattr(gemini_omni_service, "_kie_post_once", post_once)
    monkeypatch.setattr(gemini_omni_service, "_kie_post_raw", retrying_post)
    response = await gemini_omni_service.create_audio(
        name="Never Retry", audio_id="achernar",
        retry_transient=False,
    )
    assert response["error"] == "temporarily_unavailable"
    post_once.assert_awaited_once()
    retrying_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_omni_character_wire_uses_singular_description(monkeypatch):
    """Official KIE /omni/character/create expects description, not descriptions."""
    post = AsyncMock(return_value={
        "code": 200, "data": {"characterId": "character-real-2026"},
    })
    monkeypatch.setattr(gemini_omni_service, "_kie_post_once", post)
    result = await gemini_omni_service.create_character(
        description="A fox with bright orange fur",
        image_urls=["https://neuromixbot.com/uploads/web_refs/fox.png"],
        character_name="Fox Hero",
        audio_ids=["audio-owned-provider"],
        retry_transient=False,
    )
    assert result["asset_id"] == "character-real-2026"
    post.assert_awaited_once()
    assert post.await_args.args[1] == {
        "description": "A fox with bright orange fur",
        "image_urls": ["https://neuromixbot.com/uploads/web_refs/fox.png"],
        "character_name": "Fox Hero",
        "audio_ids": ["audio-owned-provider"],
    }


@pytest.mark.asyncio
async def test_gemini_omni_audio_wire_uses_registered_voice_and_name(monkeypatch):
    post = AsyncMock(return_value={
        "code": 200, "data": {"audioId": "owned-provider-audio-505"},
    })
    monkeypatch.setattr(gemini_omni_service, "_kie_post_once", post)
    result = await gemini_omni_service.create_audio(
        audio_id="achernar",
        name="Friendly voice",
        voice_description="A calm voice",
        example_dialogue="Hello everybody",
        retry_transient=False,
    )
    assert result["asset_id"] == "owned-provider-audio-505"
    post.assert_awaited_once()
    assert post.await_args.args[1] == {
        "audio_id": "achernar",
        "name": "Friendly voice",
        "voice_description": "A calm voice",
        "example_dialogue": "Hello everybody",
    }
