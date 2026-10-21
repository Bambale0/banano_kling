import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.config import config
from bot.services import ai_assistant_service as module


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'transient', 'permanent'])
async def test_audio_uses_configured_multimodal_chat_contract_with_bounded_retry(monkeypatch, caplog, failure):
    received = []

    async def provider(request):
        received.append(await request.json())
        if failure == 'permanent':
            return web.json_response({'error': 'sensitive-provider-body'}, status=400)
        if failure == 'transient' and len(received) == 1:
            return web.json_response({'code': 502, 'msg': 'sensitive-provider-body'})
        return web.json_response({'choices': [{'message': {'content': 'Understood the synthetic audio'}}]})

    app = web.Application()
    app.router.add_post('/chat/completions', provider)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setattr(config, 'OPENROUTER_BASE_URL', str(server.make_url('')).rstrip('/'))
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'synthetic-key')
    monkeypatch.setattr(config, 'AI_ASSISTANT_AUDIO_MODEL', 'synthetic-audio-model')
    monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
    assistant = module.AIAssistantService()
    monkeypatch.setattr(assistant, '_get_system_prompt', lambda **kw: 'system')
    monkeypatch.setattr(assistant, 'get_pricing_info', lambda: 'prices')
    try:
        result = await assistant.get_assistant_response_with_audio(audio_bytes=b'synthetic-audio', audio_format='ogg')
    finally:
        await server.close()
    if failure == 'permanent':
        assert result is None
        assert len(received) == 1
    else:
        assert result == 'Understood the synthetic audio'
        assert len(received) == (2 if failure else 1)
        payload = received[-1]
        assert payload['model'] == 'synthetic-audio-model'
        audio = payload['messages'][1]['content'][1]
        assert audio['type'] == 'input_audio'
        assert audio['input_audio']['format'] == 'ogg'
        assert base64.b64decode(audio['input_audio']['data']) == b'synthetic-audio'
    assert 'sensitive-provider-body' not in caplog.text
