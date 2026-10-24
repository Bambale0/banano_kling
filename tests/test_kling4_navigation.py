from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import kling4
from bot.handlers import video_generation_compat as catalog

_BOT_IDS = count(1000)


def buttons(message):
    markup = message.answer.call_args.kwargs["reply_markup"]
    return {
        button.callback_data: button.text
        for row in markup.inline_keyboard
        for button in row
    }


@pytest.fixture(autouse=True)
def lifecycle_boundary(monkeypatch):
    engine = SimpleNamespace(
        quote=AsyncMock(
            return_value={
                "quote_hash": "checked",
                "provider_credits": "1",
                "billed_seconds": "5",
                "cost": 5.0,
                "charge_cost": 0.0,
                "profile": "admin",
                "credit_name": "бананов",
                "credit_emoji": "🍌",
            }
        ),
        launch=AsyncMock(return_value={"task_id": "test", "status": "pending"}),
    )
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=object()))
    monkeypatch.setattr(kling4, "kling4_lifecycle", engine)
    return engine


@pytest.fixture
def telegram():
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=next(_BOT_IDS), chat_id=999999999, user_id=999999999),
    )
    message = SimpleNamespace(answer=AsyncMock(), edit_text=AsyncMock())
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=999999999), message=message, answer=AsyncMock()
    )
    return state, message, query


@pytest.mark.asyncio
async def test_kling4_is_inside_kling_catalog_and_hidden_in_other_families(telegram):
    state, message, query = telegram
    for family in ("seedance", "wan", "kling"):
        query.data = f"video_models:{family}:0"
        await catalog.show_video_models_page(query, state)
        markup = message.edit_text.call_args.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert ("k4:open" in callbacks) == (family == "kling")
        if family == "kling":
            assert markup.inline_keyboard[0][0].callback_data != "k4:open"
    query.from_user.id = 123123
    await catalog.show_video_models_page(query, state)
    markup = message.edit_text.call_args.kwargs["reply_markup"]
    assert all(
        b.callback_data != "k4:open" for row in markup.inline_keyboard for b in row
    )


@pytest.mark.asyncio
async def test_editor_groups_optional_materials_and_has_catalog_exits(telegram):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    actions = buttons(message)
    assert {
        "k4:duration:-1",
        "k4:duration:1",
        "k4:ratio:9:16",
        "video_models:kling:0",
    } <= actions.keys()
    assert "k4:new:voice" not in actions
    assert "reference" not in message.answer.call_args.args[0]
    query.data = "k4:materials"
    await kling4.callback(query, state)
    assert {
        "k4:new:image",
        "k4:new:video",
        "k4:new:voice",
        "k4:done",
    } <= buttons(message).keys()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "k4:text:prompt",
        "k4:text:duration",
        "k4:media:image_urls",
        "k4:media:video_urls",
    ],
)
async def test_input_can_be_cancelled_and_catalog_exit_releases_fsm(telegram, action):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    original = (await state.get_data())["k4_recipe"]
    query.data = action
    await kling4.callback(query, state)
    assert (
        "video_models:kling:0" if action == "k4:text:prompt" else "k4:done"
    ) in buttons(message)
    assert "back_main" not in buttons(message)
    query.data = "k4:done"
    await kling4.callback(query, state)
    assert await state.get_state() == kling4.Kling4States.editing.state
    assert (await state.get_data())["k4_recipe"] == original
    query.data = action
    await kling4.callback(query, state)
    query.data = "video_models:kling:0"
    await catalog.show_video_models_page(query, state)
    assert await state.get_state() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "k4:history",
        "k4:task:test",
        "k4:launch",
        "k4:quote",
        "k4:adopt:test",
        "k4:invalid",
    ],
)
async def test_task_quote_history_recovery_and_error_screens_have_navigation(
    telegram, monkeypatch, action
):
    state, message, query = telegram
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=object()))
    engine = SimpleNamespace(
        history=AsyncMock(return_value=[]),
        status=AsyncMock(
            return_value={
                "task_id": "test",
                "status": "unknown",
                "actual_credits": None,
                "result_url": None,
            }
        ),
        launch=AsyncMock(return_value={"task_id": "test", "status": "queued"}),
        quote=AsyncMock(return_value={"provider_credits": 1, "billed_seconds": 5}),
    )
    monkeypatch.setattr(kling4, "kling4_lifecycle", engine)
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.data = action
    await kling4.callback(query, state)
    assert "back_main" not in buttons(message)
    assert (
        "video_models:kling:0" if action in {"k4:quote", "k4:launch"} else "k4:done"
    ) in buttons(message)
    if action == "k4:task:test":
        assert "k4:history" in buttons(message)


@pytest.mark.asyncio
async def test_all_catalog_pages_preserve_models_and_admin_kling4(telegram):
    state, message, query = telegram
    seen = []
    for page in range(10):
        query.data = f"video_models:all:{page}"
        await catalog.show_video_models_page(query, state)
        markup = message.edit_text.call_args.kwargs["reply_markup"]
        seen.extend(
            b.callback_data
            for row in markup.inline_keyboard
            for b in row
            if b.callback_data == "k4:open"
            or b.callback_data.startswith(("advanced_v_model_", "v_model_"))
        )
        if not any(b.text == "Далее ›" for row in markup.inline_keyboard for b in row):
            break
    assert seen.count("k4:open") == 1
    assert len(seen) == len(set(seen))
    assert {
        "advanced_v_model_v3_std",
        "advanced_v_model_v3_pro",
        "v_model_seedance_2_5",
        "v_model_wan_3",
        "v_model_wan_3_prime",
    } <= set(seen)


