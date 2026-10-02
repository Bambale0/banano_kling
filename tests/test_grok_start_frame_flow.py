from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image

from bot.handlers import generation
from bot.handlers import video_generation_compat as advanced
from bot.services.grok_service import GROK_V15_VIDEO_MODEL
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.states import GenerationStates

START_URL = "https://cdn.example.org/grok-start.jpg"
PROMPT = "Animate the uploaded photo naturally, without speech."
MODELS = ["grok_imagine", "grok_imagine_v15"]


def message(*, text=None, media=None):
    item = MagicMock(spec=types.Message)
    item.from_user = SimpleNamespace(id=12345)
    item.chat = SimpleNamespace(id=12345)
    item.message_id = 101
    item.text = text
    item.caption = None
    item.model_copy = lambda *, update: message(text=update.get("text", text))
    item.photo = []
    item.document = None
    item.media_group_id = None
    item.answer = AsyncMock(return_value=SimpleNamespace(delete=AsyncMock()))
    item.edit_text = AsyncMock()
    if media:
        image = io.BytesIO()
        image_format = {"image/png": "PNG", "image/webp": "WEBP"}.get(media, "JPEG")
        Image.new("RGB", (400, 400)).save(image, format=image_format)
        image.seek(0)
        photo = SimpleNamespace(file_id="fixture-photo", file_size=len(image.getvalue()))
        if media == "photo":
            item.photo = [photo]
        else:
            photo.mime_type = media
            item.document = photo
        item.bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_path="fixture/photo")),
            download_file=AsyncMock(return_value=image),
        )
    return item


def callback(model):
    item = MagicMock(spec=types.CallbackQuery)
    item.from_user = SimpleNamespace(id=12345)
    item.data = f"advanced_v_model_{model}"
    item.message = message()
    item.answer = AsyncMock()
    return item


@pytest.fixture
async def state():
    storage = MemoryStorage()
    value = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=12345, user_id=12345))
    yield value
    await storage.close()


