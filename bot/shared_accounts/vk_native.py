"""HMAC-authenticated loopback bridge to the native VK legacy account.

The bridge owns no money. Native writes are explicitly gated and it never
derives a VK identity from untrusted query strings.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlsplit

import aiohttp

from .errors import PreviewConflict
from .wallet import InsufficientFunds


def _internal_origin() -> str:
    value = os.getenv('VK_NATIVE_INTERNAL_ORIGIN', 'http://127.0.0.1:1777').strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme != 'http'
        or parsed.hostname not in {'127.0.0.1', 'localhost'}
        or parsed.username
        or parsed.password
        or parsed.path not in {'', '/'}
        or parsed.query
        or parsed.fragment
        or not parsed.port
    ):
        raise RuntimeError('VK native internal origin must be loopback HTTP')
    return f'http://{parsed.hostname}:{parsed.port}'


async def fetch_native_vk_state(vk_user_id: int) -> dict:
    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    origin = _internal_origin()
    path = f'/internal/v1/miniapp/users/{vk_user_id}/state'
    timestamp = str(int(time.time()))
    message = f'{timestamp}\nGET\n{path}\n'.encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    headers = {
        'X-Internal-Timestamp': timestamp,
        'X-Internal-Signature': signature,
    }
    timeout = aiohttp.ClientTimeout(total=5, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.get(origin + path, headers=headers, allow_redirects=False) as result,
    ):
        if result.status != 200:
            raise RuntimeError('VK native state unavailable')
        data = await result.json()
    if (
        not isinstance(data, dict)
        or type(data.get('registered')) is not bool
        or not isinstance(data.get('tasks'), list)
        or type(data.get('is_blocked')) is not bool
        or (data.get('balance') is not None and
            (not isinstance(data['balance'], (int, float)) or
             isinstance(data['balance'], bool)))
    ):
        raise RuntimeError('VK native state invalid')
    return data



async def submit_native_vk_image(vk_user_id: int, payload: dict) -> dict:
    """Delegate a single idempotent charge+task to native VK. Never pass TG ID."""
    import json

    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    if os.getenv('VK_MINIAPP_WRITES_ENABLED') != '1':
        raise PermissionError('VK native paid operations are disabled')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    origin = _internal_origin()
    path = f'/internal/v1/miniapp/users/{vk_user_id}/generations/image'
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    if len(body) > 32768:
        raise ValueError('VK image payload is too large')
    timestamp = str(int(time.time()))
    message = b'\n'.join([timestamp.encode(), b'POST', path.encode(), body])
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    timeout = aiohttp.ClientTimeout(total=12, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.post(origin + path, data=body, headers={
            'Content-Type': 'application/json',
            'X-Internal-Timestamp': timestamp,
            'X-Internal-Signature': signature,
        }, allow_redirects=False) as result,
    ):
        if result.status == 400:
            raise ValueError('Invalid or stale VK image request')
        if result.status == 402:
            raise InsufficientFunds('Insufficient VK balance')
        if result.status == 409:
            raise PreviewConflict('VK generation request conflicts with an earlier submission')
        if result.status == 403:
            raise PermissionError('VK user is blocked')
        if result.status != 200:
            raise RuntimeError('VK native image generation unavailable')
        data = await result.json()
    if (not isinstance(data, dict) or data.get('ok') is not True
        or type(data.get('task_id')) is not int
        or not 0 <= data['task_id'] < 2**63
        or not isinstance(data.get('cost'), (int, float))
        or isinstance(data.get('cost'), bool)):
        raise RuntimeError('VK native generation response invalid')
    return {'task_id': data['task_id'], 'cost': data['cost'],
            **({'quote_only': True} if data.get('quote_only') is True else {})}


async def submit_native_vk_video(vk_user_id: int, payload: dict) -> dict:
    """Delegate native VK video quote/charge. VK wallet remains authoritative.

    This intentionally uses a separate rollout flag; enabling photo generation
    must never silently enable video charging.
    """
    import json

    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    if os.getenv('VK_MINIAPP_VIDEO_WRITES_ENABLED') != '1':
        raise PermissionError('VK native video operations are disabled')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    path = f'/internal/v1/miniapp/users/{vk_user_id}/generations/video'
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    if len(body) > 32768:
        raise ValueError('VK video payload is too large')
    timestamp = str(int(time.time()))
    message = b'\n'.join([timestamp.encode(), b'POST', path.encode(), body])
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    timeout = aiohttp.ClientTimeout(total=12, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.post(_internal_origin() + path, data=body, headers={
            'Content-Type': 'application/json',
            'X-Internal-Timestamp': timestamp,
            'X-Internal-Signature': signature,
        }, allow_redirects=False) as result,
    ):
        if result.status == 400:
            raise ValueError('Invalid or stale VK video request')
        if result.status == 402:
            raise InsufficientFunds('Insufficient VK balance')
        if result.status == 403:
            raise PermissionError('VK user is blocked')
        if result.status == 409:
            raise PreviewConflict('VK video claim conflicts with an earlier request')
        if result.status != 200:
            raise RuntimeError('VK native video generation unavailable')
        data = await result.json()
    if (not isinstance(data, dict) or data.get('ok') is not True
        or type(data.get('task_id')) is not int
        or not 0 <= data['task_id'] < 2**63
        or not isinstance(data.get('cost'), (int, float))
        or isinstance(data.get('cost'), bool)):
        raise RuntimeError('VK native video response invalid')
    return {'task_id': data['task_id'], 'cost': data['cost'],
            **({'quote_only': True} if data.get('quote_only') is True else {})}
