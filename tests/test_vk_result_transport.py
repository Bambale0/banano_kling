"""Real bounded HTTP contracts with a fake VK server and synthetic images."""
import asyncio
import io
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from bot.config import config
from bot.services.vk_result_transport import (
    VKBeforeSendUnavailable,
    VKRejected,
    VKResultTransport,
    VKSendUncertain,
)


@asynccontextmanager
async def api(monkeypatch, handler):
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '456')
    app = web.Application()
    app.router.add_post('/method/{method}', handler)
    async with TestClient(TestServer(app)) as client:
        yield VKResultTransport(api_base=str(client.make_url('/method/')))


async def test_permission_probe_and_send_use_group_token_and_stable_random_id(monkeypatch):
    calls = []

    async def handler(request):
        body = dict(await request.post())
        calls.append((request.match_info['method'], body))
        assert body.pop('access_token') == 'synthetic-group-secret'
        assert body.pop('v') == '5.199'
        return web.json_response({'response': {'is_allowed': 1} if request.match_info['method'] == 'messages.isMessagesFromGroupAllowed' else 321})

    async with api(monkeypatch, handler) as sender:
        job = {'community_id': 456, 'vk_user_id': 2001, 'random_id': -999, 'message': 'Synthetic result', 'attachment': 'photo-456_8'}
        assert await sender.permission(job)
        assert await sender.send(job) == 321
    assert calls[0][1] == {'group_id': '456', 'user_id': '2001'}
    assert calls[1][1] == {'user_id': '2001', 'random_id': '-999', 'message': 'Synthetic result', 'attachment': 'photo-456_8', 'dont_parse_links': '1'}


@pytest.mark.parametrize('sending', [False, True])
async def test_fragmented_response_is_read_to_eof_with_a_finite_bound(monkeypatch, sending):
    async def handler(request):
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)
        for part in (b'{"res', b'ponse":', b'123}'):
            await response.write(part)
            await asyncio.sleep(0)
        return response

    async with api(monkeypatch, handler) as sender:
        assert await sender.api('messages.send', {}, sending=sending) == 123


async def test_vk_error_that_echoes_credentials_is_redacted(monkeypatch, caplog):
    async def handler(_request):
        return web.json_response({'error': {'error_code': 901, 'error_msg': 'private', 'request_params': [{'access_token': 'synthetic-group-secret'}]}})

    async with api(monkeypatch, handler) as sender:
        with pytest.raises(VKRejected) as error:
            await sender.api('messages.send', {}, sending=True)
        assert error.value.code == 901
        assert 'synthetic-group-secret' not in str(error.value)
    assert 'synthetic-group-secret' not in caplog.text


@pytest.mark.parametrize('body', [b'<html>SPA fallback</html>', b'X' * 65537, b'{"response": null}'])
async def test_malformed_send_ack_never_becomes_a_success_or_safe_retry(monkeypatch, body):
    async def handler(_request):
        return web.Response(body=body)

    async with api(monkeypatch, handler) as sender:
        with pytest.raises(VKSendUncertain):
            await sender.send({'community_id': 456, 'vk_user_id': 2001, 'random_id': 999, 'message': 'Ready'})


async def test_pre_send_bad_response_allows_bounded_retry_but_does_not_invent_vk_error_code(monkeypatch):
    async def handler(_request):
        return web.Response(status=502, text='synthetic-group-secret')

    async with api(monkeypatch, handler) as sender:
        with pytest.raises(VKBeforeSendUnavailable):
            await sender.permission({'community_id': 456, 'vk_user_id': 2001})


