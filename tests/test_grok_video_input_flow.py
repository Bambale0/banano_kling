"""Regressions for advanced Grok selection -> photo -> text -> provider payload."""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, types
from aiogram.client.session.base import BaseSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from PIL import Image

from bot.handlers import generation_router, prompt_fragment_coalescer
from bot.handlers import generation as generation_module
from bot.services.grok_service import grok_service as grok_service_instance
from bot.services.kie_file_upload_service import kie_file_upload_service
from bot.states import GenerationStates

REF_URL = "https://fixture.invalid/start.png"
PROMPT = "Animate naturally without speech"
MODELS = ("grok_imagine", "grok_imagine_v15")


class RecordingSession(BaseSession):
    """No Telegram network; keep real Message/CallbackQuery answer methods."""
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ in {"sendMessage", "editMessageText"}:
            return types.Message(
                message_id=1000 + len(self.calls),
                date=datetime.now(timezone.utc),
                chat=types.Chat(id=12345, type="private"),
                text=method.text,
            ).as_(bot)
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("A test attempted real Telegram download")
        yield b""  # pragma: no cover


@pytest.fixture
async def flow(monkeypatch):
    session = RecordingSession()
    bot = Bot("123456:TEST_TOKEN_FOR_GROK_REGRESSION", session=session)
    storage = MemoryStorage()
    state = FSMContext(storage, StorageKey(bot_id=bot.id, chat_id=12345, user_id=12345))
    user = types.User(id=12345, is_bot=False, first_name="Test")
    image = io.BytesIO()
    Image.new("RGB", (600, 800)).save(image, format="PNG")
    monkeypatch.setattr(bot, "get_file", AsyncMock(return_value=types.File(
        file_id="photo", file_unique_id="photo_unique", file_path="photos/test.png"
    )))
    monkeypatch.setattr(bot, "download_file", AsyncMock(side_effect=lambda *a, **k: io.BytesIO(image.getvalue())))
    persist = AsyncMock(return_value=REF_URL)
    monkeypatch.setattr(generation_module, "_persist_reusable_image_reference", persist)
    monkeypatch.setattr(generation_module, "get_user_credits", AsyncMock(return_value=100))
    monkeypatch.setattr(generation_module, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=77, credits=100)))
    monkeypatch.setattr(generation_module, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(generation_module.config, "is_admin", lambda *_: False)
    debit = AsyncMock(return_value=True)
    refund = AsyncMock(return_value=True)
    record = AsyncMock()
    monkeypatch.setattr(generation_module, "deduct_credits", debit)
    monkeypatch.setattr(generation_module, "add_credits", refund)
    monkeypatch.setattr(generation_module, "add_generation_task", record)
    post = AsyncMock(return_value={"task_id": "grok-test-task"})
    monkeypatch.setattr(grok_service_instance, "_kie_post", post)
    monkeypatch.setattr(kie_file_upload_service, "upload_local_image_sources", AsyncMock(side_effect=lambda sources: sources))
    monkeypatch.setattr(prompt_fragment_coalescer, "quiet_seconds", 0.01)

    def message(**kwargs):
        return types.Message(
            message_id=1, date=datetime.now(timezone.utc),
            chat=types.Chat(id=user.id, type="private"), from_user=user, **kwargs,
        ).as_(bot)

    def callback(data):
        return types.CallbackQuery(
            id="query", from_user=user, chat_instance="chat",
            message=message(text="Choose model"), data=data,
        ).as_(bot)

    async def dispatch(event):
        event_type = "callback_query" if isinstance(event, types.CallbackQuery) else "message"
        await generation_router.propagate_event(
            update_type=event_type, event=event, state=state,
            raw_state=await state.get_state(), bot=bot,
        )
        # Await the real prompt coalescer rather than guessing a sleep duration.
        tasks = [entry.task for entry in prompt_fragment_coalescer._pending.values() if entry.task]
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    yield SimpleNamespace(
        state=state, bot=bot, session=session, message=message, callback=callback,
        dispatch=dispatch, persist=persist, debit=debit, refund=refund, record=record, post=post,
    )
    await storage.close()
    await bot.session.close()


def photo_message(flow, kind="photo"):
    if kind == "document":
        return flow.message(document=types.Document(
            file_id="photo", file_unique_id="photo_unique", mime_type="image/png",
            file_name="photo.png",
        ))
    return flow.message(photo=[types.PhotoSize(
        file_id="photo", file_unique_id="photo_unique", width=600, height=800,
    )])


@pytest.mark.parametrize("model", MODELS)
async def test_advanced_selection_requires_image_type(flow, model):
    await flow.dispatch(flow.callback(f"advanced_v_model_{model}"))
    data = await flow.state.get_data()
    assert data["v_model"] == model
    assert data["v_type"] == "imgtxt"
    assert await flow.state.get_state() == GenerationStates.waiting_for_video_prompt.state


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("kind", ("photo", "document"))
async def test_advanced_photo_then_text_reaches_provider_with_start_image(flow, model, kind):
    await flow.dispatch(flow.callback(f"advanced_v_model_{model}"))
    await flow.dispatch(photo_message(flow, kind))
    assert (await flow.state.get_data()).get("v_image_url") == REF_URL
    await flow.dispatch(flow.message(text=PROMPT))
    flow.post.assert_awaited_once()
    payload = flow.post.await_args.args[1]
    assert payload["input"]["image_urls"] == [REF_URL]
    assert payload["input"]["prompt"] == PROMPT
    flow.debit.assert_awaited_once()
    flow.refund.assert_not_awaited()
    flow.record.assert_awaited_once()
    assert flow.record.await_args.kwargs["request_data"]["v_type"] == "imgtxt"
    assert flow.record.await_args.kwargs["request_data"]["v_image_url"] == REF_URL


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("old_type", ("text", None, "video"))
async def test_stale_grok_state_accepts_photo_without_restarting_flow(flow, model, old_type):
    await flow.state.set_data({
        "generation_type": "video", "v_model": model, "v_type": old_type,
        "v_duration": 6 if model == "grok_imagine" else 8,
        "v_ratio": "9:16", "video_flow_step": "configure", "user_prompt": PROMPT,
    })
    await flow.state.set_state(GenerationStates.waiting_for_video_prompt)
    await flow.dispatch(photo_message(flow))
    data = await flow.state.get_data()
    assert data["v_type"] == "imgtxt"
    assert data.get("v_image_url") == REF_URL
    assert data["user_prompt"] == PROMPT
    flow.debit.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("entry", ("text_handler", "direct_launch"))
async def test_missing_photo_is_rejected_before_billing_and_keeps_prompt(flow, model, entry):
    await flow.state.set_data({
        "generation_type": "video", "v_model": model, "v_type": "text",
        "v_duration": 6 if model == "grok_imagine" else 8, "v_ratio": "9:16",
        "video_flow_step": "configure", "grok_mode": "normal",
    })
    await flow.state.set_state(GenerationStates.waiting_for_video_prompt)
    if entry == "text_handler":
        await flow.dispatch(flow.message(text=PROMPT))
    else:
        await generation_module.run_no_preset_video_from_message(flow.message(text=PROMPT), flow.state, PROMPT)
    flow.debit.assert_not_awaited()
    flow.refund.assert_not_awaited()
    flow.post.assert_not_awaited()
    data = await flow.state.get_data()
    assert data["v_model"] == model
    assert data["v_type"] == "imgtxt"
    assert data["user_prompt"] == PROMPT
    assert await flow.state.get_state() == GenerationStates.waiting_for_video_prompt.state
    assert "\u0441\u0442\u0430\u0440\u0442\u043e\u0432\u043e\u0435 \u0444\u043e\u0442\u043e" in " ".join(str(getattr(call, "text", "")) for call in flow.session.calls)


async def test_non_grok_text_mode_does_not_silently_change_on_photo(flow):
    await flow.state.set_data({"generation_type": "video", "v_model": "v3_pro", "v_type": "text"})
    await flow.state.set_state(GenerationStates.waiting_for_video_prompt)
    await flow.dispatch(photo_message(flow))
    assert (await flow.state.get_data())["v_type"] == "text"
    flow.persist.assert_not_awaited()
    flow.debit.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
async def test_missing_image_can_be_added_and_prompt_retried_in_same_flow(flow, model):
    await flow.dispatch(flow.callback(f"advanced_v_model_{model}"))
    await flow.dispatch(flow.message(text=PROMPT))
    flow.debit.assert_not_awaited()
    assert (await flow.state.get_data())["user_prompt"] == PROMPT
    await flow.dispatch(photo_message(flow))
    await flow.dispatch(flow.message(text=PROMPT))
    flow.post.assert_awaited_once()
    assert flow.post.await_args.args[1]["input"]["image_urls"] == [REF_URL]
    flow.debit.assert_awaited_once()
    flow.refund.assert_not_awaited()


@pytest.mark.parametrize("model", MODELS)
async def test_invalid_photo_does_not_persist_or_charge(flow, model, monkeypatch):
    await flow.dispatch(flow.callback(f"advanced_v_model_{model}"))
    monkeypatch.setattr(flow.bot, "download_file", AsyncMock(return_value=io.BytesIO(b"not an image")))
    await flow.dispatch(photo_message(flow))
    flow.persist.assert_not_awaited()
    flow.debit.assert_not_awaited()
    assert not (await flow.state.get_data()).get("v_image_url")
    assert (await flow.state.get_data())["v_model"] == model


@pytest.mark.parametrize("model", MODELS)
async def test_missing_image_on_media_step_keeps_prompt_without_charge(flow, model):
    await flow.state.set_data({
        "generation_type": "video", "v_model": model, "v_type": "imgtxt",
        "video_flow_step": "media",
    })
    await flow.state.set_state(GenerationStates.waiting_for_video_prompt)
    await flow.dispatch(flow.message(text=PROMPT))
    flow.debit.assert_not_awaited()
    flow.post.assert_not_awaited()
    assert (await flow.state.get_data())["user_prompt"] == PROMPT
