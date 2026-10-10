"""Ordinary WAN shares lifecycle but never Prime identity/rates."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import (
    Wan3PrimeLifecycle,
    Wan3PrimeLifecycleError,
)
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


class DistinctPrices:
    def get_video_quality_costs(self, model):
        return {"720p": 4 if model == "wan_3" else 99}


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_seconds", [4.0, 4.7, 9.0])
async def test_standard_fixed_quote_remains_frozen_and_metadata_distinct(actual_seconds):
    actor = await user_actor(100)
    provider = Provider()
    source = "https://media.example/source.mp4"
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(url_durations={source: 7}, file_duration=actual_seconds),
        preset_manager=DistinctPrices(), transport=provider,
        downloader=Downloader(Path("static/uploads/wan3_prime/results/standard-fixed.mp4")),
    )
    request = body(model="wan_3", scenario="reference", reference_video_urls=[source])
    quote = await lifecycle.quote(actor, request)
    assert quote.reserve_credits == 48
    assert quote.as_response()["model"] == "wan_3"
    result = await lifecycle.launch(actor, request, quote, "ordinary-fixed")
    assert result["model"] == "wan_3"
    assert provider.recipe.provider_model == "wan/3-0-video"
    provider.statuses["provider_1"] = {
        "taskId": "provider_1", "model": "wan/3-0-video", "state": "success",
        "resultJson": '{"resultUrls":["https://provider.test/result.mp4"]}',
    }
    await lifecycle.reconcile_once(provider_task_id="provider_1")
    status = await lifecycle.status(actor, result["task_id"])
    assert status["charged_credits"] == 48
    assert status["refunded_credits"] == 0
    assert await balance(actor.user_id) == 52
    saved = await database.get_generation_task_payload(result["task_id"], user_id=actor.user_id)
    assert saved["model"] == "wan_3"


@pytest.mark.asyncio
async def test_cross_model_idempotency_reuse_cannot_return_prime_task():
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=DistinctPrices(), transport=provider)
    standard = body(model="wan_3")
    quote = await lifecycle.quote(actor, standard)
    await lifecycle.launch(actor, standard, quote, "same-key")
    with pytest.raises(Wan3PrimeLifecycleError):
        await lifecycle.launch(actor, body(model="wan_3_prime"), quote, "same-key")
    assert provider.creates == 1
    assert await balance(actor.user_id) == 80


def test_ordinary_publication_preserves_first_last_roles_and_audio():
    from bot.video_repeat_reference_contract import (
        active_video_recipe,
        build_video_repeat_plan,
    )

    source = {"id": 12, "user_id": 1, "model": "wan_3", "request_data": {
        "model": "wan_3", "scenario": "first_last", "prompt": "test",
        "first_frame_url": "https://example.test/first.png",
        "last_frame_url": "https://example.test/last.png",
        "reference_audio_urls": ["https://example.test/sound.mp3"],
    }}
    for plan in (active_video_recipe(source), build_video_repeat_plan(source)):
        assert plan["model"] == "wan_3"
        assert [slot["role"] for slot in plan["images"]] == ["first_frame", "last_frame"]
        assert plan["audio"] == ["https://example.test/sound.mp3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [True, False])
async def test_ordinary_telegram_repeat_uses_full_wan_editor(monkeypatch, own):
    from bot.handlers.miniapp_video_continuity_compat import redirect_typed_video_repeat

    monkeypatch.setattr(database, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=1)))
    callback = SimpleNamespace(from_user=SimpleNamespace(id=101), answer=AsyncMock(),
                               message=SimpleNamespace(answer=AsyncMock()))
    task = SimpleNamespace(model="wan_3", user_id=1 if own else 2, task_id="wan3_test", id=12)
    assert await redirect_typed_video_repeat(callback, task)
    markup = callback.message.answer.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == ("wan3_recipe:wan3_test" if own else "wan3_repeat:12")
