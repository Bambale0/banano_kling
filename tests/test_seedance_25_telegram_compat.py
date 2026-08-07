from __future__ import annotations

from types import SimpleNamespace

import pytest

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
