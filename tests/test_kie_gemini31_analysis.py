import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer


@pytest.fixture(autouse=True)
def isolated_analysis_settings(monkeypatch):
    from bot import database

    monkeypatch.setattr(database, "_BOT_SETTING_CACHE", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media_url", ["https://example.test/photo.jpg", "https://example.test/video.mp4"]
)
async def test_gemini_media_contract_and_text_response(media_url):
    from bot.services.kie_gemini31_service import KieGemini31Service

    captured = {}

    async def provider(request):
        captured["body"] = await request.json()
        captured["auth"] = request.headers.get("Authorization")
        return web.json_response({"choices": [{"message": {"content": " Анализ "}}]})

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test-key", base_url=str(server.make_url("")).rstrip("/")
        )
        result = await service.analyze_media(
            media_url=media_url, user_instruction="Analyze", system_prompt="JSON only"
        )
    assert result == "Анализ"
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"] == {
        "messages": [
            {"role": "system", "content": "JSON only"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze"},
                    {"type": "image_url", "image_url": {"url": media_url}},
                ],
            },
        ],
        "stream": False,
        "include_thoughts": False,
        "reasoning_effort": "high",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["photo", "video", "v2_photo"])
async def test_media_services_default_to_gemini(surface, monkeypatch):
    from bot.config import config
    from bot.services.photo_prompt_service import PhotoPromptService
    from bot.services.prompt_analyzer_v2_service import PromptAnalyzerV2Service
    from bot.services.video_prompt_service import VideoPromptService

    seen = []

    async def provider(request):
        seen.append(await request.json())
        return web.json_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"prompt_ru":"Промпт по медиа","prompt_en":"Media prompt","key_details":[]}'
                        }
                    }
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            config, "KIE_BASE_URL", str(server.make_url("")).rstrip("/")
        )
        if surface == "photo":
            result = await PhotoPromptService(api_key="test").analyze_photo(
                image_url="https://example.test/photo.jpg"
            )
        elif surface == "video":
            result = await VideoPromptService(api_key="test").analyze_video(
                video_url="https://example.test/video.mp4"
            )
        else:
            result = await PromptAnalyzerV2Service(api_key="test").analyze_prompt(
                image_url="https://example.test/photo.jpg"
            )
    assert result["prompt_ru"] == "Промпт по медиа"
    assert len(seen) == 1
    assert seen[0]["messages"][-1]["content"][-1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_gemini_rejects_auth_without_retry(monkeypatch):
    from bot.services.kie_gemini31_service import KieGemini31Service

    calls = []

    async def provider(request):
        calls.append(1)
        return web.json_response({}, status=401)

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test", base_url=str(server.make_url("")).rstrip("/")
        )
        with pytest.raises(RuntimeError):
            await service.analyze_media(
                media_url="https://example.test/video.mp4", user_instruction="Analyze"
            )
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_body",
    [{}, {"choices": [{"message": {"content": ""}}]}],
)
async def test_gemini_retries_invalid_or_empty_200_then_succeeds(
    first_body, monkeypatch
):
    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(config, "KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS", 2)
    calls = []

    async def provider(request):
        calls.append(1)
        if len(calls) == 1:
            return web.json_response(first_body)
        return web.json_response(
            {"choices": [{"message": {"content": "Recovered by Gemini"}}]}
        )

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test", base_url=str(server.make_url("")).rstrip("/")
        )
        result = await service.analyze_media(
            media_url="https://example.test/video.mp4", user_instruction="Analyze"
        )
    assert result == "Recovered by Gemini"
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_url", "media_kind"),
    [
        ("https://example.test/photo.jpg", "image"),
        ("https://example.test/video.mp4", "video"),
    ],
)
async def test_gemini_body_500_falls_back_to_kie_gemini35(
    media_url, media_kind, monkeypatch
):
    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(
        config,
        "KIE_MEDIA_ANALYSIS_FALLBACK_ENDPOINT",
        "/gemini-3-5-flash-openai/v1/chat/completions",
    )
    monkeypatch.setattr(
        config,
        "KIE_MEDIA_ANALYSIS_FALLBACK_MODEL",
        "gemini-3-5-flash-thinking",
    )
    primary_calls = []
    fallback_calls = []

    async def primary(request):
        primary_calls.append(1)
        return web.json_response({"code": 500, "msg": "upstream unavailable"})

    async def fallback(request):
        fallback_calls.append(await request.json())
        return web.json_response(
            {"choices": [{"message": {"content": "Recovered by KIE Gemini 3.5"}}]}
        )

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", primary)
    app.router.add_post(
        "/gemini-3-5-flash-openai/v1/chat/completions",
        fallback,
    )
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test", base_url=str(server.make_url("")).rstrip("/")
        )
        result = await service.analyze_media(
            media_url=media_url,
            media_kind=media_kind,
            user_instruction="Analyze",
            system_prompt="JSON only",
        )

    assert result == "Recovered by KIE Gemini 3.5"
    assert len(primary_calls) == 1
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["model"] == "gemini-3-5-flash-thinking"
    media_part = fallback_calls[0]["messages"][-1]["content"][-1]
    assert media_part == {"type": "image_url", "image_url": {"url": media_url}}


