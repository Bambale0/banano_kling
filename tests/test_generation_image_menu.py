from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot.handlers import generation
from bot.states import GenerationStates


class FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value


@pytest.mark.asyncio
async def test_create_image_menu_uses_saved_primary_reference(monkeypatch):
    monkeypatch.setattr(database, "get_user_credits", AsyncMock(return_value=10))
    monkeypatch.setattr(
        generation,
        "get_primary_reference_asset",
        AsyncMock(return_value={"image_url": "https://u.test/main.jpg"}),
    )
    monkeypatch.setattr(generation, "track_event", AsyncMock())

    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.show_create_image_menu(callback, state)

    assert state.data["reference_images"] == ["https://u.test/main.jpg"]
    assert state.state == GenerationStates.uploading_reference_images
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_generated_image_seeds_result_as_reference(monkeypatch):
    task = database.GenerationTask(
        id=1,
        user_id=1,
        task_id="img_1",
        type="image",
        preset_id="seedream_edit",
        model="seedream_edit",
        aspect_ratio="9:16",
        result_url="https://u.test/generated.png",
        telegram_id=123,
    )
    monkeypatch.setattr(generation, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(generation, "get_user_credits", AsyncMock(return_value=20))

    callback = SimpleNamespace(
        data="edit_generated_image:img_1",
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.edit_generated_image(callback, state)

    assert state.data["reference_images"] == ["https://u.test/generated.png"]
    assert state.data["img_service"] == "seedream_edit"
    assert state.data["img_ratio"] == "9:16"
    assert state.state == GenerationStates.waiting_for_input
    callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_tryon_generated_image_uses_primary_and_clothing_refs(monkeypatch):
    task = database.GenerationTask(
        id=1,
        user_id=1,
        task_id="img_1",
        type="image",
        preset_id="seedream_edit",
        model="seedream_edit",
        aspect_ratio="1:1",
        result_url="https://u.test/outfit.png",
        telegram_id=123,
    )
    save_asset = AsyncMock()
    monkeypatch.setattr(generation, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(generation, "save_user_reference_asset", save_asset)
    monkeypatch.setattr(
        generation,
        "get_primary_reference_asset",
        AsyncMock(return_value={"image_url": "https://u.test/person.jpg"}),
    )
    monkeypatch.setattr(generation, "get_user_credits", AsyncMock(return_value=20))

    callback = SimpleNamespace(
        data="tryon_generated_image:img_1",
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    state = FakeState()

    await generation.try_on_generated_image(callback, state)

    assert state.data["reference_images"] == [
        "https://u.test/person.jpg",
        "https://u.test/outfit.png",
    ]
    assert state.data["img_service"] == "seedream_edit"
    assert state.state == GenerationStates.waiting_for_input
    save_asset.assert_awaited_once()
