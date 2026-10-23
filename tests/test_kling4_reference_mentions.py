"""KIE reference aliases bind to declared assets without changing their roles."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from bot.services.kling4_contract import DEFAULT_SETTINGS, Kling4Error, validate_recipe
from tests import test_kling4 as contract_tests
from tests import test_kling4_navigation as navigation_tests

engine_context = contract_tests.engine_context
telegram = navigation_tests.telegram


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("@Image1 meets @Image2.", "@image_1 meets @image_2."),
        ("@IMAGE_1 meets @image2.", "@image_1 meets @image_2."),
        ("Move @Image2 through @Video1.", "Move @image_2 through @video_1."),
        ("@image_1 meets @image_2.", "@image_1 meets @image_2."),
        ("Image1 is written on @image_1.", "Image1 is written on @image_1."),
    ],
)
async def test_copied_mentions_use_kie_syntax_and_keep_request_unchanged(
    prompt, expected
):
    request = {
        "mode": "reference",
        "input": {
            "prompt": prompt,
            "image_urls": ["https://owned/first.png", "https://owned/second.png"],
            "video_urls": ["https://owned/scene.mp4"],
        },
    }
    original = deepcopy(request)
    prepared = await validate_recipe(request, contract_tests.Probe())
    assert prepared.input["prompt"] == expected
    assert prepared.input["image_urls"] == original["input"]["image_urls"]
    assert request == original
    canonical = deepcopy(request)
    canonical["input"]["prompt"] = expected
    other = await validate_recipe(canonical, contract_tests.Probe())
    assert prepared.quote(DEFAULT_SETTINGS, 1) == other.quote(DEFAULT_SETTINGS, 1)


async def test_exact_named_element_has_precedence_over_builtin_alias():
    prepared = await validate_recipe(
        {
            "mode": "reference",
            "input": {
                "prompt": "@Image1 stands beside @Image2.",
                "image_urls": ["https://owned/first.png", "https://owned/second.png"],
                "elements": [
                    {
                        "name": "Image1",
                        "image_urls": [
                            "https://owned/front.png",
                            "https://owned/side.png",
                        ],
                    }
                ],
            },
        },
        contract_tests.Probe(),
    )
    assert prepared.input["prompt"] == "@Image1 stands beside @image_2."


@pytest.mark.parametrize("mention", ["@IMAGE1", "@image1"])
async def test_alias_cannot_steal_case_variant_of_a_declared_name(mention):
    with pytest.raises(Kling4Error, match="не соответствует"):
        await validate_recipe(
            {
                "mode": "reference",
                "input": {
                    "prompt": mention,
                    "image_urls": ["https://owned/ordinary.png"],
                    "elements": [
                        {
                            "name": "Image1",
                            "image_urls": [
                                "https://owned/front.png",
                                "https://owned/side.png",
                            ],
                        }
                    ],
                },
            },
            contract_tests.Probe(),
        )


@pytest.mark.parametrize("token", ["@Image3", "@Image0", "@Image1_extra", "@unknown"])
async def test_missing_or_ambiguous_references_still_fail(token):
    with pytest.raises(Kling4Error, match="не соответствует"):
        await validate_recipe(
            {
                "mode": "reference",
                "input": {"prompt": token, "image_urls": ["https://owned/first.png"]},
            },
            contract_tests.Probe(),
        )


async def test_aliases_do_not_change_keyframe_meaning():
    with pytest.raises(Kling4Error, match="не соответствует"):
        await validate_recipe(
            {
                "mode": "keyframe",
                "input": {
                    "prompt": "@Image1",
                    "first_frame_url": "https://owned/first.png",
                },
            },
            contract_tests.Probe(),
        )


async def test_normalized_prompt_cannot_exceed_provider_limit():
    with pytest.raises(Kling4Error, match="8000"):
        await validate_recipe(
            {
                "mode": "reference",
                "input": {
                    "prompt": "x" * 7993 + "@Image1",
                    "image_urls": ["https://owned/first.png"],
                },
            },
            contract_tests.Probe(),
        )


async def test_telegram_shows_actual_reference_bindings_without_extra_buttons(telegram):
    from bot.handlers import kling4

    state, message, query = telegram
    query.data = "k4:open"
    await kling4.callback(query, state)
    recipe = kling4.fresh()
    recipe["input"].update(
        image_urls=["https://owned/first.png", "https://owned/second.png"],
        video_urls=["https://owned/scene.mp4"],
        voices=[{"name": "Voice1", "audio_url": "https://owned/speech.wav"}],
    )
    await kling4.save(state, recipe)
    await kling4.show(message, state)
    text = message.answer.await_args.args[0]
    assert "@image_1" in text and "@image_2" in text
    assert text.index("@image_1") < text.index("@image_2")
    assert "@video_1" in text and "@Voice1" in text
    assert "k4:quote" not in navigation_tests.buttons(message)
    assert "back_main" not in navigation_tests.buttons(message)


@pytest.fixture
async def owned_context(engine_context, tmp_path, monkeypatch):
    from PIL import Image

    from bot.config import config
    from bot.services.wan3_prime_storage import ActualWan3PrimeProbe, wan3_prime_storage

    engine, actor, transport = engine_context
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://owned.example.test")
    engine.probe = ActualWan3PrimeProbe(wan3_prime_storage)
    urls = []
    for color in ("red", "blue"):
        path = tmp_path / (color + ".png")
        Image.new("RGB", (400, 400), color).save(path)
        stored = await wan3_prime_storage.save_owned_file(
            actor, kind="image", filename=path.name, path=path, content_type="image/png"
        )
        urls.append(stored["url"])
    return engine, actor, transport, urls


async def test_miniapp_owned_images_bind_in_provider_payload_once(
    owned_context, monkeypatch
):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import database, kling4_api
    from tests.test_wan3_http_flow import signed_user

    engine, actor, transport, urls = owned_context
    create = AsyncMock(
        return_value=(200, {"code": 200, "data": {"taskId": "kie-alias-task"}})
    )
    monkeypatch.setattr(transport, "create", create)
    before = (await database.get_or_create_user(actor.telegram_id)).credits
    app = web.Application()
    app["kling4_lifecycle"] = engine
    kling4_api.setup_kling4_routes(app, "/mini-app")
    request = {
        "mode": "reference",
        "input": {
            "prompt": "@Image1 is the woman. @Image2 is the man.",
            "image_urls": urls,
        },
    }
    auth = {"init_data": signed_user(actor.telegram_id)}
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(
            "/mini-app/api/kling4/quote", json={**auth, "recipe": request}
        )
        assert quote.status == 200, await quote.text()
        frozen = await quote.json()
        body = {
            **auth,
            "recipe": request,
            "quote_hash": frozen["quote_hash"],
            "idempotency_key": "alias-owned-images",
        }
        for _ in range(2):
            result = await client.post("/mini-app/api/kling4/generate", json=body)
            assert result.status == 200, await result.text()
        create.assert_awaited_once()
        model, submitted = create.await_args.args
        assert model == "kling-4.0/reference-to-video"
        assert submitted["prompt"] == "@image_1 is the woman. @image_2 is the man."
        assert submitted["image_urls"] == urls
        invalid = deepcopy(body)
        invalid["recipe"]["input"]["prompt"] = "@Image3 is missing."
        invalid["idempotency_key"] = "missing-image-never-submitted"
        rejected = await client.post("/mini-app/api/kling4/generate", json=invalid)
        assert rejected.status == 400, await rejected.text()
        create.assert_awaited_once()
    assert (await database.get_or_create_user(actor.telegram_id)).credits == before


async def test_telegram_alias_prompt_reaches_provider_with_ordered_owned_images(
    owned_context, telegram, monkeypatch
):
    import asyncio

    from bot import database, wan3_prime_api
    from bot.handlers import kling4
    from bot.handlers import kling4_automatic as composer
    from bot.services.prompt_fragment_coalescer import (
        PromptFragmentCoalescingMiddleware,
    )
    from tests.test_kling4_automatic_telegram import file, incoming

    engine, actor, transport, urls = owned_context
    state, _message, query = telegram
    created = asyncio.Event()

    async def accepted(*_args):
        created.set()
        return 200, {"code": 200, "data": {"taskId": "kie-telegram-alias-task"}}

    create = AsyncMock(side_effect=accepted)
    monkeypatch.setattr(transport, "create", create)
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(kling4, "kling4_lifecycle", engine)
    monkeypatch.setattr(kling4, "automatic_composer", composer.AutomaticComposer())
    monkeypatch.setattr(
        composer,
        "PromptFragmentCoalescingMiddleware",
        lambda **kwargs: PromptFragmentCoalescingMiddleware(
            quiet_seconds=0.01, **kwargs
        ),
    )
    monkeypatch.setattr(
        wan3_prime_api,
        "store_telegram_wan3_prime_media",
        AsyncMock(side_effect=[{"url": url} for url in urls]),
    )
    query.data = "k4:open"
    await kling4.callback(query, state)
    for mid, name in ((10, "first.png"), (11, "second.png")):
        await kling4.automatic(incoming(query, mid, photo=[file(name)]), state)
    prompt = incoming(query, 12, "@Image1 is the woman. @Image2 is the man.")
    before = (await database.get_or_create_user(actor.telegram_id)).credits
    await kling4.automatic(prompt, state)
    await asyncio.wait_for(created.wait(), timeout=3)
    await kling4.automatic(prompt, state)
    create.assert_awaited_once()
    model, submitted = create.await_args.args
    assert model == "kling-4.0/reference-to-video"
    assert submitted["prompt"] == "@image_1 is the woman. @image_2 is the man."
    assert submitted["image_urls"] == urls
    assert len(await engine.history(actor)) == 1
    assert (await database.get_or_create_user(actor.telegram_id)).credits == before


async def test_telegram_binding_labels_accept_nullable_optional_arrays(telegram):
    from bot.handlers import kling4

    state, message, _query = telegram
    recipe = kling4.fresh()
    recipe["input"].update(image_urls=None, video_urls=None, elements=None, voices=None)
    await kling4.save(state, recipe)
    await kling4.show(message, state)
    assert "@image_" not in message.answer.await_args.args[0]
