"""Video-reference retail pricing: source seconds + generated seconds, no ×2."""
from __future__ import annotations

import pytest

from bot.creator_tariff import resolve_video_quote
from bot.video_reference_policy import apply_video_reference_cost


@pytest.mark.parametrize("model", [
    "seedance_2", "seedance_2_5", "seedance_2_mini",
    "seedance_2_fast", "gemini_omni_video", "glow",
])
def test_reference_price_uses_actual_seconds_for_every_video_capable_model(model):
    # Base is 20 bananas for 5 output seconds (4 per second).
    assert apply_video_reference_cost(
        model, 20, ["https://example.test/clip.mp4"],
        output_seconds=5, reference_seconds=7,
    ) == 48
    assert apply_video_reference_cost(
        model, 20, ["first.mp4", "second.mp4"],
        output_seconds=5, reference_seconds=13,
    ) == 72
    assert apply_video_reference_cost(model, 20, []) == 20


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5", "gemini_omni_video"])
def test_missing_measurement_fails_closed_instead_of_using_presence_multiplier(model):
    with pytest.raises(ValueError, match="не проверена"):
        apply_video_reference_cost(model, 20, ["clip.mp4"])
    with pytest.raises(ValueError, match="не проверена"):
        resolve_video_quote(model, 5, video_references=["clip.mp4"])


def test_video_quote_records_both_seconds_and_keeps_admin_free_charge(monkeypatch):
    from bot.services.preset_manager import preset_manager

    ordinary_cost = resolve_video_quote("seedance_2", 5).cost
    rate = ordinary_cost / 5
    paid = resolve_video_quote(
        "seedance_2", 5, video_references=["clip.mp4"],
        reference_video_seconds=7,
    )
    assert paid.cost == preset_manager._format_cost(rate * 12)
    assert paid.input_video_seconds == 7
    assert paid.billable_seconds == 12
    assert paid.reference_multiplier == 1
    assert paid.version == 2
    assert paid.charge_cost == paid.cost
    free = resolve_video_quote(
        "seedance_2", 5, video_references=["clip.mp4"],
        reference_video_seconds=7, tariff="admin",
    )
    assert free.cost == paid.cost
    assert free.charge_cost == 0


@pytest.mark.asyncio
async def test_actor_quote_measures_refs_once_and_uses_creator_rate(monkeypatch):
    import bot.creator_tariff as pricing

    calls = []
    async def measure(refs):
        calls.append(tuple(refs))
        return 7.25

    async def tariff(_telegram_id):
        return "standard"

    monkeypatch.setattr(pricing, "measure_video_reference_seconds", measure)
    monkeypatch.setattr(pricing, "get_actor_tariff", tariff)
    quote = await pricing.quote_video_for_actor(555, "seedance_2", 5, "720p", ["clip.mp4"])
    assert calls == [("clip.mp4",)]
    base = pricing.resolve_video_quote("seedance_2", 5, "720p").cost
    assert quote.cost == pricing.preset_manager._format_cost(base * (5 + 7.25) / 5)
    assert quote.input_video_seconds == 7.25


@pytest.mark.asyncio
async def test_refs_without_local_ownership_are_not_silently_undercounted():
    from bot.video_reference_policy import measure_video_reference_seconds
    with pytest.raises(ValueError, match="загрузите видео заново"):
        await measure_video_reference_seconds(["https://untrusted.example/video.mp4"])


def test_already_metered_wan_and_motion_are_not_billed_twice():
    for model in ("wan_3", "wan_3_prime", "motion_control_v26", "motion_control_v30"):
        assert apply_video_reference_cost(model, 20, ["clip.mp4"]) == 20
        assert apply_video_reference_cost(
            model, 20, ["clip.mp4"], output_seconds=5, reference_seconds=7,
        ) == 20


def test_unhandled_model_cannot_bill_video_references():
    with pytest.raises(ValueError, match="не принимает"):
        apply_video_reference_cost("grok_imagine", 20, ["clip.mp4"],
                                   output_seconds=5, reference_seconds=7)
