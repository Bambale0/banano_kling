"""Native Kling4 options stay reachable without a manual launch step."""

import asyncio
from unittest.mock import AsyncMock

from tests import test_kling4_automatic_telegram as automatic_tests
from tests import test_kling4_navigation as navigation_tests
from tests import test_kling4_reference_mentions as reference_tests

telegram = navigation_tests.telegram
engine = automatic_tests.engine
buttons = navigation_tests.buttons
engine_context = reference_tests.engine_context
owned_context = reference_tests.owned_context


async def test_native_controls_select_mode_quality_and_ratio_without_launch(
    telegram, engine
):
    from bot.handlers import kling4

    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    actions = buttons(message)
    assert actions["k4:mode:reference"].startswith("✅")
    assert actions["k4:resolution:720p"].startswith("✅")
    assert {"k4:materials", "k4:mode:keyframe", "k4:resolution:1080p"} <= actions.keys()
    assert {key for key in actions if key.startswith("k4:ratio:")} == {
        "k4:ratio:auto",
        "k4:ratio:16:9",
        "k4:ratio:9:16",
        "k4:ratio:1:1",
        "k4:ratio:21:9",
    }
    assert not {"back_main", "k4:quote", "k4:launch", "k4:text:prompt"} & actions.keys()
    for action in ("k4:resolution:1080p", "k4:ratio:21:9", "k4:duration:1"):
        query.data = action
        await kling4.callback(query, state)
    data = (await state.get_data())["k4_recipe"]["input"]
    assert (data["resolution"], data["aspect_ratio"], data["duration"]) == (
        "1080p",
        "21:9",
        6,
    )
    assert buttons(message)["k4:resolution:1080p"].startswith("✅")
    query.data = "k4:mode:keyframe"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["mode"] == "keyframe"
    assert buttons(message)["k4:mode:keyframe"].startswith("✅")
    query.data = "k4:mode:reference"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["mode"] == "reference"
    engine.launch.assert_not_awaited()


async def test_elements_can_be_created_uploaded_named_and_used_in_prompt(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api
    from bot.handlers import kling4

    state, message, query = telegram
    for action in ("k4:open", "k4:materials", "k4:new:image"):
        query.data = action
        await kling4.callback(query, state)
    assert "k4:media:elements.0.image_urls" in buttons(message)
    assert "2–4" in message.answer.await_args.args[0]
    query.data = "k4:media:elements.0.image_urls"
    await kling4.callback(query, state)
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(side_effect=lambda **kw: {"url": "https://owned/" + kw["file_id"]}),
    )
    for mid, filename in ((10, "front.png"), (11, "side.png")):
        upload = automatic_tests.incoming(
            query, mid, photo=[automatic_tests.file(filename)]
        )
        await kling4.media(upload, state)
    query.data = "k4:element:0"
    await kling4.callback(query, state)
    query.data = "k4:text:elements.0.name"
    await kling4.callback(query, state)
    renamed = automatic_tests.incoming(query, 12, "Woman")
    await kling4.text(renamed, state)
    assert "k4:media:elements.0.image_urls" in buttons(renamed)
    item = (await state.get_data())["k4_recipe"]["input"]["elements"][0]
    assert item["name"] == "Woman"
    assert item["image_urls"] == ["https://owned/front.png", "https://owned/side.png"]
    assert "tag" not in item  # Native primary-image type inference remains available.
    query.data = "k4:done"
    await kling4.callback(query, state)
    prompt = automatic_tests.incoming(query, 13, "@Woman looks at the camera.")
    await kling4.automatic(prompt, state)
    await asyncio.sleep(0.08)
    engine.launch.assert_awaited_once()
    assert engine.launch.await_args.args[1]["input"]["elements"] == [item]


