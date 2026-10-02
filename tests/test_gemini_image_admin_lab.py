import base64
import io

import pytest
from PIL import Image

from bot.services.openrouter_image_service import OpenRouterImageService


@pytest.fixture
async def image_server():
    from types import SimpleNamespace

    from aiohttp import web

    runners = []

    async def start(app):
        runner = web.AppRunner(app)
        await runner.setup()
        runners.append(runner)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        return SimpleNamespace(make_url=lambda path: f"http://127.0.0.1:{port}/{path}")

    yield start
    for runner in runners:
        await runner.cleanup()


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(out, format="PNG")
    return out.getvalue()


@pytest.mark.asyncio
async def test_image_contract_uses_live_capabilities_and_preserves_original(
    image_server,
):
    from aiohttp import web

    received = []

    async def endpoints(request):
        return web.json_response(
            {
                "endpoints": [
                    {
                        "provider_name": "Studio",
                        "provider_tag": "google-ai-studio/global",
                        "supported_parameters": {
                            "resolution": {"type": "enum", "values": ["1K", "4K"]},
                            "aspect_ratio": {"type": "enum", "values": ["16:9"]},
                            "input_references": {"type": "range", "min": 0, "max": 14},
                        },
                    }
                ]
            }
        )

    async def generate(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        received.append(await request.json())
        return web.json_response(
            {
                "id": "gen-test",
                "data": [
                    {
                        "b64_json": base64.b64encode(image_bytes()).decode(),
                        "media_type": "image/png",
                    }
                ],
                "usage": {"cost": 0.12},
            }
        )

    app = web.Application()
    app.router.add_get("/images/models/google/gemini-3-pro-image/endpoints", endpoints)
    app.router.add_post("/images", generate)
    server = await image_server(app)
    service = OpenRouterImageService(
        api_key="test-key", base_url=str(server.make_url("")).rstrip("/")
    )
    caps = await service.capabilities()
    result = await service.generate(
        prompt="Poster",
        references=["https://example.com/ref.png"],
        ratio="16:9",
        resolution="4K",
        provider="auto",
        timeout=120,
        capabilities=caps,
    )
    assert received == [
        {
            "model": "google/gemini-3-pro-image",
            "prompt": "Poster",
            "n": 1,
            "resolution": "4K",
            "aspect_ratio": "16:9",
            "input_references": [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/ref.png"},
                }
            ],
            "provider": {"only": ["google-ai-studio/global"]},
        }
    ]
    assert result.images[0].data == image_bytes()
    assert result.request_id == "gen-test"
    assert result.usage["cost"] == 0.12


@pytest.mark.asyncio
async def test_lab_rejects_non_admin_and_keeps_settings_after_reopening(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from bot.handlers import admin_gemini_image_lab as lab

    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=111, user_id=111))
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"), edit_text=AsyncMock(), answer=AsyncMock()
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=222),
        message=message,
        data="admin_gmi:open",
        answer=AsyncMock(),
    )
    monkeypatch.setattr(lab.config, "ADMIN_IDS_STR", "111")
    await lab.handle_callback(callback, state)
    callback.answer.assert_awaited_once_with("⛔ Нет доступа", show_alert=True)
    message.edit_text.assert_not_awaited()
    callback.from_user.id = 111
    monkeypatch.setattr(
        lab.openrouter_image_service,
        "capabilities",
        AsyncMock(
            return_value=[
                {
                    "provider_name": "Studio",
                    "provider_tag": "studio",
                    "supported_parameters": {
                        "resolution": {"values": ["1K", "4K"]},
                        "aspect_ratio": {"values": ["16:9"]},
                        "input_references": {"max": 14},
                    },
                }
            ]
        ),
    )
    await lab.handle_callback(callback, state)
    callback.data = "admin_gmi:resolution:4K"
    await lab.handle_callback(callback, state)
    await state.clear()
    callback.data = "admin_gmi:open"
    await lab.handle_callback(callback, state)
    assert "4K" in message.edit_text.call_args.args[0]
    assert (await lab.load_session(111))["resolution"] == "4K"


