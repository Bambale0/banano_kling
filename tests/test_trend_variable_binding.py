"""Real trend assembly must replace the user's display variables, never the scene."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.trend_api import trusted_trend_run
from bot.trend_user_fields import normalize_user_fields_settings
from bot.trend_visibility import public_trend_settings


def trend(prompt: str, kind: str, label: str, **field: object):
    return {
        "id": 1605,
        "status": "approved",
        "is_public": True,
        "tags": ["trend"],
        "model": "seedance_2_5" if kind == "video" else "banana_pro",
        "prompt_text": prompt,
        "generation_settings": {
            "kind": kind,
            "user_input": "photo",
            "model": "seedance_2_5" if kind == "video" else "banana_pro",
            "ratio": "9:16",
            "duration": 10,
            "user_fields": [{"key": label, "label": label, **field}],
        },
    }


@pytest.mark.parametrize("kind", ["video", "image"])
@pytest.mark.parametrize("literal", ["«37»", "37", "«30»"])
def test_numeric_display_variable_replaces_original_without_breaking_scene(kind, literal):
    base = (
        f"@Image1 is the heroine in a cinematic birthday scene. "
        f"She holds a black cake with burning golden свечи-цифры {literal}. "
        "Camera slowly tracks her face while she blows out the candles. "
        "At [00:02–00:05] sparks reflect on the lens. Keep the music and lighting."
    )
    item = trend(base, kind, "Цифры")
    rendered = trusted_trend_run(item, ("https://example.test/ref.jpg",), {"Цифры": "2"}).prompt
    assert f"свечи-цифры {literal}" not in rendered
    assert "свечи-цифры" in rendered and "2" in rendered
    assert "@Image1" in rendered
    assert "At [00:02–00:05]" in rendered
    assert "Camera slowly tracks her face" in rendered
    assert "music and lighting" in rendered
    assert "одна цифра" in rendered.lower()


def test_numeric_display_does_not_rewrite_timecodes_camera_or_reference_indices():
    item = trend(
        "@Image1 moves in front of 30fps camera. Golden свечи-цифры «37» "
        "on the cake. At 00:02 she lights one candle.",
        "video", "Цифры",
    )
    result = trusted_trend_run(item, ("https://example.test/ref.jpg",), {"Цифры": "18"}).prompt
    assert "свечи-цифры «18»" in result
    assert "30fps" in result
    assert "00:02" in result
    assert "@Image1" in result


def test_admin_exact_old_value_binding_and_private_source():
    item = trend(
        "Golden cake reads 37. The clock shows 00:02. Cinematic orbit on @Image1.",
        "video", "Цифры", original_value="37",
    )
    normalized = normalize_user_fields_settings(item["generation_settings"], prompt=item["prompt_text"])
    item["generation_settings"] = normalized
    rendered = trusted_trend_run(item, ("https://example.test/ref.jpg",), {"Цифры": "2"}).prompt
    assert "Golden cake reads 2." in rendered
    assert "The clock shows 00:02." in rendered
    assert "Cinematic orbit" in rendered
    public = public_trend_settings(item)
    assert "original_value" not in public["user_fields"][0]
    assert "37" not in str(public)


def test_unbound_nonnumeric_variable_keeps_complete_base_and_appends_change():
    item = trend("Portrait, green flowers, soft side light, @Image1.", "image", "Цвет")
    result = trusted_trend_run(item, ("https://example.test/ref.jpg",), {"Цвет": "красный"}).prompt
    assert result.startswith("Portrait, green flowers, soft side light, @Image1.")
    assert "красный" in result


@pytest.mark.asyncio
async def test_installed_seedance_video_wrapper_accepts_authoritative_quote_without_double_quoting(monkeypatch):
    from bot import trend_api
    from bot.handlers import trend_seedance_25_compat as compat

    generic = AsyncMock(return_value="generic")
    special = AsyncMock(return_value="seedance")
    monkeypatch.setattr(trend_api, "_run_video_trend", generic)
    monkeypatch.setattr(trend_api, "_seedance25_trend_compat_installed", False, raising=False)
    monkeypatch.setattr(compat, "_run_seedance25_trend", special)
    compat.install_trend_seedance_25_compat()

    q = SimpleNamespace(cost=99.0, charge_cost=99.0)
    user = SimpleNamespace(id=1)
    result_generic = await trend_api._run_video_trend(
        telegram_id=1, user=user, trend=SimpleNamespace(model="seedance_2"), billing_quote=q,
    )
    result_seedance = await trend_api._run_video_trend(
        telegram_id=1, user=user, trend=SimpleNamespace(model="seedance_2_5"), billing_quote=q,
    )
    assert result_generic == "generic"
    assert result_seedance == "seedance"
    generic.assert_awaited_once_with(
        telegram_id=1, user=user, trend=SimpleNamespace(model="seedance_2"), billing_quote=q,
    )
    assert special.await_args.kwargs["billing_quote"] is q


def test_forbidden_mirrored_example_does_not_override_positive_number():
    text = (
        "She paints цифры 37 on the pavement. When the candle lights, "
        "the цифры «37» ignite and the camera follows. "
        "ЗАПРЕЩЕНО писать число «73» или зеркалить цифры — только правильное «37»."
    )
    item = trend(text, "video", "Цифры")
    result = trusted_trend_run(item, ("https://example.test/ref.jpg",), {"Цифры": "2"}).prompt
    assert "цифры 2" in result and "цифры «2»" in result
    assert "цифры 37" not in result and "только правильное «37»" not in result
    assert "She paints" in result and "the camera follows" in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("editing", "duration", "resolution", "expected_duration"),
    [(False, 6, "480p", 6), (False, 10, "720p", 10), (True, -1, "720p", 12)],
)
async def test_seedance25_trend_quote_matches_exact_provider_duration_and_quality(
    monkeypatch, editing, duration, resolution, expected_duration,
):
    from bot import miniapp, trend_api
    quote = SimpleNamespace(cost=21, charge_cost=21)
    get_quote = AsyncMock(return_value=quote)
    monkeypatch.setattr(trend_api, "quote_video_for_actor", get_quote)
    monkeypatch.setattr(miniapp, "_resolve_gemini_omni_model", lambda model, _scenario: model)
    run = trend_api.TrustedTrendRun(
        trend_id=1883, kind="video", prompt="source", model="seedance_2_5", ratio="9:16",
        reference_urls=("https://example.test/face.jpg",),
        settings={
            "duration": duration, "seedance25_resolution": resolution,
            "seedance25_video_editing": editing,
            "source_video_duration_seconds": 12,
        },
    )
    result = await trend_api._quote_trend_video(123, run)
    assert result is quote
    get_quote.assert_awaited_once_with(
        123, "seedance_2_5", expected_duration, resolution, (),
    )


@pytest.mark.asyncio
async def test_seedance25_provider_receives_bound_private_scene_and_one_authoritative_quote(
    monkeypatch,
):
    from bot import miniapp as miniapp_module
    from bot import trend_api
    from bot.handlers import trend_seedance_25_compat as compat

    base = "At [00:02–00:05] woman @Image1 holds black cake, золотые свечи-цифры «37». Camera pans to face."
    run = trusted_trend_run(
        trend(base, "video", "Цифры"),
        ("https://example.test/face.jpg",),
        {"Цифры": "2"},
    )
    quote = SimpleNamespace(cost=24.0, charge_cost=24.0, duration=10, quality="720p")
    no_requote = AsyncMock(side_effect=AssertionError("Unexpected second pricing"))
    monkeypatch.setattr(compat, "quote_video_for_actor", no_requote)
    monkeypatch.setattr(compat.public_release, "_public_model_meta", lambda: {
        "ratios": ["9:16"], "durations": [10],
    })
    monkeypatch.setattr(miniapp_module, "get_video_model_label", lambda _: "Seedance 2.5")
    monkeypatch.setattr(trend_api, "_validate_uploaded_references", lambda *_args: None)
    monkeypatch.setattr(trend_api, "touch_saved_references", AsyncMock())
    debit = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(trend_api, "_debit_for_generation", debit)
    monkeypatch.setattr(trend_api, "_record_trend_use", AsyncMock())
    monkeypatch.setattr(compat.public_release, "_validate_public_payload", AsyncMock())
    provider = AsyncMock(return_value={"task_id": "mock-provider-trend"})
    monkeypatch.setattr(compat.public_release, "_launch_provider", provider)
    monkeypatch.setattr(compat.public_release, "_request_data", lambda _p, **_kwargs: {})
    monkeypatch.setattr(compat.generation_module, "add_generation_task", AsyncMock())
    monkeypatch.setattr(
        compat.generation_module, "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=76)),
    )
    user = SimpleNamespace(id=123, credits=100)
    response = await compat._run_seedance25_trend(
        telegram_id=123, user=user, trend=run, billing_quote=quote,
    )
    assert response.status == 200
    provider.assert_awaited_once()
    payload = provider.await_args.args[0]
    assert payload["prompt"].startswith("At [00:02–00:05] woman @Image1")
    assert "свечи-цифры «2»" in payload["prompt"]
    assert "свечи-цифры «37»" not in payload["prompt"]
    assert "Camera pans to face" in payload["prompt"]
    assert "одна цифра" in payload["prompt"]
    no_requote.assert_not_awaited()
    debit.assert_awaited_once_with(123, user, quote.cost)


def test_invalid_admin_source_binding_is_rejected_before_publication():
    from bot.trend_user_fields import TrendUserFieldsError
    data = trend("Age 37, cake, cinema", "video", "Возраст", original_value="29")
    with pytest.raises(TrendUserFieldsError, match="не найдено"):
        normalize_user_fields_settings(data["generation_settings"], prompt=data["prompt_text"])


def test_legacy_token_enforces_single_digit_on_candles_and_reference_photo():
    item = trend(
        "At [00:02] @Image1 holds a cake with candles {{Цифры}}. "
        "She blows them out. Keep the original movement.",
        "video", "Цифры",
    )
    output = trusted_trend_run(
        item, ("https://example.test/ref.jpg",), {"Цифры": "2"},
    ).prompt
    assert "candles 2" in output
    assert "одна цифра" in output
    assert "референс" in output
    assert "@Image1" in output and "[00:02]" in output


def test_ambiguous_old_numbers_do_not_change_unrelated_objects():
    item = trend(
        "The heroine paints цифры 37 near the cake, then shows цифры 52 "
        "on a distinct clock. @Image1 and camera at [00:02] stay unchanged.",
        "video", "Цифры",
    )
    output = trusted_trend_run(
        item, ("https://example.test/ref.jpg",), {"Цифры": "2"},
    ).prompt
    assert output.startswith(item["prompt_text"])
    assert "- Цифры: 2" in output
    assert "@Image1" in output