@pytest.mark.parametrize('format, mime, filename', [('PNG', 'image/png', 'result.png'), ('JPEG', 'image/jpeg', 'result.jpg')])
async def test_actual_photo_upload_prepares_attachment_without_sending_a_message(monkeypatch, tmp_path, format, mime, filename):
    from bot.services import wan3_prime_media, wan3_prime_storage

    raw = io.BytesIO()
    Image.new('RGB', (2, 3), (12, 23, 34)).save(raw, format=format)
    calls = []
    app = web.Application()

    async def upload(request):
        fields = await request.multipart()
        part = await fields.next()
        assert part.name == 'photo'
        assert part.filename == filename and part.headers['Content-Type'] == mime
        with Image.open(io.BytesIO(await part.read())) as image:
            assert image.size == (2, 3)
        return web.json_response({'server': 7, 'photo': 'synthetic-upload', 'hash': 'fake-upload-hash'})

    async def handler(request):
        method = request.match_info['method']
        body = dict(await request.post())
        calls.append(method)
        if method == 'photos.getMessagesUploadServer':
            assert body['peer_id'] == '2001'
            return web.json_response({'response': {'upload_url': str(client.make_url('/upload'))}})
        assert method == 'photos.saveMessagesPhoto'
        assert body['hash'] == 'fake-upload-hash'
        return web.json_response({'response': [{'owner_id': -456, 'id': 9, 'access_key': 'abc123'}]})

    app.router.add_post('/upload', upload)
    app.router.add_post('/method/{method}', handler)
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '456')
    public_check = AsyncMock()
    monkeypatch.setattr(wan3_prime_media, 'assert_public_url', public_check)

    async def download(url, *, destination, max_bytes, timeout_seconds):
        assert max_bytes == 50 * 1024 * 1024 and timeout_seconds == 60
        destination.write_bytes(raw.getvalue())
        return {'content_type': 'image/png'}

    monkeypatch.setattr(wan3_prime_storage, 'fetch_public_asset', download)
    async with TestClient(TestServer(app)) as client:
        sender = VKResultTransport(api_base=str(client.make_url('/method/')))
        assert await sender.prepare({'community_id': 456, 'vk_user_id': 2001, 'result_url': 'https://example.test/result.png'}) == 'photo-456_9_abc123'
        public_check.assert_awaited_once_with(str(client.make_url('/upload')))
    assert calls == ['photos.getMessagesUploadServer', 'photos.saveMessagesPhoto']


async def test_video_type_uses_saved_link_even_when_cdn_url_has_no_extension(monkeypatch):
    from bot.services import wan3_prime_storage

    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '456')
    download = AsyncMock()
    monkeypatch.setattr(wan3_prime_storage, 'fetch_public_asset', download)
    sender = VKResultTransport()

    assert await sender.prepare({
        'community_id': 456,
        'vk_user_id': 2001,
        'result_type': 'video',
        'result_url': 'https://cdn.example.test/generated/result?id=123',
    }) is None
    download.assert_not_awaited()


async def test_unsafe_private_media_is_not_fetched_and_uses_only_the_saved_link(monkeypatch):
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '456')
    sender = VKResultTransport()
    sender.api = AsyncMock()
    assert await sender.prepare({'community_id': 456, 'vk_user_id': 2001, 'result_url': 'http://127.0.0.1/private'}) is None
    sender.api.assert_not_awaited()


async def test_credential_cannot_send_from_a_different_configured_community(monkeypatch):
    from bot.services.vk_result_transport import VKConfigurationRequired

    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '999')
    sender = VKResultTransport()
    sender.api = AsyncMock()
    with pytest.raises(VKConfigurationRequired):
        await sender.permission({'community_id': 456, 'vk_user_id': 2001})
    with pytest.raises(VKConfigurationRequired):
        await sender.send({'community_id': 456, 'vk_user_id': 2001, 'random_id': 3, 'message': 'Ready'})
    sender.api.assert_not_awaited()


async def test_socket_loss_after_server_accepts_send_is_uncertain_and_not_retried(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(dict(await request.post()))
        request.transport.close()
        return web.json_response({'response': 321})

    async with api(monkeypatch, handler) as sender:
        with pytest.raises(VKSendUncertain):
            await sender.send({'community_id': 456, 'vk_user_id': 2001, 'random_id': 3, 'message': 'Ready'})
    assert len(calls) == 1