@pytest.mark.asyncio
async def test_nested_material_fields_return_to_material_and_keep_draft(telegram):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    for kind, parent, field in [
        ("image", "element", "elements.0.image_urls"),
        ("voice", "voice", "voices.0.audio_url"),
    ]:
        query.data = f"k4:new:{kind}"
        await kling4.callback(query, state)
        query.data = f"k4:{parent}:0"
        await kling4.callback(query, state)
        assert "k4:materials" in buttons(message)
        query.data = f"k4:media:{field}"
        await kling4.callback(query, state)
        assert f"k4:{parent}:0" in buttons(message)
        query.data = f"k4:{parent}:0"
        await kling4.callback(query, state)
        assert await state.get_state() == kling4.Kling4States.editing.state
    query.data = "k4:mode"
    await kling4.callback(query, state)
    for field in ("first_frame_url", "keyframe_urls", "last_frame_url"):
        query.data = f"k4:media:{field}"
        await kling4.callback(query, state)
        assert "k4:done" in buttons(message)
        assert "back_main" not in buttons(message)
    query.data = "k4:mode"
    await kling4.callback(query, state)
    recipe = (await state.get_data())["k4_recipe"]
    assert len(recipe["input"]["elements"]) == len(recipe["input"]["voices"]) == 1


@pytest.mark.asyncio
async def test_leaving_catalog_cancels_pending_upload(telegram, monkeypatch):
    import asyncio

    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.data = "k4:media:image_urls"
    await kling4.callback(query, state)
    started, release = asyncio.Event(), asyncio.Event()

    async def upload(**kwargs):
        started.set()
        await release.wait()
        return {"url": "https://owned/late.png"}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    upload_message = SimpleNamespace(
        from_user=query.from_user,
        answer=AsyncMock(),
        text=None,
        voice=None,
        document=SimpleNamespace(file_id="test", file_name="test.png", file_size=100),
        bot=object(),
    )
    pending = asyncio.create_task(kling4.media(upload_message, state))
    await started.wait()
    query.data = "video_models:kling:0"
    await catalog.show_video_models_page(query, state)
    release.set()
    await pending
    assert not (await state.get_data())["k4_recipe"]["input"].get("image_urls")
    assert await state.get_state() is None


@pytest.mark.asyncio
async def test_forged_kling4_callback_from_nonadmin_does_not_change_state(telegram):
    state, _message, query = telegram
    await state.update_data(sentinel="preserved")
    query.from_user.id = 123123
    for action in ("open", "materials", "new:voice", "history", "launch"):
        query.data = f"k4:{action}"
        await kling4.callback(query, state)
    assert await state.get_data() == {"sentinel": "preserved"}
    assert await state.get_state() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("next_action", ["k4:done", "k4:text:duration"])
@pytest.mark.parametrize("legacy_session", [False, True])
async def test_queued_text_cannot_mutate_cancelled_or_replaced_input(
    telegram, next_action, legacy_session
):
    import asyncio

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.data = "k4:text:prompt"
    await kling4.callback(query, state)
    # Input state persisted by an older deployment before automatic intake.
    await state.set_state(kling4.Kling4States.text)
    await state.update_data(k4_field="prompt", k4_text_session="old-screen")
    if legacy_session:
        data = await state.get_data()
        data.pop("k4_text_session")
        await state.set_data(data)
    incoming = SimpleNamespace(from_user=query.from_user, text="10", answer=AsyncMock())
    lock = kling4.actor_lock(query, state)
    async with lock:
        query.data = next_action
        navigate = asyncio.create_task(kling4.callback(query, state))
        await asyncio.sleep(0)
        late = asyncio.create_task(kling4.text(incoming, state))
        await asyncio.sleep(0)
    await navigate
    await late
    recipe = (await state.get_data())["k4_recipe"]
    assert recipe["input"]["prompt"] == ""
    assert recipe["input"]["duration"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [("prompt", "A quiet landscape", "A quiet landscape"), ("duration", "10", 10)],
)
async def test_active_text_session_saves_value_and_returns_to_editor(
    telegram, field, value, expected
):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.data = f"k4:text:{field}"
    await kling4.callback(query, state)
    message.from_user = query.from_user
    message.text = value
    await (
        kling4.automatic(message, state)
        if field == "prompt"
        else kling4.text(message, state)
    )
    assert (await state.get_data())["k4_recipe"]["input"][field] == expected
    assert await state.get_state() == kling4.Kling4States.editing.state
    assert "back_main" not in buttons(message)


@pytest.mark.asyncio
async def test_text_input_started_before_session_tokens_still_saves(telegram):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.data = "k4:text:prompt"
    await kling4.callback(query, state)
    await state.set_state(kling4.Kling4States.text)
    await state.update_data(k4_field="prompt", k4_text_session="old-screen")
    data = await state.get_data()
    data.pop("k4_text_session")
    await state.set_data(data)
    message.from_user, message.text = query.from_user, "Prompt from an existing screen"
    await kling4.text(message, state)
    assert (await state.get_data())["k4_recipe"]["input"]["prompt"] == message.text
