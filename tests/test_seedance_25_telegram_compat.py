from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from aiogram.dispatcher.event.bases import SkipHandler

from bot.handlers import seedance_25_telegram_compat as module


class FakeState:
    def __init__(self, data):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)


class FakeMessage:
    def __init__(self):
        self.from_user = SimpleNamespace(id=123)
        self.document = None
        self.photo = [SimpleNamespace(file_id="photo-1")]
        self.answers: list[str] = []

    async def answer(self, text, **_kwargs):
        self.answers.append(text)


class FakeCallback:
    def __init__(self, task_id="task-1"):
        self.data = f"repeat_video_result_{task_id}"
        self.from_user = SimpleNamespace(id=123)
        self.message = SimpleNamespace()
        self.answers: list[tuple[str, dict]] = []

    async def answer(self, text="", **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_public_first_frame_photo_is_stored_as_first_frame(monkeypatch):
    state = FakeState(
        {
            "v_model": module.MODEL_KEY,
            "seedance25_scenario": "first_frame",
            "reference_images": ["https://example.com/old-ref.png"],
            "v_reference_videos": ["https://example.com/old-ref.mp4"],
            "seedance25_reference_audio_urls": ["https://example.com/old-ref.mp3"],
        }
    )
    message = FakeMessage()

    async def fake_persist(_message, _obj):
        return "https://tanyapi.chillcreative.ru/uploads/refs/image/123/first.png"

    async def fake_show(_message, _state, *, edit=False):
        assert edit is False

    monkeypatch.setattr(module, "_persist_image", fake_persist)
    monkeypatch.setattr(module.preview_module, "_show_seedance_25_screen", fake_show)

    await module.seedance25_public_image_upload(message, state)

    assert state.data["seedance25_first_frame_url"].endswith("/first.png")
    assert state.data["seedance25_last_frame_url"] is None
    assert state.data["reference_images"] == []
    assert state.data["v_reference_videos"] == []
    assert state.data["seedance25_reference_audio_urls"] == []
    assert any("Первый кадр сохранён" in item for item in message.answers)


@pytest.mark.asyncio
async def test_repeat_seedance25_restores_multimodal_references_and_original_shape(monkeypatch):
    request_data = {
        # Legacy preview schema is intentional: repeat must also work for tasks
        # created before the public request_data schema was aligned.
        "v_model": module.MODEL_KEY,
        "scenario": "multimodal",
        "reference_images": ["https://example.com/ref-1.png", "https://example.com/ref-2.png"],
        "reference_videos": ["https://example.com/ref.mp4"],
        "reference_audios": ["https://example.com/ref.mp3"],
        "resolution": "480p",
        "generate_audio": False,
        "return_last_frame": True,
        "output_format": "mov",
        "web_search": True,
        "nsfw_checker": True,
    }
    task = SimpleNamespace(
        id="task-1",
        type="video",
        model=module.MODEL_KEY,
        user_id=77,
        prompt="keep the same character and motion",
        duration=12,
        aspect_ratio="9:16",
        cost=48,
        request_data=json.dumps(request_data),
    )
    state = FakeState({"seedance25_scenario": "text", "reference_images": []})
    callback = FakeCallback()
    launched = {}

    async def fake_get_task(_task_id):
        return task

    async def fake_get_user(_telegram_id):
        return SimpleNamespace(id=77)

    async def fake_launch(cb, launch_state, prompt, cost, is_admin):
        launched.update(
            callback=cb,
            prompt=prompt,
            cost=cost,
            is_admin=is_admin,
            data=await launch_state.get_data(),
        )

    monkeypatch.setattr(module.generation_module, "get_task_by_id", fake_get_task)
    monkeypatch.setattr(module.generation_module, "get_or_create_user", fake_get_user)
    monkeypatch.setattr(module.generation_module, "run_no_preset_video_from_callback", fake_launch)
    monkeypatch.setattr(module.generation_module.config, "is_admin", lambda _user_id: False)

    await module.seedance25_repeat_video_result(callback, state)

    assert launched["prompt"] == task.prompt
    assert launched["cost"] == 48.0
    assert launched["is_admin"] is False
    assert launched["data"]["seedance25_scenario"] == "multimodal"
    assert launched["data"]["v_type"] == "video"
    assert launched["data"]["v_duration"] == 12
    assert launched["data"]["v_ratio"] == "9:16"
    assert launched["data"]["seedance25_resolution"] == "480p"
    assert launched["data"]["reference_images"] == request_data["reference_images"]
    assert launched["data"]["v_reference_videos"] == request_data["reference_videos"]
    assert launched["data"]["seedance25_reference_audio_urls"] == request_data["reference_audios"]
    assert launched["data"]["seedance25_generate_audio"] is False
    assert launched["data"]["seedance25_return_last_frame"] is True
    assert launched["data"]["seedance25_output_format"] == "mov"
    assert launched["data"]["seedance25_web_search"] is True
    assert launched["data"]["seedance25_nsfw_checker"] is True
    assert any("по референсам" in text for text, _ in callback.answers)


@pytest.mark.asyncio
async def test_repeat_handler_skips_other_video_models(monkeypatch):
    task = SimpleNamespace(
        type="video",
        model="grok_video",
        request_data=json.dumps({"v_model": "grok_video"}),
    )

    async def fake_get_task(_task_id):
        return task

    monkeypatch.setattr(module.generation_module, "get_task_by_id", fake_get_task)

    with pytest.raises(SkipHandler):
        await module.seedance25_repeat_video_result(FakeCallback(), FakeState({}))


def test_clear_keyboard_uses_human_scenario_labels_and_keeps_controls():
    markup = module._clear_seedance_keyboard(
        {
            "seedance25_scenario": "first_frame",
            "seedance25_resolution": "720p",
            "v_ratio": "adaptive",
            "v_duration": 9,
            "seedance25_generate_audio": True,
            "seedance25_return_last_frame": False,
            "seedance25_output_format": "mp4",
            "seedance25_web_search": False,
            "seedance25_nsfw_checker": False,
        }
    )
    buttons = [button for row in markup.inline_keyboard for button in row]
    texts = [button.text for button in buttons]
    callbacks = {button.callback_data for button in buttons}

    assert any("Оживить фото" in text for text in texts)
    assert any("Между 2 фото" in text for text in texts)
    assert any("9 сек" in text for text in texts)
    assert "s25_scenario_first_frame" in callbacks
    assert "s25_duration_minus" in callbacks
    assert "s25_duration_plus" in callbacks
    assert "s25_toggle_audio" in callbacks
