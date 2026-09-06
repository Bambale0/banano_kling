# ruff: noqa: I001
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot.handlers.seedance_25_public_release as public_release
import bot.miniapp as miniapp_module

from bot.handlers.seedance_25_fullstack import (
    MAX_VIDEO_PIXELS,
    MIN_VIDEO_PIXELS,
    _classify_results,
    _float_fraction,
    _seedance25_model_meta,
    _validate_dimensions,
)
from bot.handlers.seedance_25_public_release import _clean_other_new_markers
from bot.services.seedance_25_service import Seedance25Service, get_seedance25_callback_url
from bot.video_reference_policy import apply_video_reference_cost


def test_seedance25_model_meta_exposes_public_new_contract():
    meta = _seedance25_model_meta()

    assert meta["id"] == "seedance_2_5"
    assert meta["admin_only"] is False
    assert meta["is_new"] is True
    assert "NEW" in meta["label"]
    assert meta["seedance25_resolutions"] == ["480p", "720p"]
    assert meta["seedance25_output_formats"] == ["mp4", "mov"]
    assert meta["seedance25_scenarios"] == [
        "text",
        "first_frame",
        "first_last",
        "multimodal",
    ]
    assert meta["durations"][0] == -1
    assert meta["durations"][1:] == list(range(4, 31))
    assert meta["max_image_references"] == 30
    assert meta["max_video_references"] == 10
    assert meta["max_audio_references"] == 10
    assert meta["supports_generate_audio"] is True
    assert meta["supports_return_last_frame"] is True
    assert meta["supports_web_search"] is True
    assert meta["supports_nsfw_checker"] is True
    assert meta["camera_control_via_prompt"] is True


def test_seedance25_release_removes_new_markers_from_other_models():
    assert _clean_other_new_markers("Grok Imagine 1.5 NEW🔥🔥🔥") == "Grok Imagine 1.5"
    assert _clean_other_new_markers("Seedream 5 Pro 🔥 НОВИНКА") == "Seedream 5 Pro"
    assert _clean_other_new_markers("Nano Banana 2 Lite НОВИНКА") == "Nano Banana 2 Lite"


def test_seedance25_video_reference_doubles_price_once():
    assert apply_video_reference_cost("seedance_2_5", 20, []) == 20
    assert apply_video_reference_cost("seedance_2_5", 20, ["https://example.com/ref.mp4"]) == 40
    assert apply_video_reference_cost(
        "seedance_2_5",
        20,
        ["https://example.com/a.mp4", "https://example.com/b.mp4"],
    ) == 40


def test_seedance25_classifies_video_and_returned_last_frame():
    request_data = {"return_last_frame": True, "output_format": "mov"}
    video, frame = _classify_results(
        [
            "https://cdn.example/result.mov",
            "https://cdn.example/last-frame.png",
        ],
        request_data,
    )
    assert video == "https://cdn.example/result.mov"
    assert frame == "https://cdn.example/last-frame.png"


def test_seedance25_fraction_parser_handles_ffprobe_rates():
    assert _float_fraction("30/1") == 30.0
    assert _float_fraction("60000/1001") == pytest.approx(59.94005994)
    assert _float_fraction("0/0") == 0.0


def test_seedance25_video_geometry_enforces_spec_pixel_range():
    _validate_dimensions(640, 640, video=True)

    with pytest.raises(ValueError):
        _validate_dimensions(639, 640, video=True)

    # Still inside side/ratio limits but over the Kie per-frame pixel ceiling.
    assert 1000 * 1000 > MAX_VIDEO_PIXELS
    with pytest.raises(ValueError):
        _validate_dimensions(1000, 1000, video=True)

    assert 640 * 640 == MIN_VIDEO_PIXELS


@pytest.mark.asyncio
async def test_seedance25_rejects_reference_overflow_instead_of_truncating(monkeypatch):
    service = Seedance25Service(kie_key="test-key")

    async def unexpected_post(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("provider call must not happen")

    monkeypatch.setattr(service, "_kie_post", unexpected_post)
    result = await service.generate_video(
        prompt="test",
        reference_image_urls=[f"https://example.com/{idx}.png" for idx in range(31)],
    )
    assert result["success"] is False
    assert "at most 30" in result["error"]


def test_seedance25_dedicated_callback_path_when_host_available(monkeypatch):
    # The helper reuses the public Kie callback host and switches only the path.
    import bot.services.seedance_25_service as module

    monkeypatch.setattr(module.config, "WEBHOOK_HOST", "https://example.com")
    monkeypatch.setattr(module.config, "KIE_AI_WEBHOOK_PATH", "/webhook/kie_ai")
    monkeypatch.setattr(module.config, "KIE_AI_WEBHOOK_SECRET", "")
    assert get_seedance25_callback_url() == "https://example.com/webhook/kie_seedance25"


@pytest.mark.asyncio
async def test_seedance25_miniapp_repeat_keeps_source_lineage_and_rewards_author(monkeypatch):
    user = SimpleNamespace(id=501)
    monkeypatch.setattr(
        miniapp_module,
        '_get_user_context',
        AsyncMock(return_value=(700001, {'user': user})),
    )
    monkeypatch.setattr(public_release.config, 'is_admin', lambda _telegram_id: False)
    monkeypatch.setattr(
        miniapp_module,
        '_get_repeat_source_card',
        AsyncMock(return_value={'gen_type': 'video', 'model': 'seedance_2_5'}),
    )
    monkeypatch.setattr(miniapp_module, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp_module, 'deduct_credits', AsyncMock(return_value=True))
    monkeypatch.setattr(
        miniapp_module,
        'get_or_create_user',
        AsyncMock(return_value=SimpleNamespace(credits=88)),
    )
    repeat_credit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp_module, 'credit_feed_prompt_repeat', repeat_credit)
    add_task = AsyncMock(return_value=True)
    monkeypatch.setattr(public_release.generation_module, 'add_generation_task', add_task)
    monkeypatch.setattr(public_release, '_validate_public_payload', AsyncMock(return_value=None))
    monkeypatch.setattr(public_release.preview_module, '_price_quote', lambda _data: 12.0)
    monkeypatch.setattr(
        public_release,
        '_launch_provider',
        AsyncMock(return_value={'task_id': 'seedance-repeat-task'}),
    )

    response = await public_release._public_miniapp_generate(
        SimpleNamespace(app={}),
        {
            'init_data': 'signed',
            'v_model': 'seedance_2_5',
            'source_feed_gen_id': 42,
            'seedance25_scenario': 'text',
            'prompt': 'same prompt',
            'v_duration': 10,
            'v_ratio': '9:16',
            'seedance25_resolution': '720p',
        },
    )

    assert response.status == 200
    kwargs = add_task.await_args.kwargs
    assert kwargs['source_feed_gen_id'] == 42
    assert kwargs['parent_generation_id'] == 42
    assert kwargs['action_type'] == 'repeat'
    assert kwargs['request_data']['source'] == 'miniapp_repeat'
    repeat_credit.assert_awaited_once_with(
        42,
        501,
        repeat_task_id='seedance-repeat-task',
        credits_spent=12.0,
    )