@pytest.mark.asyncio
async def test_gemini_retries_rate_limit_then_succeeds(monkeypatch):
    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(config, "KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS", 2)
    calls = []

    async def provider(request):
        calls.append(1)
        if len(calls) == 1:
            return web.json_response({}, status=429)
        return web.json_response({"choices": [{"message": {"content": "Recovered"}}]})

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test", base_url=str(server.make_url("")).rstrip("/")
        )
        assert (
            await service.analyze_media(
                media_url="https://example.test/photo.jpg", user_instruction="Analyze"
            )
            == "Recovered"
        )
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_admin_can_switch_media_analysis_but_user_cannot(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.handlers.admin import cmd_analysis_provider
    from bot.services.kie_gemini31_service import media_analysis_provider

    monkeypatch.setattr(config, "ADMIN_IDS_STR", "999999999")
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=81002),
        text="/analysis_provider qwen38",
        answer=AsyncMock(),
    )
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == "kie_gemini31"
    message.from_user.id = 999999999
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == "qwen38"
    message.text = "/analysis_provider unknown"
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == "qwen38"
    message.text = "/analysis_provider kie_gemini31"
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == "kie_gemini31"


@pytest.mark.asyncio
async def test_gemini_timeout_falls_back_to_kie_gemini35(monkeypatch):
    import asyncio

    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(config, "KIE_MEDIA_ANALYSIS_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(config, "KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(config, "KIE_MEDIA_ANALYSIS_FALLBACK_MAX_ATTEMPTS", 1)

    async def primary(request):
        await asyncio.sleep(2)
        return web.json_response({})

    async def fallback(request):
        return web.json_response(
            {"choices": [{"message": {"content": "Recovered after timeout"}}]}
        )

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", primary)
    app.router.add_post(
        "/gemini-3-5-flash-openai/v1/chat/completions",
        fallback,
    )
    async with TestServer(app) as server:
        service = KieGemini31Service(
            api_key="test", base_url=str(server.make_url("")).rstrip("/")
        )
        result = await service.analyze_media(
            media_url="https://example.test/video.mp4",
            media_kind="video",
            user_instruction="Analyze",
        )

    assert result == "Recovered after timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["photo", "video", "v2_photo"])
async def test_selected_gemini_does_not_auto_fallback_to_qwen(surface, monkeypatch):
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.services import (
        photo_prompt_service,
        prompt_analyzer_v2_service,
        video_prompt_service,
    )

    async def provider(request):
        return web.json_response({}, status=401)

    qwen = AsyncMock()
    qwen.enabled = True
    qwen.model = "qwen-test"
    qwen.analyze_image.return_value = (
        '{"prompt_ru":"Fallback result","prompt_en":"Fallback result"}'
    )
    qwen.analyze_video.return_value = qwen.analyze_image.return_value
    module = {
        "photo": photo_prompt_service,
        "video": video_prompt_service,
        "v2_photo": prompt_analyzer_v2_service,
    }[surface]
    monkeypatch.setattr(module, "openrouter_qwen38_service", qwen)
    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            config, "KIE_BASE_URL", str(server.make_url("")).rstrip("/")
        )
        with pytest.raises(RuntimeError):
            if surface == "photo":
                await module.PhotoPromptService(api_key="test").analyze_photo(
                    image_url="https://example.test/photo.jpg"
                )
            elif surface == "video":
                await module.VideoPromptService(api_key="test").analyze_video(
                    video_url="https://example.test/video.mp4"
                )
            else:
                await module.PromptAnalyzerV2Service(
                    api_key="test"
                ).analyze_prompt(image_url="https://example.test/photo.jpg")
    qwen.analyze_image.assert_not_awaited()
    qwen.analyze_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["photo", "video", "v2_photo"])
