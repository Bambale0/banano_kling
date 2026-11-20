"""Wan3 web text scenarios never invent pricing or Telegram accounts."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot import web_generation
from bot.services.preset_manager import preset_manager
from bot.services.wan3_models import wan3_service_for_model


@pytest.mark.parametrize("model", ["wan_3_prime", "wan_3"])
def test_wan3_text_mode_requires_admin_quality_rate_and_exact_duration(monkeypatch, model):
    # Production may not yet have configured Wan3 rates. A missing rate must
    # disable the purchasing option, NOT fallback to an unrelated video price.
    monkeypatch.setattr(preset_manager, "get_video_quality_costs",
                        lambda m: {"720p": 2.25} if m == model else {})
    price = web_generation._price("video", model, 6, "720P")
    from bot.services.wan3_prime_lifecycle import _round_half_credit

    assert float(price) == _round_half_credit(6 * 2.25)
    with pytest.raises(ValueError):
        web_generation._price("video", model, 6, "480P")
    auto = web_generation._normalize_request({
        "model": model, "prompt": "A normal text video",
        "request_key": "wan3-auto-bounded-quote-2026",
        "duration": -1, "quality": "720P",
    })
    assert auto["duration"] == -1
    assert float(web_generation._price_for_request(auto)) == _round_half_credit(30 * 2.25)
    for payload in (
        {"wan_scenario": "text", "reference_ids": ["wr_" + "1" * 32]},
        {"video_reference_ids": ["wr_" + "2" * 32]},
        {"audio_reference_ids": ["wr_" + "3" * 32]},
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({
                "model": model, "prompt": "Time-lapse of growing trees",
                "request_key": "wan3-text-mode-2026", **payload,
            })


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["wan_3_prime", "wan_3"])
async def test_wan3_text_provider_uses_prepared_existing_wire_contract(monkeypatch, model):
    service = wan3_service_for_model(model)
    mock_submit = AsyncMock(return_value={"task_id": "wan-task-created"})
    monkeypatch.setattr(service, "submit_prepared", mock_submit)
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "b" * 32, {
            "model": model, "prompt": "A bird taking flight over water",
            "aspect_ratio": "16:9", "duration": 6,
            "quality": "720P", "reference_urls": [],
            "reference_video_urls": [], "reference_audio_urls": [],
        },
    )
    assert (task, rejected) == ("wan-task-created", False)
    mock_submit.assert_awaited_once()
    wire = mock_submit.await_args.args[0]
    assert wire["duration"] == 6
    assert wire["resolution"] == "720P"
    assert wire["aspect_ratio"] == "16:9"
    assert "telegram_id" not in wire and "user_id" not in wire


def test_wan3_catalog_can_be_safely_disabled_without_admin_rates(monkeypatch):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {})
    entries = {m["id"]: m for m in web_generation._models()}
    for model in ("wan_3", "wan_3_prime"):
        assert entries[model]["enabled"] is False
        assert entries[model]["unavailable_reason"]



@pytest.mark.parametrize("scenario,count", [
    ("first_frame", 1), ("first_last", 2), ("reference", 3),
])
def test_wan3_image_scenarios_require_exact_refs_and_live_resolution_rate(monkeypatch, scenario, count):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs",
                        lambda _: {"720p": 2.25})
    refs = ["wr_" + f"{idx + 1:032x}" for idx in range(count)]
    payload = {
        "model": "wan_3", "prompt": "Sunset on coastal cliffs",
        "request_key": "wan3-images-scenario-2026",
        "wan_scenario": scenario, "reference_ids": refs,
        "duration": 6, "quality": "720P",
    }
    normalized = web_generation._normalize_request(payload)
    assert normalized["wan_scenario"] == scenario
    assert normalized["reference_ids"] == refs
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            **payload, "reference_ids": refs[:-1] if scenario != "reference" else [],
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,image_count,wire_keys", [
    ("first_frame", 1, ("first_frame_url",)),
    ("first_last", 2, ("first_frame_url", "last_frame_url")),
    ("reference", 3, ("reference_image_urls",)),
])
async def test_wan3_image_provider_prepares_explicit_recipe_without_telegram(
    monkeypatch, scenario, image_count, wire_keys,
):
    service = wan3_service_for_model("wan_3")
    prepare = AsyncMock(return_value={"scenario": scenario, "duration": "6"})
    submit = AsyncMock(return_value={"task_id": "wan3-verified-image"})
    monkeypatch.setattr(service, "prepare_request", prepare)
    monkeypatch.setattr(service, "submit_prepared", submit)
    urls = [f"https://neuromixbot.com/uploads/web_refs/owned-{i}.png"
            for i in range(image_count)]
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "f" * 32, {
            "model": "wan_3", "prompt": "Clouds flying over a city",
            "wan_scenario": scenario, "duration": 6, "quality": "720P",
            "aspect_ratio": "16:9", "reference_urls": urls,
            "reference_video_urls": [], "reference_audio_urls": [],
        },
    )
    assert (task, rejected) == ("wan3-verified-image", False)
    kwargs = prepare.await_args.kwargs
    assert kwargs["scenario"] == scenario
    assert all(key in kwargs for key in wire_keys)
    assert "telegram_id" not in kwargs


@pytest.mark.parametrize("scenario,video_count,audio_count", [
    ("reference", 2, 0), ("reference", 0, 2),
    ("edit", 1, 0), ("reference", 1, 1),
])
def test_wan3_web_accepts_typed_references_but_never_arbitrary_urls(
    scenario, video_count, audio_count, monkeypatch,
):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {"720p": 3.25})
    payload = {
        "model": "wan_3", "prompt": "A film scene",
        "request_key": "web-wan3-multimedia-2026",
        "wan_scenario": scenario, "duration": 8, "quality": "720P",
        "video_reference_ids": ["wr_" + str(i + 1) * 32 for i in range(video_count)],
        "audio_reference_ids": ["wr_" + str(i + 5) * 32 for i in range(audio_count)],
    }
    normalized = web_generation._normalize_request(payload)
    assert len(normalized["video_reference_ids"]) == video_count
    assert len(normalized["audio_reference_ids"]) == audio_count
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            **payload, "reference_video_urls": ["https://other.invalid/user.mp4"],
        })


@pytest.mark.asyncio
async def test_wan3_web_quote_accounts_for_verified_input_video_duration(monkeypatch):
    from types import SimpleNamespace

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import web_auth, web_references

    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {"720p": 2})
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "owned_reference_urls", AsyncMock(
        side_effect=lambda account, refs, *, kind:
            ["https://neuromixbot.com/uploads/web_refs/owned.mp4"]
            if refs and kind == "video" else [],
    ))
    from bot.services.wan3_prime_media import MediaInfo

    fake_video = MediaInfo(
        kind="video", duration_seconds=5.5, size_bytes=2222,
        width=1280, height=720, extension=".mp4",
        url="https://neuromixbot.com/uploads/web_refs/owned.mp4",
    )
    monkeypatch.setattr(web_references, "owned_reference_media", AsyncMock(
        side_effect=lambda account, refs, *, kind:
            [fake_video] if kind == "video" else [],
    ))
    resp = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "wan3-owner-quote-input-duration",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = resp.cookies["nm_web_session"].value
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(
            "/mini-app/api/web-auth/web-generation/quote",
            headers={
                "Cookie": "nm_web_session=" + cookie,
                "Origin": "https://neuromixbot.com",
            }, json={
                "model": "wan_3", "prompt": "Add fire to scene",
                "wan_scenario": "edit", "duration": 8,
                "quality": "720P",
                "video_reference_ids": ["wr_" + "1" * 32],
            },
        )
        assert quote.status == 200, await quote.text()
        body = await quote.json()
        from bot.services.wan3_prime_lifecycle import _round_half_credit
        assert float(body["price"]) == _round_half_credit((5.5 + 8) * 2)


@pytest.mark.asyncio
async def test_wan3_web_autoduration_reserves_maximum_until_result_probed(monkeypatch):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {"720p": 2})
    payload = web_generation._normalize_request({
        "model": "wan_3_prime", "prompt": "A cinematic sequence",
        "request_key": "wan-auto-duration-2026",
        "wan_scenario": "text", "duration": -1, "quality": "720P",
    })
    assert payload["duration"] == -1
    assert float(web_generation._price_for_request(payload)) == 60


@pytest.mark.asyncio
async def test_wan3_auto_duration_settles_real_video_seconds_only_after_s3(monkeypatch):
    from types import SimpleNamespace

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import db as db_backend
    from bot import web_auth, web_media_delivery, web_wan3
    from bot.shared_accounts.wallet import WalletService

    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {"720p": 2})
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_submit_to_provider", AsyncMock(
        return_value=("kie-wan3-auto", False),
    ))
    monkeypatch.setattr(web_generation, "_provider_check", AsyncMock(
        return_value=("success", "https://cdn.kie.ai/provider.mp4"),
    ))
    monkeypatch.setattr(web_media_delivery, "archive_web_result", AsyncMock(
        return_value="https://neuromixbot.com/uploads/web_results/test-output.mp4",
    ))
    inspector = AsyncMock(return_value=8.25)
    monkeypatch.setattr(web_wan3, "inspect_web_wan_output", inspector)

    owner = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "wan3-auto-web-payout",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = owner.cookies["nm_web_session"].value
    account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    await WalletService("live").apply(account, "credit", "90", "wan3-auto-test-balance")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    headers = {
        "Origin": "https://neuromixbot.com",
        "Cookie": "nm_web_session=" + cookie,
    }
    async with TestClient(TestServer(app)) as client:
        created = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            headers=headers, json={
                "model": "wan_3_prime", "prompt": "A waterfall",
                "duration": -1, "quality": "720P",
                "request_key": "wan3-auto-web-long",
            },
        )
        assert created.status == 202, await created.text()
        task_id = (await created.json())["task_id"]
        assert (await WalletService("live").snapshot(account))["balance"]["reserved"] == "60.0000"
        assert await web_generation.run_worker_tick() == [task_id]
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?",
                (task_id,),
            )
            await db.commit()
        assert await web_generation.run_worker_tick() == [task_id]
        snapshot = await WalletService("live").snapshot(account)
        from bot.services.wan3_prime_lifecycle import _round_half_credit
        charged = _round_half_credit(8.25 * 2)
        assert float(snapshot["balance"]["available"]) == pytest.approx(90 - charged)
        assert snapshot["balance"]["reserved"] == "0.0000"
        assert len([row for row in snapshot["entries"] if row["kind"] == "capture"]) == 1
        assert len([row for row in snapshot["entries"] if row["kind"] == "release"]) == 1
        details = await client.get(
            "/mini-app/api/web-auth/task/" + task_id, headers=headers,
        )
        assert (await details.json())["task"]["status"] == "completed"
        inspector.assert_awaited_once()
