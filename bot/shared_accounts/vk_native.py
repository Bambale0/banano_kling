"""HMAC-authenticated loopback bridge to the native VK legacy account.

The bridge owns no money. Native writes are explicitly gated and it never
derives a VK identity from untrusted query strings.
"""
from __future__ import annotations

import hashlib
import hmac
import math
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



async def fetch_native_vk_models(vk_user_id: int) -> dict:
    """Read worker-supported native VK models; no Telegram price projection."""
    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    secret = os.getenv('INTERNAL_API_SECRET','')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    path = f'/internal/v1/miniapp/users/{vk_user_id}/models'
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(),
                         f'{stamp}\nGET\n{path}\n'.encode(),hashlib.sha256).hexdigest()
    timeout = aiohttp.ClientTimeout(total=5, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.get(_internal_origin()+path,allow_redirects=False,headers={
            'X-Internal-Timestamp':stamp,'X-Internal-Signature':signature,
        }) as result,
    ):
        if result.status in {403,404}:
            raise PermissionError('VK account cannot access model catalog')
        if result.status!=200:
            raise RuntimeError('VK native catalog unavailable')
        data=await result.json()
    if not isinstance(data,dict) or data.get('ok') is not True:
        raise RuntimeError('Invalid VK native catalog response')
    photos=data.get('photo_models')
    videos=data.get('video_models')
    if not isinstance(photos,list) or len(photos)>30 or not isinstance(videos,list) or len(videos)>60:
        raise RuntimeError('Invalid VK native model collection')
    for item in photos:
        if (not isinstance(item,dict) or type(item.get('id')) is not str
            or not item['id'] or type(item.get('label')) is not str
            or not isinstance(item.get('ratios'),list)
            or not isinstance(item.get('resolutions'),list)
            or type(item.get('max_references')) is not int
            or not 0<=item['max_references']<=4):
            raise RuntimeError('Invalid VK native photo model')
    for item in videos:
        if (not isinstance(item,dict) or type(item.get('id')) is not str
            or type(item.get('label')) is not str
            or not isinstance(item.get('ratios'),list)
            or not isinstance(item.get('scenarios'),list)
            or type(item.get('duration_min')) is not int
            or type(item.get('duration_max')) is not int
            or not 1<=item['duration_min']<=item['duration_max']<=60
            or type(item.get('max_image_references')) is not int
            or not 0<=item['max_image_references']<=4):
            raise RuntimeError('Invalid VK native video model')
    # Never forward additional provider fields, secrets or private account data.
    return {'ok':True,'photo_models':photos,'video_models':videos}


async def fetch_native_vk_commerce(vk_user_id: int) -> dict:
    """HMAC-only read of VK's authoritative purchases/partners; never TG wallet."""
    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    path = f'/internal/v1/miniapp/users/{vk_user_id}/commerce'
    stamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), f'{stamp}\nGET\n{path}\n'.encode(), hashlib.sha256,
    ).hexdigest()
    timeout = aiohttp.ClientTimeout(total=5, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.get(_internal_origin() + path, allow_redirects=False, headers={
            'X-Internal-Timestamp': stamp, 'X-Internal-Signature': signature,
        }) as result,
    ):
        if result.status == 403:
            raise PermissionError('Native VK account is blocked')
        if result.status != 200:
            raise RuntimeError('VK native commerce unavailable')
        data = await result.json()
    if (
        not isinstance(data, dict) or data.get('ok') is not True
        or type(data.get('registered')) is not bool
        or (data.get('balance') is not None and
            (type(data['balance']) not in (int, float) or data['balance'] < 0))
        or not isinstance(data.get('payment_packages'), list)
        or not isinstance(data.get('payments'), list)
        or not isinstance(data.get('referrals'), dict)
        or len(data['payments']) > 10
        or len(data['payment_packages']) > 50
    ):
        raise RuntimeError('VK native commerce response invalid')
    return data