def capabilities():
    return [
        {
            "provider_name": "Studio",
            "provider_tag": "studio",
            "supported_parameters": {
                "resolution": {"values": ["1K", "4K"]},
                "aspect_ratio": {"values": ["16:9", "1:1"]},
                "input_references": {"max": 14},
            },
        },
        {
            "provider_name": "Vertex",
            "provider_tag": "vertex",
            "supported_parameters": {
                "resolution": {"values": ["1K"]},
                "aspect_ratio": {"values": ["16:9"]},
                "input_references": {"max": 14},
            },
        },
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt": "  "},
        {"resolution": "8K"},
        {"resolution": "4K", "provider": "vertex"},
        {"ratio": "7:1"},
        {"references": ["https://example.com/ref.png"] * 15},
        {"references": ["file:///etc/passwd"]},
        {"provider": "unknown"},
    ],
)
def test_unsupported_generation_rejected_before_paid_request(changes):
    options = {
        "prompt": "Poster",
        "references": [],
        "ratio": "auto",
        "resolution": "1K",
        "provider": "auto",
        "capabilities": capabilities(),
    }
    options.update(changes)
    with pytest.raises(ValueError):
        OpenRouterImageService.build_payload(**options)


@pytest.mark.parametrize("status", [401, 402, 429, 502])
@pytest.mark.asyncio
async def test_http_error_is_sanitized_and_never_retried(image_server, status):
    from aiohttp import web

    from bot.services.openrouter_image_service import ImageProviderError

    calls = []

    async def failed(request):
        calls.append(await request.json())
        return web.json_response(
            {"error": {"message": "SECRET PROMPT AND TOKEN"}}, status=status
        )

    app = web.Application()
    app.router.add_post("/images", failed)
    server = await image_server(app)
    service = OpenRouterImageService(
        api_key="secret", base_url=server.make_url("").rstrip("/")
    )
    with pytest.raises(ImageProviderError) as error:
        await service.generate(
            prompt="Poster",
            references=[],
            ratio="auto",
            resolution="1K",
            provider="auto",
            capabilities=capabilities(),
        )
    assert "SECRET" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"data": []},
        {"error": {"message": "secret"}},
        {"data": [{"b64_json": "not base64"}]},
        {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]},
        ["invalid"],
    ],
)
@pytest.mark.asyncio
async def test_malformed_or_empty_result_has_safe_error(image_server, body):
    from aiohttp import web

    from bot.services.openrouter_image_service import ImageProviderError

    async def respond(request):
        return web.json_response(body)

    app = web.Application()
    app.router.add_post("/images", respond)
    server = await image_server(app)
    service = OpenRouterImageService(
        api_key="key", base_url=server.make_url("").rstrip("/")
    )
    with pytest.raises(ImageProviderError):
        await service.generate(
            prompt="Poster",
            references=[],
            ratio="auto",
            resolution="1K",
            provider="auto",
            capabilities=capabilities(),
        )


@pytest.fixture
async def lab_context(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from bot.handlers import admin_gemini_image_lab as lab

    monkeypatch.setattr(lab.config, "ADMIN_IDS_STR", "111")
    monkeypatch.setattr(lab, "OUTPUT_ROOT", tmp_path / "results")
    monkeypatch.setattr(lab, "_LOCKS", {})
    monkeypatch.setattr(lab.openrouter_image_service, "api_key", "test")
    monkeypatch.setattr(
        lab.openrouter_image_service,
        "capabilities",
        AsyncMock(return_value=capabilities()),
    )
    bot = SimpleNamespace(
        send_photo=AsyncMock(), send_document=AsyncMock(), send_message=AsyncMock()
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        edit_text=AsyncMock(),
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=111),
        text=None,
        photo=None,
        document=None,
        caption=None,
        bot=bot,
    )
    callback = SimpleNamespace(
        from_user=message.from_user,
        message=message,
        data="admin_gmi:open",
        answer=AsyncMock(),
        bot=bot,
    )
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=111, user_id=111))
    await lab.handle_callback(callback, state)
    return lab, callback, state


