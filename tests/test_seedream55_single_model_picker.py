"""Regression: one Seedream 5.5 model entry, with layers as an inner mode."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import generation
from bot.keyboards import get_create_image_keyboard, get_image_model_selection_keyboard


def callbacks(keyboard):
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]


def buttons(keyboard):
    return [
        button for row in keyboard.inline_keyboard for button in row
    ]


@pytest.mark.parametrize("selected", ["seedream_55", "seedream_55_layers"])
def test_only_one_seedream55_model_picker_entry(selected):
    keyboard = get_image_model_selection_keyboard(selected)
    ids = callbacks(keyboard)
    assert ids.count("model_seedream_55") == 1
    assert "model_seedream_55_layers" not in ids
    labels = [button.text for button in buttons(keyboard) if button.callback_data == "model_seedream_55"]
    assert len(labels) == 1
    assert labels[0].startswith("✅ ")


def test_layers_are_configured_inside_one_model():
    normal = callbacks(get_create_image_keyboard(current_service="seedream_55"))
    layers = callbacks(get_create_image_keyboard(current_service="seedream_55_layers"))
    assert "seedream55_toggle_layers_mode" in normal
    assert "seedream55_toggle_layers_mode" in layers
    assert "seedream55_cycle_background" in normal
    assert "seedream55_cycle_layers" not in normal
    assert "seedream55_cycle_layers" in layers
    assert "seedream55_toggle_text" in layers


class FakeState:
    def __init__(self, **data):
        self.data = data

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **updates):
        self.data.update(updates)


@pytest.mark.asyncio
async def test_toggle_to_layers_with_one_reference(monkeypatch):
    screen = AsyncMock()
    ref_screen = AsyncMock()
    monkeypatch.setattr(generation, "_show_image_creation_screen", screen)
    monkeypatch.setattr(generation, "_show_image_references_screen", ref_screen)
    state = FakeState(img_service="seedream_55", img_ratio="9:16", reference_images=["https://example.com/image.png"])
    callback = SimpleNamespace(answer=AsyncMock())
    await generation.handle_seedream55_toggle_layers_mode(callback, state)
    assert state.data["img_service"] == "seedream_55_layers"
    assert state.data["img_ratio"] == "1:1"
    screen.assert_awaited_once()
    ref_screen.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_without_reference_opens_ref_step(monkeypatch):
    screen = AsyncMock()
    refs = AsyncMock()
    monkeypatch.setattr(generation, "_show_image_creation_screen", screen)
    monkeypatch.setattr(generation, "_show_image_references_screen", refs)
    state = FakeState(img_service="seedream_55", reference_images=[])
    callback = SimpleNamespace(answer=AsyncMock())
    await generation.handle_seedream55_toggle_layers_mode(callback, state)
    assert state.data["img_service"] == "seedream_55_layers"
    assert state.data["img_flow_step"] == "upload_refs"
    refs.assert_awaited_once()
    screen.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_with_multiple_refs_does_not_silently_drop_images(monkeypatch):
    screen = AsyncMock()
    monkeypatch.setattr(generation, "_show_image_creation_screen", screen)
    state = FakeState(img_service="seedream_55", reference_images=["one", "two"])
    callback = SimpleNamespace(answer=AsyncMock())
    await generation.handle_seedream55_toggle_layers_mode(callback, state)
    assert state.data["img_service"] == "seedream_55"
    screen.assert_not_awaited()
    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_can_switch_back_to_regular_generation(monkeypatch):
    screen = AsyncMock()
    monkeypatch.setattr(generation, "_show_image_creation_screen", screen)
    state = FakeState(img_service="seedream_55_layers", reference_images=["one"])
    callback = SimpleNamespace(answer=AsyncMock())
    await generation.handle_seedream55_toggle_layers_mode(callback, state)
    assert state.data["img_service"] == "seedream_55"
    screen.assert_awaited_once()