@pytest.fixture
def boundary(monkeypatch):
    """Exercise real handlers and provider adapter; mock external side effects only."""
    get_user = AsyncMock(return_value=SimpleNamespace(id=7, credits=100))
    debit = AsyncMock(return_value=True)
    refund = AsyncMock(return_value=True)
    task = AsyncMock()
    post = AsyncMock(return_value={"task_id": "grok-fixture-task"})
    persist = AsyncMock(return_value=START_URL)
    monkeypatch.setattr(generation, "get_user_credits", AsyncMock(return_value=100))
    monkeypatch.setattr(generation, "get_or_create_user", get_user)
    monkeypatch.setattr(generation, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(generation, "deduct_credits", debit)
    monkeypatch.setattr(generation, "add_credits", refund)
    monkeypatch.setattr(generation, "add_generation_task", task)
    monkeypatch.setattr(generation, "_persist_reusable_image_reference", persist)
    monkeypatch.setattr(generation.config, "is_admin", lambda _user: False)
    monkeypatch.setattr(generation.preset_manager, "get_video_cost_with_quality", lambda *_args: 6)
    monkeypatch.setattr(generation.grok_service, "_kie_post", post)

    async def uploaded(sources, **_kwargs):
        return sources

    monkeypatch.setattr(kie_file_upload_service, "upload_local_image_sources", uploaded)
    return SimpleNamespace(debit=debit, refund=refund, task=task, post=post, persist=persist)


@pytest.mark.parametrize("model", MODELS)
async def test_public_advanced_grok_selection_requires_photo(model, state, boundary):
    await advanced.select_advanced_video_model(callback(model), state)
    data = await state.get_data()
    assert data["v_model"] == model
    assert data["v_type"] == "imgtxt"
    assert await state.get_state() == GenerationStates.waiting_for_video_prompt.state
    boundary.debit.assert_not_awaited()
    boundary.post.assert_not_awaited()


@pytest.mark.parametrize("media", ["photo", "image/jpeg", "image/png", "image/webp"])
@pytest.mark.parametrize("model", MODELS)
async def test_public_grok_photo_then_prompt_reaches_provider(model, media, state, boundary):
    await advanced.select_advanced_video_model(callback(model), state)
    photo = message(media=media)
    await generation.process_photo_for_video_prompt_state(photo, state)
    assert (await state.get_data()).get("v_image_url") == START_URL
    photo.bot.download_file.assert_awaited_once()
    boundary.debit.assert_not_awaited()
    boundary.post.assert_not_awaited()

    await generation.handle_video_prompt_text(message(text=PROMPT), state)
    boundary.post.assert_awaited_once()
    endpoint, payload = boundary.post.await_args.args
    assert endpoint == "/api/v1/jobs/createTask"
    assert payload["model"] == (
        "grok-imagine/image-to-video" if model == "grok_imagine" else GROK_V15_VIDEO_MODEL
    )
    assert payload["input"]["image_urls"] == [START_URL]
    assert payload["input"]["prompt"] == PROMPT
    boundary.debit.assert_awaited_once_with(12345, 6)
    boundary.refund.assert_not_awaited()
    boundary.task.assert_awaited_once()
    saved = boundary.task.await_args.kwargs["request_data"]
    assert saved["v_image_url"] == START_URL
    assert saved["v_type"] == "imgtxt"
    assert saved["v_model"] == model


@pytest.mark.parametrize("old_type", [None, "text", "video"])
@pytest.mark.parametrize("model", MODELS)
async def test_existing_grok_session_accepts_photo_without_reselection(model, old_type, state, boundary):
    await state.update_data(
        generation_type="video", v_model=model, v_type=old_type,
        video_flow_step="configure", reference_images=[], grok_mode="fun",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await generation.process_photo_for_video_prompt_state(message(media="photo"), state)
    data = await state.get_data()
    assert data.get("v_image_url") == START_URL
    assert data["v_type"] == "imgtxt"
    assert data["grok_mode"] == "fun"
    boundary.debit.assert_not_awaited()
    boundary.post.assert_not_awaited()


@pytest.mark.parametrize("old_type", ["text", "imgtxt"])
@pytest.mark.parametrize("model", MODELS)
async def test_missing_grok_photo_is_rejected_before_billing_and_preserves_prompt(model, old_type, state, boundary):
    await state.update_data(
        generation_type="video", v_model=model, v_type=old_type,
        video_flow_step="configure", v_image_url=None, grok_mode="fun",
    )
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await generation.handle_video_prompt_text(message(text=PROMPT), state)
    boundary.debit.assert_not_awaited()
    boundary.refund.assert_not_awaited()
    boundary.post.assert_not_awaited()
    boundary.task.assert_not_awaited()
    data = await state.get_data()
    assert data["user_prompt"] == PROMPT
    assert data["v_model"] == model
    assert data["v_type"] == "imgtxt"
    assert data["grok_mode"] == "fun"
    assert await state.get_state() == GenerationStates.waiting_for_video_prompt.state


@pytest.mark.parametrize("model, expected", [
    ("v3_pro", "text"), ("veo3", "text"), ("seedance_2", "text"),
    ("motion_control_v26", "motion"), ("avatar_std", "avatar"),
    ("gemini_omni_audio", "audio"), ("gemini_omni_character", "character"),
])
def test_non_grok_initial_modes_unchanged(model, expected):
    assert advanced._initial_type_for_model(model) == expected


@pytest.mark.parametrize("model", MODELS)
async def test_registered_router_photo_prompt_journey(model, state, boundary, monkeypatch):
    from bot.handlers import generation_router, prompt_fragment_coalescer

    monkeypatch.setattr(prompt_fragment_coalescer, "quiet_seconds", 0.01)
    query = callback(model)
    routing_bot = MagicMock()
    await generation_router.propagate_event(
        update_type="callback_query", event=query, state=state, raw_state=None, bot=routing_bot,
    )
    assert (await state.get_data())["v_type"] == "imgtxt"
    await generation_router.propagate_event(
        update_type="message", event=message(media="photo"), state=state,
        raw_state=await state.get_state(), bot=routing_bot,
    )
    assert (await state.get_data())["v_image_url"] == START_URL
    await generation_router.propagate_event(
        update_type="message", event=message(text=PROMPT), state=state,
        raw_state=await state.get_state(), bot=routing_bot,
    )
    # Await the actual prompt-coalescing task, not an arbitrary sleep.
    tasks = [p.task for p in prompt_fragment_coalescer._pending.values() if p.task]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    boundary.post.assert_awaited_once()
    assert boundary.post.await_args.args[1]["input"]["image_urls"] == [START_URL]
    boundary.debit.assert_awaited_once_with(12345, 6)
    boundary.refund.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
async def test_grok_recovery_after_missing_photo(model, state, boundary):
    await advanced.select_advanced_video_model(callback(model), state)
    await generation.handle_video_prompt_text(message(text=PROMPT), state)
    boundary.debit.assert_not_awaited()
    await generation.process_photo_for_video_prompt_state(message(media="photo"), state)
    await generation.handle_video_prompt_text(message(text=PROMPT), state)
    boundary.post.assert_awaited_once()
    boundary.debit.assert_awaited_once_with(12345, 6)
    boundary.refund.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
async def test_invalid_photo_is_not_persisted_or_billed(model, state, boundary):
    await advanced.select_advanced_video_model(callback(model), state)
    photo = message(media="photo")
    photo.bot.download_file.return_value = io.BytesIO(b"not an image")
    await generation.process_photo_for_video_prompt_state(photo, state)
    assert (await state.get_data()).get("v_image_url") is None
    boundary.persist.assert_not_awaited()
    boundary.debit.assert_not_awaited()
    boundary.post.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
async def test_reference_limit_and_original_start_frame_are_preserved(model, state, boundary):
    await advanced.select_advanced_video_model(callback(model), state)
    start = "https://cdn.example.org/original.jpg"
    limit = generation.get_max_video_image_references(model)
    refs = [f"https://cdn.example.org/ref-{i}.jpg" for i in range(limit - 1)]
    await state.update_data(v_image_url=start, reference_images=refs)
    await generation.process_photo_for_video_prompt_state(message(media="photo"), state)
    saved = await state.get_data()
    assert saved["v_image_url"] == start
    assert saved["reference_images"] == refs
    boundary.debit.assert_not_awaited()
    boundary.post.assert_not_awaited()