@pytest.mark.parametrize("malformed", [False, True])
async def test_analysis_trace_links_gemini_retry_to_user(
    surface, malformed, monkeypatch, caplog
):
    import logging
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.services import (
        photo_prompt_service,
        prompt_analyzer_v2_service,
        video_prompt_service,
    )

    sensitive = "PRIVATE_MEDIA_OR_PROMPT"
    output = '{"prompt_ru":"Результат","prompt_en":"Result"}'
    calls = 0

    async def provider(request):
        nonlocal calls
        calls += 1
        if malformed and calls == 1:
            return web.json_response({"private": sensitive})
        return web.json_response(
            {"choices": [{"message": {"content": output}}]}
        )

    qwen = AsyncMock()
    qwen.enabled = True
    qwen.model = "qwen-test"
    qwen.analyze_image.return_value = output
    qwen.analyze_video.return_value = output
    module = {
        "photo": photo_prompt_service,
        "video": video_prompt_service,
        "v2_photo": prompt_analyzer_v2_service,
    }[surface]
    monkeypatch.setattr(module, "openrouter_qwen38_service", qwen)
    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    caplog.set_level(logging.INFO)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            config, "KIE_BASE_URL", str(server.make_url("")).rstrip("/")
        )
        url = "https://example.test/" + sensitive
        if surface == "photo":
            result = await module.PhotoPromptService(api_key=sensitive).analyze_photo(
                image_url=url, telegram_user_id=81002
            )
        elif surface == "video":
            result = await module.VideoPromptService(api_key=sensitive).analyze_video(
                video_url=url, telegram_user_id=81002
            )
        else:
            result = await module.PromptAnalyzerV2Service(
                api_key=sensitive
            ).analyze_prompt(image_url=url, telegram_user_id=81002)
    assert result["prompt_en"] == "Result"
    assert calls == (2 if malformed else 1)
    qwen.analyze_image.assert_not_awaited()
    qwen.analyze_video.assert_not_awaited()
    records = [r for r in caplog.records if hasattr(r, "analysis_event")]
    assert records
    assert len({r.request_id for r in records}) == 1
    assert all(r.telegram_user_id == 81002 for r in records)
    assert records[-1].analysis_event == "operation_success"
    if malformed:
        assert any(
            r.analysis_event == "provider_retry"
            and r.error_category == "invalid_response"
            for r in records
        )
        assert not any(r.analysis_event == "fallback" for r in records)
    assert any(r.analysis_event == "provider_success" for r in records)
    assert records[-1].analysis_provider == "kie_gemini31"
    assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_analysis_terminal_failure_is_sanitized_and_does_not_leak_context(
    monkeypatch, caplog
):
    import logging
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.services import photo_prompt_service as module

    secret = "PRIVATE_PROVIDER_ERROR_BODY"
    qwen = AsyncMock()
    qwen.enabled = True
    qwen.analyze_image.side_effect = RuntimeError(secret)
    monkeypatch.setattr(module, "openrouter_qwen38_service", qwen)

    async def provider(request):
        return web.json_response({"private": secret}, status=401)

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    caplog.set_level(logging.INFO)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            config, "KIE_BASE_URL", str(server.make_url("")).rstrip("/")
        )
        for user_id in (81002, 81003):
            with pytest.raises(RuntimeError):
                await module.PhotoPromptService(api_key=secret).analyze_photo(
                    image_url="https://example.test/photo.jpg",
                    telegram_user_id=user_id,
                )
    records = [r for r in caplog.records if hasattr(r, "analysis_event")]
    terminal = [r for r in records if r.analysis_event == "operation_failure"]
    assert len(terminal) == 2
    assert {r.telegram_user_id for r in terminal} == {81002, 81003}
    assert len({r.request_id for r in terminal}) == 2
    assert all(r.error_category == "RuntimeError" for r in terminal)
    for terminal_record in terminal:
        operation = [r for r in records if r.request_id == terminal_record.request_id]
        assert all(
            r.telegram_user_id == terminal_record.telegram_user_id for r in operation
        )
        assert any(
            r.analysis_event == "provider_failure" and r.error_category == "http_error"
            for r in operation
        )
    assert secret not in caplog.text