@pytest.mark.asyncio
async def test_double_click_runs_once_and_recovers_original_after_delivery_failure(
    lab_context, monkeypatch
):
    import asyncio
    from unittest.mock import AsyncMock

    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendDocument

    from bot.services.openrouter_image_service import GeneratedImage, ImageResult

    lab, callback, state = lab_context
    gate = asyncio.Event()
    result = ImageResult(
        [GeneratedImage(image_bytes(), "png")], "provider-123", {"cost": 0.1}
    )

    async def generate(**kwargs):
        await gate.wait()
        return result

    provider = AsyncMock(side_effect=generate)
    monkeypatch.setattr(lab.openrouter_image_service, "generate", provider)
    callback.bot.send_document.side_effect = TelegramBadRequest(
        method=SendDocument(chat_id=111, document="file"), message="temporary failure"
    )
    data = await lab.load_session(111)
    data["prompt"] = "A poster"
    await lab.save_session(111, data)
    callback.data = f"admin_gmi:generate:{data['nonce']}"
    await asyncio.gather(
        lab.handle_callback(callback, state), lab.handle_callback(callback, state)
    )
    await asyncio.sleep(0)
    assert provider.await_count == 1
    assert (await lab.load_session(111))["job"]["status"] == "running"
    gate.set()
    await asyncio.gather(*list(lab._TASKS))
    data = await lab.load_session(111)
    assert data["job"]["status"] == "ready"
    assert data["job"]["provider_id"] == "provider-123"
    await state.clear()
    callback.bot.send_document.side_effect = None
    callback.data = "admin_gmi:result"
    await lab.handle_callback(callback, state)
    document = callback.bot.send_document.call_args.kwargs["document"]
    assert document.path.read_bytes() == image_bytes()
    assert provider.await_count == 1


@pytest.mark.asyncio
async def test_album_upload_serializes_and_edit_uses_result_reference(
    lab_context, monkeypatch
):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    lab, callback, state = lab_context
    callback.data = "admin_gmi:refs"
    await lab.handle_callback(callback, state)

    async def save(message, **kwargs):
        await asyncio.sleep(0)
        return f"https://example.com/{message.photo[-1].file_id}.png", None

    monkeypatch.setattr(lab, "_save_reference_image_from_message", save)
    messages = [
        SimpleNamespace(
            **{
                **vars(callback.message),
                "photo": [SimpleNamespace(file_id=str(i), file_size=10)],
            }
        )
        for i in range(3)
    ]
    await asyncio.gather(*(lab.receive_message(m, state) for m in messages))
    data = await lab.load_session(111)
    assert data["references"] == [f"https://example.com/{i}.png" for i in range(3)]
    import uuid

    job = {"id": str(uuid.uuid4()), "status": "ready", "files": ["1.png"]}
    path = lab.OUTPUT_ROOT / job["id"] / "1.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(image_bytes())
    data["job"] = job
    await lab.save_session(111, data)
    save_result = AsyncMock(return_value="https://example.com/generated.png")
    monkeypatch.setattr(lab, "_persist_reusable_media_reference", save_result)
    callback.data = "admin_gmi:edit"
    await lab.handle_callback(callback, state)
    data = await lab.load_session(111)
    assert data["references"] == ["https://example.com/generated.png"]
    assert data["prompt"] == ""
    assert await state.get_state() == lab.GeminiImageLabStates.prompt.state
    assert save_result.call_args.args[1] == image_bytes()


@pytest.mark.asyncio
async def test_provider_switch_normalizes_4k_and_rejects_forged_callbacks(lab_context):
    lab, callback, state = lab_context
    callback.data = "admin_gmi:resolution:4K"
    await lab.handle_callback(callback, state)
    callback.data = "admin_gmi:provider:vertex"
    await lab.handle_callback(callback, state)
    assert (await lab.load_session(111))["resolution"] == "1K"
    callback.data = "admin_gmi:resolution:4K"
    await lab.handle_callback(callback, state)
    assert (await lab.load_session(111))["resolution"] == "1K"


@pytest.mark.asyncio
async def test_revoked_admin_cannot_upload_or_generate(lab_context, monkeypatch):
    lab, callback, state = lab_context
    await state.set_state(lab.GeminiImageLabStates.prompt)
    monkeypatch.setattr(lab.config, "ADMIN_IDS_STR", "")
    callback.message.text = "secret prompt"
    await lab.receive_message(callback.message, state)
    assert await state.get_state() is None
    assert (await lab.load_session(111))["prompt"] == ""
    callback.data = "admin_gmi:generate:forged"
    await lab.handle_callback(callback, state)
    callback.answer.assert_awaited_with("⛔ Нет доступа", show_alert=True)


@pytest.mark.asyncio
async def test_interrupted_request_is_not_retried_on_reopening(
    lab_context, monkeypatch
):
    from unittest.mock import AsyncMock

    lab, callback, state = lab_context
    data = await lab.load_session(111)
    data["job"] = {
        "id": "old",
        "status": "running",
        "started": 0,
        "settings": {"timeout": 120},
    }
    await lab.save_session(111, data)
    generate = AsyncMock()
    monkeypatch.setattr(lab.openrouter_image_service, "generate", generate)
    await lab.handle_callback(callback, state)
    assert (await lab.load_session(111))["job"]["status"] == "unknown"
    generate.assert_not_awaited()
