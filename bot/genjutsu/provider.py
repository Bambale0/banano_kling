"""Higgsfield REST boundary. A submission is attempted exactly once by this client.

Transport failures are not proof of provider rejection. Callers must retain the
attempt and reconcile uncertain outcomes rather than retrying a generation POST.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

import aiohttp

from .contract import CATALOG


class ProviderFailure(Exception):
    def __init__(self, code: str, *, uncertain: bool = False, http_status: int | None = None):
        self.code = code
        self.uncertain = uncertain
        self.http_status = http_status
        super().__init__(code)


def request_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise ProviderFailure('provider_invalid_request_id')
    return value


def https_url(value) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ProviderFailure('provider_invalid_media_url')
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('invalid URL')
        if parsed.port not in (None, 443):
            raise ValueError('invalid port')
    except ValueError as exc:
        raise ProviderFailure('provider_invalid_media_url') from exc
    return value


class Higgsfield:
    def __init__(self, credential: str, base_url: str = 'https://api.higgsfield.ai',
                 *, allow_insecure_for_tests: bool = False):
        self.credential = credential.strip()
        self.base_url = base_url.rstrip('/')
        self.allow_insecure_for_tests = allow_insecure_for_tests
        parsed = urlsplit(self.base_url)
        schemes = {'http', 'https'} if allow_insecure_for_tests else {'https'}
        if (parsed.scheme not in schemes or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError('Invalid Higgsfield API base URL')

    @property
    def configured(self) -> bool:
        return bool(self.credential)

    def _provider_url(self, value: str) -> str:
        if not isinstance(value, str) or len(value) > 8192:
            raise ProviderFailure('provider_invalid_url')
        parsed = urlsplit(value)
        base = urlsplit(self.base_url)
        base_port = base.port or (443 if base.scheme == 'https' else 80)
        parsed_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        allowed_origins = {(base.scheme, base.hostname, base_port)}
        # Higgsfield's generation endpoint is api.higgsfield.ai, while current
        # acceptance receipts return authenticated status/cancel URLs on
        # platform.higgsfield.ai. Keep this fail-closed to the provider-owned
        # production origin instead of accepting arbitrary response URLs.
        if (
            base.scheme == 'https'
            and base.hostname == 'api.higgsfield.ai'
            and base_port == 443
        ):
            allowed_origins.add(('https', 'platform.higgsfield.ai', 443))
        if (
            (parsed.scheme, parsed.hostname, parsed_port) not in allowed_origins
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.startswith('/')
        ):
            raise ProviderFailure('provider_invalid_url')
        return value

    def _request_handle_url(self, external_id: str, action: str) -> str:
        rid = request_id(external_id)
        if action not in {'status', 'cancel'}:
            raise ProviderFailure('provider_invalid_url')
        base = urlsplit(self.base_url)
        base_port = base.port or (443 if base.scheme == 'https' else 80)
        if base.scheme == 'https' and base.hostname == 'api.higgsfield.ai' and base_port == 443:
            return f'https://platform.higgsfield.ai/requests/{rid}/{action}'
        return f'requests/{rid}/{action}'

    async def _request(self, method: str, path: str, *, timeout: int,
                       payload=None, params=None, submission: bool = False,
                       extra_headers: dict[str, str] | None = None) -> tuple[dict, str | None]:
        if not self.configured:
            raise ProviderFailure('provider_not_configured')
        url = self._provider_url(path) if path.startswith(('http://', 'https://')) else self.base_url + '/' + path
        headers = {'Authorization': 'Key ' + self.credential, 'Accept': 'application/json'}
        headers.update(extra_headers or {})
        try:
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session,
                session.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                    allow_redirects=False,
                ) as response,
            ):
                    status = response.status
                    # Never echo provider response text: it can contain input URLs or secrets.
                    if not 200 <= status < 300:
                        uncertain = submission and (status >= 500 or 300 <= status < 400 or status == 408)
                        raise ProviderFailure(f'provider_http_{status}', uncertain=uncertain, http_status=status)
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        raw.extend(chunk)
                        if len(raw) > 1048576:
                            raise ProviderFailure('provider_response_too_large', uncertain=submission)
                    correlation_id = response.headers.get('X-Correlation-ID')
                    if correlation_id is not None and len(correlation_id) > 500:
                        correlation_id = correlation_id[:500]
                    if status == 204:
                        return {}, correlation_id
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeError) as exc:
                        raise ProviderFailure('provider_invalid_json', uncertain=submission) from exc
                    if not isinstance(data, dict):
                        raise ProviderFailure('provider_invalid_response', uncertain=submission)
                    return data, correlation_id
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise ProviderFailure('provider_transport_error', uncertain=submission) from exc

    async def submit(self, model_path: str, payload: dict, *, timeout: int,
                     idempotency_key: str, webhook: str | None = None) -> dict:
        if model_path not in {caps['provider_path'] for caps in CATALOG.values()}:
            raise ProviderFailure('provider_unsupported_model')
        if webhook:
            https_url(webhook)
        if (
            not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key) <= 255
            or any(not 0x21 <= ord(char) <= 0x7E for char in idempotency_key)
        ):
            raise ProviderFailure('provider_invalid_idempotency_key')
        data, correlation_id = await self._request(
            'POST',
            model_path,
            timeout=timeout,
            payload=payload,
            params={'hf_webhook': webhook} if webhook else None,
            submission=True,
            extra_headers={'Idempotency-Key': idempotency_key},
        )
        try:
            return {
                'request_id': request_id(data.get('request_id')),
                'status_url': self._provider_url(data.get('status_url')),
                'cancel_url': self._provider_url(data.get('cancel_url')),
                'correlation_id': correlation_id,
            }
        except ProviderFailure as exc:
            raise ProviderFailure('provider_submit_missing_id', uncertain=True) from exc

    async def status(self, external_id: str, *, timeout: int, status_url: str | None = None) -> dict:
        rid = request_id(external_id)
        data, correlation_id = await self._request(
            'GET', status_url or self._request_handle_url(rid, 'status'), timeout=timeout
        )
        state = data.get('status')
        if state not in {'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'}:
            raise ProviderFailure('provider_unknown_status')
        result = {'status': state, 'correlation_id': correlation_id}
        if state == 'completed':
            video = data.get('video')
            if not isinstance(video, dict):
                raise ProviderFailure('provider_missing_video')
            result['result_url'] = https_url(video.get('url'))
        return result

    async def cancel(self, external_id: str, *, timeout: int, cancel_url: str | None = None) -> None:
        # An acknowledgement is not a terminal state. Always follow with status().
        rid = request_id(external_id)
        await self._request(
            'POST', cancel_url or self._request_handle_url(rid, 'cancel'), timeout=timeout
        )

    async def presets(self, *, timeout: int) -> list[dict]:
        path = 'models/' + CATALOG['restyle']['provider_path'] + '/presets'
        data, _ = await self._request('GET', path, timeout=timeout)
        if data.get('model') != CATALOG['restyle']['provider_path'] or not isinstance(data.get('items'), list):
            raise ProviderFailure('provider_invalid_presets')
        items, seen = [], set()
        for value in data['items']:
            try:
                pid = str(UUID(value['id']))
                name = value['name']
                preview = https_url(value['preview_url'])
                if not isinstance(name, str) or not 1 <= len(name) <= 500 or pid in seen:
                    raise ValueError('invalid preset')
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ProviderFailure('provider_invalid_presets') from exc
            seen.add(pid)
            items.append({'id': pid, 'name': name, 'preview_url': preview})
        return items
