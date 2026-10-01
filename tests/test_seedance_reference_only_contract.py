"""Regression contract for Seedance reference-only video inputs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers import generation as generation_module
from bot.handlers.seedance_multimodal_compat import (
    default_video_type,
    reference_only_seedance_media_inputs,
)
from bot.services.seedance_service import SeedanceService


def test_video_flow_defaults_to_photo_text_without_overriding_explicit_modes():
    assert default_video_type(None) == "imgtxt"
    assert default_video_type("text") == "text"
    assert default_video_type("video") == "video"


def test_seedance_media_builder_never_returns_first_frame():
    first_frame, images, videos = reference_only_seedance_media_inputs(
        "imgtxt",
        "https://files.example/one.png",
        [
            "https://files.example/two.png",
            "https://files.example/one.png",
            "https://files.example/three.png",
        ],
        ["https://files.example/motion.mp4"],
    )

    assert first_frame is None
    assert images == [
        "https://files.example/one.png",
        "https://files.example/two.png",
        "https://files.example/three.png",
    ]
    assert videos == ["https://files.example/motion.mp4"]


@pytest.mark.asyncio
async def test_seedance_provider_downgrades_legacy_first_frame_to_reference(monkeypatch):
    service = SeedanceService(kie_key="test-key")
    captured: dict = {}

    async def fake_prepare(image_urls):
        return list(image_urls), [], []

    async def fake_post(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"task_id": "seedance-test"}

    monkeypatch.setattr(service, "_prepare_image_urls", fake_prepare)
    monkeypatch.setattr(service, "_kie_post", fake_post)

    prompt = "A person walks through a city"
    result = await service.generate_video(
        prompt=prompt,
        duration=15,
        first_frame_url="https://files.example/person.png",
        reference_image_urls=["https://files.example/style.png"],
    )

    assert result == {"task_id": "seedance-test"}
    provider_input = captured["payload"]["input"]
    assert provider_input["prompt"] == prompt
    assert "first_frame_url" not in provider_input
    assert provider_input["reference_image_urls"] == [
        "https://files.example/person.png",
        "https://files.example/style.png",
    ]


class _PromptState:
    def __init__(self, data: dict):
        self.data = dict(data)

    async def get_state(self):
        return "GenerationStates:waiting_for_video_prompt"

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


class _PromptMessage:
    def __init__(self, text: str):
        self.text = text
        self.from_user = SimpleNamespace(id=123456789)
        self.answers: list[str] = []

    async def answer(self, text: str, *args, **kwargs):
        self.answers.append(text)


@pytest.mark.asyncio
async def test_seedance_prompt_accepts_reference_only_photo_from_media_step(monkeypatch):
    launched: dict[str, str] = {}

    async def fake_launch(message, state, prompt):
        launched["prompt"] = prompt

    monkeypatch.setattr(
        generation_module,
        "run_no_preset_video_from_message",
        fake_launch,
    )
    state = _PromptState(
        {
            "generation_type": "video",
            "v_type": "imgtxt",
            "v_model": "seedance_2",
            "v_image_url": None,
            "reference_images": ["https://files.example/reference.png"],
            "video_flow_step": "media",
        }
    )
    message = _PromptMessage("Оживить фото")

    await generation_module.handle_video_prompt_text(message, state)

    assert launched == {"prompt": "Оживить фото"}
    assert state.data["video_flow_step"] == "configure"
    assert state.data["user_prompt"] == "Оживить фото"
    assert not any("стартовое фото" in answer.lower() for answer in message.answers)