async def test_element_album_keeps_primary_image_order_and_deduplicates_messages(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api
    from bot.handlers import kling4

    state, _message, query = telegram
    for action in ("k4:open", "k4:new:image", "k4:media:elements.0.image_urls"):
        query.data = action
        await kling4.callback(query, state)
    started, release = asyncio.Event(), asyncio.Event()

    async def upload(**kw):
        if kw["file_id"] == "front.png":
            started.set()
            await release.wait()
        return {"url": "https://owned/" + kw["file_id"]}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    front = automatic_tests.incoming(
        query, 10, photo=[automatic_tests.file("front.png")]
    )
    side = automatic_tests.incoming(query, 11, photo=[automatic_tests.file("side.png")])
    pending = asyncio.create_task(kling4.media(front, state))
    await started.wait()
    await kling4.media(side, state)
    release.set()
    await pending
    await kling4.media(side, state)
    element = (await state.get_data())["k4_recipe"]["input"]["elements"][0]
    assert element["image_urls"] == [
        "https://owned/front.png",
        "https://owned/side.png",
    ]
    query.data = "k4:up:elements.0.image_urls:1"
    await kling4.callback(query, state)
    await kling4.media(
        automatic_tests.incoming(query, 12, photo=[automatic_tests.file("third.png")]),
        state,
    )
    element = (await state.get_data())["k4_recipe"]["input"]["elements"][0]
    assert element["image_urls"] == [
        "https://owned/side.png",
        "https://owned/front.png",
        "https://owned/third.png",
    ]
    engine.launch.assert_not_awaited()


async def test_adding_element_after_deletion_does_not_reuse_existing_name(telegram):
    from bot.handlers import kling4

    state, _message, query = telegram
    for action in (
        "k4:open",
        "k4:new:image",
        "k4:new:image",
        "k4:remove:element:0",
        "k4:new:image",
    ):
        query.data = action
        await kling4.callback(query, state)
    names = [
        e["name"] for e in (await state.get_data())["k4_recipe"]["input"]["elements"]
    ]
    assert len(set(names)) == 2


async def test_owned_element_reaches_reference_provider_once_with_selected_quality(
    telegram, owned_context, monkeypatch
):
    from bot import database, wan3_prime_api
    from bot.handlers import kling4, kling4_automatic
    from bot.services.prompt_fragment_coalescer import (
        PromptFragmentCoalescingMiddleware,
    )

    lifecycle, actor, transport, urls = owned_context
    state, _message, query = telegram
    created = asyncio.Event()

    async def accept(*_args):
        created.set()
        return 200, {"code": 200, "data": {"taskId": "kie-full-elements"}}

    create = AsyncMock(side_effect=accept)
    monkeypatch.setattr(transport, "create", create)
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(kling4, "kling4_lifecycle", lifecycle)
    monkeypatch.setattr(
        kling4, "automatic_composer", kling4_automatic.AutomaticComposer()
    )
    monkeypatch.setattr(
        kling4_automatic,
        "PromptFragmentCoalescingMiddleware",
        lambda **kw: PromptFragmentCoalescingMiddleware(quiet_seconds=0.01, **kw),
    )
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(side_effect=[{"url": u} for u in urls]),
    )
    before = (await database.get_or_create_user(actor.telegram_id)).credits
    for action in (
        "k4:open",
        "k4:resolution:1080p",
        "k4:ratio:9:16",
        "k4:new:image",
        "k4:media:elements.0.image_urls",
    ):
        query.data = action
        await kling4.callback(query, state)
    for mid, name in ((10, "front.png"), (11, "side.png")):
        await kling4.media(
            automatic_tests.incoming(query, mid, photo=[automatic_tests.file(name)]),
            state,
        )
    query.data = "k4:done"
    await kling4.callback(query, state)
    prompt = automatic_tests.incoming(query, 12, "@Hero1 smiles at the camera.")
    await kling4.automatic(prompt, state)
    await asyncio.wait_for(created.wait(), 5)
    await asyncio.sleep(0.05)
    await kling4.automatic(prompt, state)
    await asyncio.sleep(0.05)
    create.assert_awaited_once()
    model, payload = create.await_args.args
    assert model == "kling-4.0/reference-to-video"
    assert payload["resolution"] == "1080p" and payload["aspect_ratio"] == "9:16"
    assert payload["elements"] == [{"name": "Hero1", "image_urls": urls}]
    assert len(await lifecycle.history(actor)) == 1
    assert (await database.get_or_create_user(actor.telegram_id)).credits == before


async def test_new_reference_switches_frame_draft_without_losing_frames(
    telegram, engine, monkeypatch
):
    from bot import wan3_prime_api
    from bot.handlers import kling4

    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    reference = (await state.get_data())["k4_recipe"]
    reference["input"]["elements"] = [
        {"name": "Saved", "image_urls": ["https://owned/a.png", "https://owned/b.png"]}
    ]
    await kling4.save(state, reference)
    query.data = "k4:mode:keyframe"
    await kling4.callback(query, state)
    assert {
        "k4:media:first_frame_url",
        "k4:media:keyframe_urls",
        "k4:media:last_frame_url",
    } <= buttons(message).keys()
    recipe = (await state.get_data())["k4_recipe"]
    recipe["input"].update(
        first_frame_url="https://owned/first.png",
        last_frame_url="https://owned/last.png",
    )
    await kling4.save(state, recipe)
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(return_value={"url": "https://owned/clip.mp4"}),
    )
    await kling4.automatic(
        automatic_tests.incoming(query, 10, video=automatic_tests.file("clip.mp4")),
        state,
    )
    recipe = (await state.get_data())["k4_recipe"]
    assert recipe["mode"] == "reference"
    assert recipe["input"]["image_urls"] == [
        "https://owned/first.png",
        "https://owned/last.png",
    ]
    assert recipe["input"]["video_urls"] == ["https://owned/clip.mp4"]
    assert recipe["input"]["elements"] == reference["input"]["elements"]
    query.data = "k4:sound"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["keep_original_sound"] is True
    assert "вкл" in buttons(message)["k4:sound"]
    query.data = "k4:mode:keyframe"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"][
        "first_frame_url"
    ] == "https://owned/first.png"
    query.data = "k4:mode:reference"
    await kling4.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["video_urls"] == [
        "https://owned/clip.mp4"
    ]
    engine.launch.assert_not_awaited()


async def test_native_sound_without_video_is_explained_without_unsupported_field(
    telegram,
):
    from bot.handlers import kling4

    state, _message, query = telegram
    for action in ("k4:open", "k4:sound"):
        query.data = action
        await kling4.callback(query, state)
    assert "keep_original_sound" not in (await state.get_data())["k4_recipe"]["input"]
    assert "автоматически" in query.answer.await_args.args[0]
