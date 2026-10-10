"""Ordinary WAN shares lifecycle but never Prime identity/rates."""
from pathlib import Path

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
