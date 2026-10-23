"""The Telegram composer accepts references and launches on prompt messages."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import kling4
from bot.handlers import kling4_automatic as auto
from bot.services.prompt_fragment_coalescer import PromptFragmentCoalescingMiddleware
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from tests import test_kling4 as lifecycle_tests
from tests import test_kling4_navigation as navigation_tests

engine_context = lifecycle_tests.engine_context
telegram = navigation_tests.telegram
buttons = navigation_tests.buttons


async def test_open_keeps_direct_controls_and_automatic_prompt_launch(telegram):
    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    actions = buttons(message)
    assert "back_main" not in actions
    assert not {"k4:text:prompt", "k4:quote", "k4:launch"} & actions.keys()
    assert {
        "k4:duration:-1",
        "k4:duration:1",
        "k4:ratio:auto",
        "k4:ratio:16:9",
        "k4:ratio:9:16",
    } <= actions.keys()
    query.data = "k4:duration:1"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["duration"] == 6
    query.data = "k4:ratio:9:16"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["aspect_ratio"] == "9:16"


class Incoming(SimpleNamespace):
    def model_copy(self, *, update):
        return Incoming(**{**vars(self), **update})


def incoming(query, message_id, text=None, **media):
    return Incoming(
        from_user=query.from_user,
        chat=SimpleNamespace(id=999999999),
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        video=None,
        audio=None,
        voice=None,
        document=None,
        bot=object(),
        answer=AsyncMock(),
    ).model_copy(update=media)


@pytest.fixture
def engine(monkeypatch):
    engine = SimpleNamespace(
        quote=AsyncMock(
            return_value={
                "quote_hash": "frozen-quote",
                "provider_credits": "142.5",
                "billed_seconds": "5",
            }
        ),
        launch=AsyncMock(return_value={"task_id": "kling4_auto", "status": "pending"}),
    )
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=object()))
    monkeypatch.setattr(kling4, "kling4_lifecycle", engine)
    monkeypatch.setattr(kling4, "automatic_composer", auto.AutomaticComposer())
    monkeypatch.setattr(
        auto,
        "PromptFragmentCoalescingMiddleware",
        lambda **kwargs: PromptFragmentCoalescingMiddleware(
            quiet_seconds=0.01, long_quiet_seconds=0.02, **kwargs
        ),
    )
    monkeypatch.setattr(auto, "PROMPT_FRAGMENT_LONG_QUIET_SECONDS", 0.02)
    return engine


async def test_plain_prompt_launches_without_any_prompt_or_confirm_callback(
    telegram,
    engine,
):
    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    prompt = incoming(query, 10, "A quiet landscape")
    await kling4.automatic(prompt, state)
    await asyncio.sleep(0.06)
    engine.quote.assert_awaited_once()
    engine.launch.assert_awaited_once()
    recipe = engine.launch.await_args.args[1]
    assert recipe["input"]["prompt"] == "A quiet landscape"
    assert recipe["input"]["duration"] == 5
    assert engine.launch.await_args.args[2] == "frozen-quote"
    await kling4.automatic(prompt, state)
    await asyncio.sleep(0.06)
    engine.launch.assert_awaited_once()


async def settled():
    await asyncio.sleep(0.08)


def file(name, *, mime=None):
    return SimpleNamespace(
        file_id=name, file_unique_id=name, file_name=name, file_size=100, mime_type=mime
    )


@pytest.mark.parametrize(
    "field,name,kind",
    [
        ("photo", "photo.jpg", "image"),
        ("document", "photo.png", "image"),
        ("video", "clip.mp4", "video"),
        ("document", "clip.mp4", "video"),
        ("voice", "voice.ogg", "audio"),
        ("audio", "speech.wav", "audio"),
        ("document", "speech.mp3", "audio"),
    ],
)
async def test_reference_type_detected_without_selecting_a_field(
    telegram, engine, monkeypatch, field, name, kind
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    stored = AsyncMock(return_value={"url": "https://owned.test/" + name})
    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", stored)
    media = file(name)
    msg = incoming(query, 10, **{field: [media] if field == "photo" else media})
    await kling4.automatic(msg, state)
    assert stored.await_args.kwargs["kind"] == kind
    data = (await state.get_data())["k4_recipe"]["input"]
    if kind == "audio":
        assert data["voices"] == [
            {"name": "Voice1", "audio_url": "https://owned.test/" + name}
        ]
    else:
        assert data[kind + "_urls"] == ["https://owned.test/" + name]
    engine.launch.assert_not_awaited()


async def test_caption_waits_for_entire_album_and_preserves_telegram_order(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    started, release = asyncio.Event(), asyncio.Event()

    async def upload(**kwargs):
        if kwargs["file_id"] == "first.png":
            started.set()
            await release.wait()
        return {"url": "https://owned.test/" + kwargs["file_id"]}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    first = incoming(
        query,
        10,
        photo=[file("first.png")],
        caption="Use both photos",
        media_group_id="album",
    )
    second = incoming(query, 11, photo=[file("second.png")], media_group_id="album")
    pending = asyncio.create_task(kling4.automatic(first, state))
    await started.wait()
    await kling4.automatic(second, state)
    await settled()
    engine.launch.assert_not_awaited()
    release.set()
    await pending
    await settled()
    engine.launch.assert_awaited_once()
    recipe = engine.launch.await_args.args[1]
    assert recipe["input"]["image_urls"] == [
        "https://owned.test/first.png",
        "https://owned.test/second.png",
    ]
    assert recipe["input"]["prompt"] == "Use both photos"


async def test_failed_reference_blocks_prompt_until_successful_resend(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    upload = AsyncMock(side_effect=Wan3PrimeValidationError("Invalid image"))
    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    await kling4.automatic(incoming(query, 10, document=file("face.png")), state)
    await kling4.automatic(incoming(query, 11, "Animate my photo"), state)
    await settled()
    engine.launch.assert_not_awaited()
    upload.side_effect = None
    upload.return_value = {"url": "https://owned.test/face.png"}
    await kling4.automatic(incoming(query, 12, document=file("face.png")), state)
    await kling4.automatic(incoming(query, 13, "Animate my photo"), state)
    await settled()
    engine.launch.assert_awaited_once()
    assert engine.launch.await_args.args[1]["input"]["image_urls"] == [
        "https://owned.test/face.png"
    ]


@pytest.mark.parametrize(
    "exit_action", ["k4:clear", "video_models:kling:0", "k4:repeat:saved"]
)
async def test_replacing_or_leaving_draft_cancels_pending_caption_and_upload(
    telegram, engine, monkeypatch, exit_action
):
    from bot import wan3_prime_api
    from bot.handlers import video_generation_compat as catalog

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    saved = kling4.fresh()
    saved["input"].update(
        prompt="Saved recipe", duration=12, image_urls=["https://owned.test/saved.png"]
    )
    engine.owner_recipe = AsyncMock(return_value=saved)
    started, release = asyncio.Event(), asyncio.Event()

    async def upload(**_kwargs):
        started.set()
        await release.wait()
        return {"url": "https://owned.test/stale.png"}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    pending = asyncio.create_task(
        kling4.automatic(
            incoming(query, 10, document=file("old.png"), caption="Old prompt"), state
        )
    )
    await started.wait()
    query.data = exit_action
    await (
        catalog.show_video_models_page(query, state)
        if exit_action.startswith("video_models:")
        else kling4.callback(query, state)
    )
    release.set()
    await pending
    await settled()
    engine.launch.assert_not_awaited()
    data = (await state.get_data())["k4_recipe"]["input"]
    if exit_action == "k4:repeat:saved":
        assert data == saved["input"]
        assert not (await state.get_data()).get("k4_upload_errors")
        await kling4.automatic(
            incoming(query, 11, "New prompt for saved recipe"), state
        )
        await settled()
        engine.launch.assert_awaited_once()
        data = engine.launch.await_args.args[1]["input"]
        assert data["image_urls"] == ["https://owned.test/saved.png"]
        assert data["duration"] == 12
    else:
        assert not data.get("image_urls")


async def test_prompt_fragments_launch_once_and_filename_in_prompt_is_not_a_reference(
    telegram, engine
):
    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    await kling4.automatic(
        incoming(query, 10, "Show a file named landscape.png"), state
    )
    await kling4.automatic(incoming(query, 11, "With a slow camera pan"), state)
    await settled()
    engine.launch.assert_awaited_once()
    assert (
        engine.launch.await_args.args[1]["input"]["prompt"]
        == "Show a file named landscape.png\nWith a slow camera pan"
    )


async def test_actual_telegram_router_receives_prompt_in_editing_state(
    telegram, engine, monkeypatch
):
    from datetime import UTC, datetime

    from aiogram import Bot, types

    from bot.handlers import generation_router

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    monkeypatch.setattr(types.Message, "answer", AsyncMock())
    bot = Bot("123456:TEST_TOKEN_FOR_ROUTING_ONLY")
    try:
        msg = types.Message(
            message_id=30,
            date=datetime.now(UTC),
            chat=types.Chat(id=999999999, type="private"),
            from_user=types.User(id=999999999, is_bot=False, first_name="Test"),
            text="A landscape",
        ).as_(bot)
        await generation_router.propagate_event(
            update_type="message",
            event=msg,
            bot=bot,
            state=state,
            raw_state=await state.get_state(),
        )
        await settled()
        engine.launch.assert_awaited_once()
    finally:
        await bot.session.close()


async def test_real_lifecycle_keeps_unknown_submission_idempotent(
    telegram, engine, engine_context, monkeypatch
):
    from bot import database

    lifecycle, actor, transport = engine_context
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(kling4, "kling4_lifecycle", lifecycle)

    async def uncertain(*_args):
        transport.calls += 1
        raise TimeoutError("No acknowledgement")

    monkeypatch.setattr(transport, "create", uncertain)
    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    prompt = incoming(query, 10, "A quiet landscape")
    before = (await database.get_or_create_user(actor.telegram_id)).credits
    await kling4.automatic(prompt, state)
    await settled()
    assert transport.calls == 1
    history = await lifecycle.history(actor)
    assert len(history) == 1 and history[0]["status"] == "unknown"
    assert "проверяю статус" in prompt.answer.await_args.args[0]
    await kling4.automatic(prompt, state)
    await settled()
    query.data = "k4:launch"
    await kling4.callback(query, state)
    assert transport.calls == 1
    assert (await database.get_or_create_user(actor.telegram_id)).credits == before


async def test_unsupported_album_file_blocks_caption_instead_of_silent_omission(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(return_value={"url": "https://owned.test/face.png"}),
    )
    await kling4.automatic(
        incoming(
            query, 10, photo=[file("face.png")], caption="Animate", media_group_id="a"
        ),
        state,
    )
    await kling4.automatic(
        incoming(query, 11, document=file("notes.pdf"), media_group_id="a"), state
    )
    await settled()
    engine.launch.assert_not_awaited()
    assert (await state.get_data())["k4_upload_errors"]


async def test_settings_are_bounded_and_next_prompt_uses_them(telegram, engine):
    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    for value, action, expected in ((3, "-1", 3), (30, "1", 30)):
        recipe = kling4.fresh()
        recipe["input"]["duration"] = value
        await kling4.save(state, recipe)
        query.data = f"k4:duration:{action}"
        await kling4.callback(query, state)
        assert (await state.get_data())["k4_recipe"]["input"]["duration"] == expected
    query.data = "k4:ratio:9:16"
    await kling4.callback(query, state)
    engine.launch.assert_not_awaited()
    await kling4.automatic(incoming(query, 10, "Vertical scene"), state)
    await settled()
    data = engine.launch.await_args.args[1]["input"]
    assert data["duration"] == 30 and data["aspect_ratio"] == "9:16"


async def test_frame_tags_select_frames_automatically_and_keep_order_on_more_uploads(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(
            side_effect=lambda **kwargs: {
                "url": "https://owned.test/" + kwargs["file_id"]
            }
        ),
    )
    for mid, name in ((10, "first.png"), (11, "last.png")):
        await kling4.automatic(incoming(query, mid, document=file(name)), state)
    await kling4.automatic(
        incoming(query, 12, "Move from @first_frame to @last_frame"), state
    )
    await settled()
    data = engine.launch.await_args.args[1]
    assert data["mode"] == "keyframe"
    assert data["input"]["first_frame_url"].endswith("/first.png")
    assert data["input"]["last_frame_url"].endswith("/last.png")
    # File completion order cannot reorder the next draft.
    for mid, name in ((15, "new-last.png"), (14, "middle.png")):
        await kling4.automatic(incoming(query, mid, document=file(name)), state)
    await kling4.automatic(
        incoming(query, 16, "Move from @first_frame to @last_frame"), state
    )
    await settled()
    data = engine.launch.await_args.args[1]["input"]
    assert data["last_frame_url"].endswith("/new-last.png")
    assert [u.rsplit("/", 1)[-1] for u in data["keyframe_urls"]] == [
        "last.png",
        "middle.png",
    ]


async def test_nonadmin_message_cannot_upload_or_launch(telegram, engine, monkeypatch):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    query.from_user.id = 123123
    upload = AsyncMock()
    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    await kling4.automatic(
        incoming(query, 10, document=file("face.png"), caption="Animate"), state
    )
    await settled()
    engine.launch.assert_not_awaited()
    upload.assert_not_awaited()


async def test_out_of_order_first_delivery_keeps_every_prompt_fragment(
    telegram, engine
):
    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    await kling4.automatic(incoming(query, 11, "Then move the camera"), state)
    await kling4.automatic(incoming(query, 10, "Start from the photo"), state)
    await settled()
    engine.launch.assert_awaited_once()
    assert (
        engine.launch.await_args.args[1]["input"]["prompt"]
        == "Start from the photo\nThen move the camera"
    )


@pytest.mark.parametrize("old_action", ["k4:text:prompt", "k4:quote", "k4:launch"])
async def test_old_controls_cannot_bypass_pending_or_failed_references(
    telegram, engine, monkeypatch, old_action
):
    from bot import wan3_prime_api

    state, _message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    started, release = asyncio.Event(), asyncio.Event()

    async def upload(**_kwargs):
        started.set()
        await release.wait()
        return {"url": "https://owned.test/face.png"}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    pending = asyncio.create_task(
        kling4.automatic(incoming(query, 10, document=file("face.png")), state)
    )
    await started.wait()
    query.data = old_action
    await kling4.callback(query, state)
    engine.launch.assert_not_awaited()
    engine.quote.assert_not_awaited()
    await kling4.automatic(incoming(query, 11, "Animate the photo"), state)
    await settled()
    engine.launch.assert_not_awaited()
    release.set()
    await pending
    await settled()
    engine.launch.assert_awaited_once()
    assert engine.launch.await_args.args[1]["input"]["image_urls"] == [
        "https://owned.test/face.png"
    ]
    await state.update_data(k4_upload_errors={"failed": True})
    await kling4.callback(query, state)
    await kling4.automatic(incoming(query, 12, "Another prompt"), state)
    await settled()
    engine.launch.assert_awaited_once()
