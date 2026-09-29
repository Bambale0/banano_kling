import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer


@pytest.fixture(autouse=True)
def isolated_analysis_settings(monkeypatch):
    from bot import database
    monkeypatch.setattr(database, "_BOT_SETTING_CACHE", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("media_url", ["https://example.test/photo.jpg", "https://example.test/video.mp4"])
async def test_gemini_media_contract_and_text_response(media_url):
    from bot.services.kie_gemini31_service import KieGemini31Service

    captured = {}

    async def provider(request):
        captured["body"] = await request.json()
        captured["auth"] = request.headers.get("Authorization")
        return web.json_response({"choices": [{"message": {"content": " Анализ "}}]})

    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(api_key="test-key", base_url=str(server.make_url('')).rstrip('/'))
        result = await service.analyze_media(media_url=media_url, user_instruction="Analyze", system_prompt="JSON only")
    assert result == "Анализ"
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"] == {
        "messages": [
            {"role": "system", "content": "JSON only"},
            {"role": "user", "content": [
                {"type": "text", "text": "Analyze"},
                {"type": "image_url", "image_url": {"url": media_url}},
            ]},
        ],
        "stream": False, "include_thoughts": False, "reasoning_effort": "high",
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
        return web.json_response({"choices": [{"message": {"content":
            '{"prompt_ru":"Промпт по медиа","prompt_en":"Media prompt","key_details":[]}'
        }}]})

    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        monkeypatch.setattr(config, 'KIE_BASE_URL', str(server.make_url('')).rstrip('/'))
        if surface == 'photo':
            result = await PhotoPromptService(api_key='test').analyze_photo(image_url='https://example.test/photo.jpg')
        elif surface == 'video':
            result = await VideoPromptService(api_key='test').analyze_video(video_url='https://example.test/video.mp4')
        else:
            result = await PromptAnalyzerV2Service(api_key='test').analyze_prompt(image_url='https://example.test/photo.jpg')
    assert result['prompt_ru'] == 'Промпт по медиа'
    assert len(seen) == 1
    assert seen[0]['messages'][-1]['content'][-1]['type'] == 'image_url'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {}), (200, {}), (200, {'choices': [{'message': {'content': ''}}]})])
async def test_gemini_rejects_auth_and_invalid_responses_without_retry(status, body, monkeypatch):
    from bot.services.kie_gemini31_service import KieGemini31Service

    calls = []
    async def provider(request):
        calls.append(1)
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(api_key='test', base_url=str(server.make_url('')).rstrip('/'))
        with pytest.raises(RuntimeError):
            await service.analyze_media(media_url='https://example.test/video.mp4', user_instruction='Analyze')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_gemini_retries_rate_limit_then_succeeds(monkeypatch):
    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(config, 'KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS', 2)
    calls = []
    async def provider(request):
        calls.append(1)
        if len(calls) == 1:
            return web.json_response({}, status=429)
        return web.json_response({'choices': [{'message': {'content': 'Recovered'}}]})

    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(api_key='test', base_url=str(server.make_url('')).rstrip('/'))
        assert await service.analyze_media(media_url='https://example.test/photo.jpg', user_instruction='Analyze') == 'Recovered'
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_admin_can_switch_media_analysis_but_user_cannot(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.handlers.admin import cmd_analysis_provider
    from bot.services.kie_gemini31_service import media_analysis_provider

    monkeypatch.setattr(config, 'ADMIN_IDS_STR', '999999999')
    message = SimpleNamespace(from_user=SimpleNamespace(id=81002), text='/analysis_provider qwen38', answer=AsyncMock())
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == 'kie_gemini31'
    message.from_user.id = 999999999
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == 'qwen38'
    message.text = '/analysis_provider unknown'
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == 'qwen38'
    message.text = '/analysis_provider kie_gemini31'
    await cmd_analysis_provider(message)
    assert await media_analysis_provider() == 'kie_gemini31'


@pytest.mark.asyncio
async def test_gemini_timeout_is_finite(monkeypatch):
    import asyncio

    from bot.config import config
    from bot.services.kie_gemini31_service import KieGemini31Service

    monkeypatch.setattr(config, 'KIE_MEDIA_ANALYSIS_TIMEOUT_SECONDS', 1)
    monkeypatch.setattr(config, 'KIE_MEDIA_ANALYSIS_MAX_ATTEMPTS', 1)
    async def provider(request):
        await asyncio.sleep(2)
        return web.json_response({})
    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        service = KieGemini31Service(api_key='test', base_url=str(server.make_url('')).rstrip('/'))
        with pytest.raises(RuntimeError, match='network failure'):
            await service.analyze_media(media_url='https://example.test/video.mp4', user_instruction='Analyze')


@pytest.mark.asyncio
@pytest.mark.parametrize('surface', ['photo', 'video', 'v2_photo'])
async def test_gemini_failure_preserves_existing_qwen_fallback(surface, monkeypatch):
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
    qwen.model = 'qwen-test'
    qwen.analyze_image.return_value = '{"prompt_ru":"Fallback result","prompt_en":"Fallback result"}'
    qwen.analyze_video.return_value = qwen.analyze_image.return_value
    module = {'photo': photo_prompt_service, 'video': video_prompt_service, 'v2_photo': prompt_analyzer_v2_service}[surface]
    monkeypatch.setattr(module, 'openrouter_qwen38_service', qwen)
    app = web.Application()
    app.router.add_post('/gemini-3.1-pro/v1/chat/completions', provider)
    async with TestServer(app) as server:
        monkeypatch.setattr(config, 'KIE_BASE_URL', str(server.make_url('')).rstrip('/'))
        if surface == 'photo':
            result = await module.PhotoPromptService(api_key='test').analyze_photo(image_url='https://example.test/photo.jpg')
        elif surface == 'video':
            result = await module.VideoPromptService(api_key='test').analyze_video(video_url='https://example.test/video.mp4')
        else:
            result = await module.PromptAnalyzerV2Service(api_key='test').analyze_prompt(image_url='https://example.test/photo.jpg')
    assert result['prompt_ru'] == 'Fallback result'