async def create_native_vk_invoice(vk_user_id: int, payload: dict) -> tuple[int, dict]:
    """One attempt to native VK checkout. NEVER retry unknown provider results."""
    import json

    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    if not isinstance(payload, dict):
        raise TypeError('Invalid VK invoice request')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    path = f'/internal/v1/miniapp/users/{vk_user_id}/commerce/invoices'
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > 4096:
        raise ValueError('VK invoice request too large')
    stamp = str(int(time.time()))
    sig = hmac.new(
        secret.encode(), b'\n'.join([stamp.encode(), b'POST', path.encode(), raw]),
        hashlib.sha256,
    ).hexdigest()
    # A provider timeout is an UNKNOWN outcome. Never automatically retry.
    timeout = aiohttp.ClientTimeout(total=25, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.post(_internal_origin() + path, data=raw, allow_redirects=False,
                    headers={
                        'Content-Type': 'application/json',
                        'X-Internal-Timestamp': stamp,
                        'X-Internal-Signature': sig,
                    }) as result,
    ):
        status = result.status
        if status not in {200, 202, 400, 403, 404, 409, 429, 503}:
            raise RuntimeError('VK native checkout unavailable')
        data = await result.json()
    if not isinstance(data, dict) or type(data.get('ok')) is not bool:
        raise RuntimeError('Invalid VK native checkout response')
    if status in {200, 202}:
        if data['ok'] is not True or data.get('status') not in {'ready', 'paid', 'creating', 'unknown'}:
            raise RuntimeError('Invalid VK checkout state')
        amount = data.get('amount_rub')
        credits = data.get('credits')
        if type(amount) is not int or amount <= 0 or type(credits) is not int or credits <= 0:
            raise RuntimeError('Invalid VK checkout quote')
        result = {'ok': True, 'status': data['status'], 'amount_rub': amount, 'credits': credits}
        if data['status'] == 'ready':
            from urllib.parse import urlsplit

            pay = data.get('payment_url')
            if not isinstance(pay, str):
                raise RuntimeError('Invalid VK payment URL')
            target = urlsplit(pay)
            allowed_hosts = tuple(
                item.strip().lower().lstrip('.') for item in
                os.getenv('VK_MINIAPP_PAYMENT_ALLOWED_HOSTS', 'lava.top,lava.ru').split(',')
                if item.strip()
            )
            host = (target.hostname or '').lower().rstrip('.')
            if (target.scheme != 'https' or not host or target.username or target.password
                    or target.fragment or not any(host == domain or host.endswith('.' + domain)
                                                   for domain in allowed_hosts)):
                raise RuntimeError('Invalid VK payment URL')
            result['payment_url'] = pay
        return status, result
    if data['ok'] is not False:
        raise RuntimeError('Invalid VK checkout error state')
    permitted_errors = {
        'invalid_user', 'invalid_payload', 'invalid_content_type', 'invalid_json',
        'invalid_request_key', 'invalid_package', 'invalid_payment_method_or_email',
        'payment_method_unavailable', 'payment_provider_unavailable',
        'vk_account_unavailable', 'idempotency_conflict', 'invoice_rate_limited',
        'payment_limits_unconfigured', 'invoice_reconciliation_required',
        'not_enabled',
    }
    error = data.get('error')
    return status, {'ok': False, 'error': error if error in permitted_errors
                    else 'native_checkout_unavailable'}
class NativeVkOperationNotFound(LookupError):
    """The verified VK owner or requested native operation does not exist."""


async def _native_vk_operation_call(
    vk_user_id: int, *, action: str, payload: dict,
) -> dict:
    """Relay one exact-body HMAC wallet operation to native VK storage."""
    import json

    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    if action not in {'reserve', 'settle'} or not isinstance(payload, dict):
        raise ValueError('Invalid VK operation request')
    if {'user_id', 'vk_user_id', 'telegram_user_id'}.intersection(payload):
        raise ValueError('Actor fields are not accepted')
    if os.getenv('VK_NATIVE_SHARED_OPERATIONS_ENABLED') != '1':
        raise PermissionError('VK shared operations are disabled')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    path = f'/internal/v1/miniapp/users/{vk_user_id}/operations/{action}'
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    if len(body) > 32768:
        raise ValueError('VK operation payload is too large')
    stamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(),
        b'\n'.join([stamp.encode(), b'POST', path.encode(), body]),
        hashlib.sha256,
    ).hexdigest()
    timeout = aiohttp.ClientTimeout(total=8, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.post(_internal_origin() + path, data=body, headers={
            'Content-Type': 'application/json',
            'X-Internal-Timestamp': stamp,
            'X-Internal-Signature': signature,
        }, allow_redirects=False) as result,
    ):
        if result.status == 400:
            raise ValueError('Invalid native VK operation request')
        if result.status == 402:
            raise InsufficientFunds('Insufficient VK balance')
        if result.status == 403:
            raise PermissionError('VK native account is blocked')
        if result.status == 404:
            raise NativeVkOperationNotFound('VK account or operation not found')
        if result.status == 409:
            raise PreviewConflict('VK operation conflicts with an earlier request')
        if result.status != 200:
            raise RuntimeError('VK native operation ledger unavailable')
        data = await result.json()
    key = data.get('client_request_id') if isinstance(data, dict) else None
    expected_key = payload.get('client_request_id')
    if (
        not isinstance(data, dict)
        or data.get('ok') is not True
        or data.get('status') not in {'reserved', 'completed', 'unknown', 'refunded'}
        or type(key) is not str
        or not 16 <= len(key) <= 80
        or (expected_key is not None and key != expected_key)
        or type(data.get('cost')) not in (int, float)
        or data['cost'] < 0
        or type(data.get('balance')) not in (int, float)
        or data['balance'] < 0
    ):
        raise RuntimeError('VK native operation response invalid')
    return data


async def reserve_native_vk_operation(vk_user_id: int, payload: dict) -> dict:
    return await _native_vk_operation_call(
        vk_user_id, action='reserve', payload=payload,
    )


