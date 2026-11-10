"""HMAC-authenticated read-only bridge to the native VK legacy account.

The bridge owns no money. It cannot create or modify balances, and it never
derives a VK identity from untrusted query strings.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlsplit

import aiohttp


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
