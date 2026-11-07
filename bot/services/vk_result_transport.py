"""Transport-only VK contracts. Never changes users, tasks, balances or refunds."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from PIL import Image

from bot.config import config

logger = logging.getLogger(__name__)


class VKSendUncertain(RuntimeError):
    pass


class VKConfigurationRequired(RuntimeError):
    pass


class VKBeforeSendUnavailable(RuntimeError):
    pass


class VKRejected(RuntimeError):
    def __init__(self, code: int):
        self.code = code
        super().__init__(f'VK rejected operation: {code}')


class VKResultTransport:
    def __init__(self, *, api_base='https://api.vk.com/method/'):
        self.api_base = api_base

    @staticmethod
    def configured_for(community_id) -> bool:
        return bool(config.VK_GROUP_TOKEN and type(community_id) is int and community_id > 0
                    and config.VK_GROUP_TOKEN_COMMUNITY_ID.strip() == str(community_id))

    def check_community(self, job):
        if not self.configured_for(job.get('community_id')):
            raise VKConfigurationRequired()

    @staticmethod
    async def read_json(response):
        raw = bytearray()
        async for block in response.content.iter_chunked(8192):
            raw.extend(block)
            if len(raw) > 65536:
                raise ValueError('Oversized VK response')
        if response.status != 200:
            raise ValueError('Invalid VK status')
        return json.loads(raw)

    async def api(self, method: str, values: dict, *, sending=False):
        token = config.VK_GROUP_TOKEN
        if not token:
            raise VKConfigurationRequired()
        try:
            timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)
            async with (
                aiohttp.ClientSession(timeout=timeout, trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as session,
                session.post(self.api_base + method, data={**values, 'access_token': token, 'v': '5.199'}, allow_redirects=False) as response,
            ):
                payload = await self.read_json(response)
            if isinstance(payload, dict) and isinstance(payload.get('error'), dict):
                code = payload['error'].get('error_code')
                if type(code) is not int:
                    raise ValueError('Invalid VK error')
                raise VKRejected(code)
            if not isinstance(payload, dict) or 'response' not in payload:
                raise ValueError('Invalid VK acknowledgement')
            return payload['response']
        except VKRejected:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            # Do not propagate payload/error text: VK errors may echo tokens.
            if sending:
                raise VKSendUncertain() from None
            raise VKBeforeSendUnavailable() from None

    async def permission(self, job) -> bool:
        self.check_community(job)
        result = await self.api('messages.isMessagesFromGroupAllowed', {'group_id': job['community_id'], 'user_id': job['vk_user_id']})
        if not isinstance(result, dict) or type(result.get('is_allowed')) is not int or result['is_allowed'] not in {0, 1}:
            raise VKConfigurationRequired()
        return result['is_allowed'] == 1

    async def prepare(self, job) -> str | None:
        from bot.genjutsu.media import PublicResolver
        from bot.services.wan3_prime_media import assert_public_url
        from bot.services.wan3_prime_storage import fetch_public_asset

        self.check_community(job)
        # VK photo upload cannot accept generated video. Deliver the durable
        # public URL immediately instead of downloading a large MP4 only to
        # fail Pillow decoding.
        suffix = Path(urlsplit(str(job.get("result_url") or "")).path).suffix.lower()
        if job.get("result_type") == "video" or suffix in {
            ".mp4",
            ".mov",
            ".webm",
            ".mkv",
        }:
            return None
        # Upload failure before messages.send permits one link-only payload.
        phase = 'download'
        try:
            async with asyncio.timeout(100):
                with tempfile.TemporaryDirectory(prefix='neuromix-vk-result-') as directory:
                    path = Path(directory) / 'result.image'
                    await fetch_public_asset(job['result_url'], destination=path, max_bytes=50 * 1024 * 1024, timeout_seconds=60)
                    phase = 'decode'

                    def inspect():
                        with Image.open(path) as image:
                            if image.format not in {'PNG', 'JPEG'} or image.width * image.height > 25_000_000:
                                raise ValueError('Invalid photo dimensions or format')
                            jpeg = image.format == 'JPEG'
                            image.verify()
                            return ('result.jpg', 'image/jpeg') if jpeg else ('result.png', 'image/png')

                    inspection = asyncio.create_task(asyncio.to_thread(inspect))
                    try:
                        filename, content_type = await asyncio.shield(inspection)
                    except asyncio.CancelledError:
                        # The worker still owns this temporary file until done.
                        await asyncio.shield(inspection)
                        raise
                    phase = 'upload_server'
                    upload = await self.api('photos.getMessagesUploadServer', {'peer_id': job['vk_user_id']})
                    url = upload.get('upload_url') if isinstance(upload, dict) else None
                    if not isinstance(url, str):
                        raise TypeError('Missing upload URL')
                    await assert_public_url(url)
                    phase = 'upload'
                    resolver = PublicResolver()
                    try:
                        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
                        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=25), trust_env=False,
                                                         cookie_jar=aiohttp.DummyCookieJar()) as session:
                            with path.open('rb') as handle:
                                body = aiohttp.FormData()
                                body.add_field('photo', handle, filename=filename, content_type=content_type)
                                async with session.post(url, data=body, allow_redirects=False) as response:
                                    uploaded = await self.read_json(response)
                    finally:
                        await resolver.close()
                    if not isinstance(uploaded, dict) or not {'server', 'photo', 'hash'} <= uploaded.keys():
                        raise ValueError('Invalid uploaded photo')
                    phase = 'save_photo'
                    saved = await self.api('photos.saveMessagesPhoto', {key: uploaded[key] for key in ('server', 'photo', 'hash')})
                    if not isinstance(saved, list) or not saved or not isinstance(saved[0], dict):
                        raise ValueError('Missing saved photo')
                    photo = saved[0]
                    if type(photo.get('owner_id')) is not int or type(photo.get('id')) is not int or photo['id'] <= 0:
                        raise ValueError('Invalid attachment')
                    attachment = f"photo{photo['owner_id']}_{photo['id']}"
                    if photo.get('access_key'):
                        if not isinstance(photo['access_key'], str) or not photo['access_key'].isalnum():
                            raise ValueError('Invalid attachment key')
                        attachment += '_' + photo['access_key']
                    return attachment
        except Exception as exc:  # noqa: BLE001 - only before-send preparation may fall back to a link.
            # Never log remote responses, URLs, access keys or credential values.
            logger.warning('vk_photo_prepare_failed task_id=%s phase=%s error_type=%s vk_code=%s',
                           job.get('task_id'), phase, type(exc).__name__, exc.code if isinstance(exc, VKRejected) else None)
            return None

    async def send(self, job) -> int:
        self.check_community(job)
        values = {'user_id': job['vk_user_id'], 'random_id': job['random_id'], 'message': job['message'], 'dont_parse_links': 1}
        if job.get('attachment'):
            values['attachment'] = job['attachment']
        result = await self.api('messages.send', values, sending=True)
        if type(result) is not int or result <= 0:
            raise VKSendUncertain()
        return result