async def settle_native_vk_operation(vk_user_id: int, payload: dict) -> dict:
    return await _native_vk_operation_call(
        vk_user_id, action='settle', payload=payload,
    )


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


class NativeVkTaskNotFound(LookupError):
    """Native VK actor or owned task is absent; never fall back to TG."""


async def _native_vk_task_read(
    vk_user_id: int, *, operation: str, payload: dict,
) -> dict:
    """Exact-body HMAC to the native read-only VK SQLite worker."""
    import json

    if type(vk_user_id) is not int or not 0 < vk_user_id < 2**63:
        raise ValueError('Invalid verified VK identity')
    if operation not in {'history', 'detail', 'claim'}:
        raise ValueError('Invalid native VK task operation')
    if not isinstance(payload, dict):
        raise TypeError('Invalid VK task payload')
    secret = os.getenv('INTERNAL_API_SECRET', '')
    if not secret:
        raise RuntimeError('VK internal authentication is not configured')
    domain = 'generations' if operation == 'claim' else 'tasks'
    path = f'/internal/v1/miniapp/users/{vk_user_id}/{domain}/{operation}'
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    if len(raw) > 32768:
        raise ValueError('VK task payload is too large')
    stamp = str(int(time.time()))
    sig = hmac.new(
        secret.encode(),
        b'\n'.join([stamp.encode(), b'POST', path.encode(), raw]),
        hashlib.sha256,
    ).hexdigest()
    timeout = aiohttp.ClientTimeout(total=6, connect=2)
    async with (
        aiohttp.ClientSession(timeout=timeout) as client,
        client.post(_internal_origin() + path, data=raw, headers={
            'Content-Type': 'application/json',
            'X-Internal-Timestamp': stamp,
            'X-Internal-Signature': sig,
        }, allow_redirects=False) as result,
    ):
        if result.status == 404:
            raise NativeVkTaskNotFound('VK account or task not found')
        if result.status == 403:
            raise PermissionError('VK native account is blocked')
        if result.status != 200:
            raise RuntimeError('VK native task service unavailable')
        data = await result.json()
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise RuntimeError('VK native task response invalid')
    return data


async def fetch_native_vk_task_history(
    vk_user_id: int, *, cursor: int | None = None,
) -> dict:
    if cursor is not None and (type(cursor) is not int or not 0 < cursor < 2**63):
        raise ValueError('Invalid VK history cursor')
    data = await _native_vk_task_read(
        vk_user_id, operation='history',
        payload={'cursor': cursor} if cursor is not None else {},
    )
    tasks = data.get('tasks')
    next_cursor = data.get('next_cursor')
    if (not isinstance(tasks, list) or len(tasks) > 8
        or type(data.get('cursor_reset')) is not bool
        or (next_cursor is not None
            and (type(next_cursor) is not int or not 0 < next_cursor < 2**63))
        or (next_cursor is not None
            and (not tasks or tasks[-1].get('task_id') != next_cursor))):
        raise RuntimeError('VK native history response invalid')
    return data


async def fetch_native_vk_task_detail(vk_user_id: int, task_id: int) -> dict:
    if type(task_id) is not int or not 0 < task_id < 2**63:
        raise ValueError('Invalid VK task ID')
    data = await _native_vk_task_read(
        vk_user_id, operation='detail', payload={'task_id': task_id},
    )
    row = data.get('task')
    if not isinstance(row, dict) or row.get('task_id') != task_id:
        raise RuntimeError('VK native detail response invalid')
    return data


async def fetch_native_vk_generation_claim(vk_user_id: int, client_request_id: str) -> dict:
    """Resolve an ambiguous native charge by its exact owner/idempotency key.

    The HMAC service is read-only; neither this function nor the public BFF
    may substitute Telegram ownership or expose hidden provider recipes.
    """
    if (not isinstance(client_request_id, str)
        or not 16 <= len(client_request_id) <= 80
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
               for ch in client_request_id)):
        raise ValueError('Invalid VK generation request key')
    data = await _native_vk_task_read(
        vk_user_id, operation='claim',
        payload={'client_request_id': client_request_id},
    )
    if type(data.get('found')) is not bool:
        raise RuntimeError('Invalid VK generation claim state')
    if data['found'] is False:
        return {'ok': True, 'found': False}
    task_id = data.get('task_id')
    cost = data.get('cost')
    status = data.get('status')
    task_type = data.get('task_type')
    if (type(task_id) is not int or not 0 < task_id < 2**63
        or type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
        or task_type not in {'photo', 'video'}
        or not isinstance(status, str) or not 1 <= len(status) <= 32
        or not all(ch.isascii() and (ch.isalnum() or ch == '_') for ch in status)):
        raise RuntimeError('Invalid VK generation claim payload')
    return {
        'ok': True, 'found': True, 'task_id': task_id,
        'task_type': task_type, 'status': status, 'cost': cost,
    }


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
