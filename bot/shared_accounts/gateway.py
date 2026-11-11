"""Transition gateway for ONE shared Mini App shell across VK and Telegram.

The existing Telegram Mini App API is legacy-ID based. A signed VK session
must only enter that API through the native VK platform adapter, never by
inventing a Telegram user. Disabled by default; no changes to production
routing until full domain parity is implemented.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from aiohttp import web

from .actor import PlatformActor, resolve_platform_actor
from .errors import AuthenticationError

logger = logging.getLogger(__name__)

VK_FULL_APP_OPERATIONS = frozenset({
    'bootstrap', 'photo', 'video', 'motion', 'trends', 'feed',
    'services', 'profile', 'payments', 'referrals', 'tasks',
})
MAX_GATEWAY_JSON_BYTES = 128 * 1024
FORBIDDEN_ACTOR_CLAIMS = frozenset({
    'telegram_id', 'vk_user_id', 'shared_account_id',
    'owner_key', 'user_id', 'is_admin', 'wallet_platform',
})


def full_vk_adapter(app: web.Application) -> Any | None:
    """Return a *complete* callable adapter, never a flag-only declaration."""
    if os.getenv('VK_FULL_APP_PARITY_ENABLED') != '1':
        return None
    adapter = app.get('vk_full_app_adapter')
    ready = getattr(adapter, 'ready_operations', None)
    if (type(ready) is not frozenset
        or not VK_FULL_APP_OPERATIONS.issubset(ready)
        or not callable(getattr(adapter, 'handle', None))):
        return None
    return adapter


def vk_miniapp_gateway(miniapp_root: str = '/mini-app') -> Callable:
    """Intercept signed VK requests for the *same* /mini-app/api endpoints.

    Only after all domains have real native VK handlers registered. Without
    this gate, the existing legacy Telegram routes remain unchanged.
    """
    base = miniapp_root.rstrip('/') + '/api/'

    @web.middleware
    async def middleware(request: web.Request, handler):
        # Every existing Telegram operation is byte-for-byte untouched until
        # the full VK adapter rollout is explicitly enabled.
        if os.getenv('VK_FULL_APP_PARITY_ENABLED') != '1':
            return await handler(request)
        if (request.method == 'OPTIONS'
            or not request.path.startswith(base)
            or request.path.startswith(base + 'account-preview/')
            or os.getenv('VK_FULL_APP_PARITY_ENABLED') != '1'):
            # In production, the gateway is an exact no-op: do not eagerly
            # read JSON bodies or alter Telegram transport behaviour.
            return await handler(request)

        init_data = request.headers.get('X-Telegram-Init-Data', '')
        parsed: dict | None = None
        if not init_data and request.content_type == 'application/json':
            if request.content_length is not None and request.content_length > MAX_GATEWAY_JSON_BYTES:
                # Do not break existing TG requests; the legacy handler
                # retains its own bounds and validation.
                return await handler(request)
            try:
                value = await request.json()
            except (ValueError, TypeError):
                value = None
            if isinstance(value, dict):
                parsed = value
                init_data = value.get('init_data', '')
        elif not init_data:
            init_data = request.query.get('init_data', '')

        if not isinstance(init_data, str) or not init_data.startswith('vk_session:'):
            return await handler(request)

        # When the signed init data is provided in an HTTP header, parse a
        # bounded JSON body as well. The actor is NEVER taken from that body.
        if parsed is None and request.content_type == 'application/json':
            if request.content_length is not None and request.content_length > MAX_GATEWAY_JSON_BYTES:
                return web.json_response({'ok': False, 'error': 'Request too large'}, status=413)
            try:
                value = await request.json()
            except (ValueError, TypeError):
                return web.json_response({'ok': False, 'error': 'Invalid JSON'}, status=400)
            if isinstance(value, dict):
                parsed = value

        if parsed and FORBIDDEN_ACTOR_CLAIMS.intersection(parsed):
            return web.json_response({'ok': False, 'error': 'Invalid account scope'}, status=400)

        token = init_data[len('vk_session:'):]
        try:
            actor: PlatformActor = await resolve_platform_actor(
                token, expected_platform='vk',
            )
        except AuthenticationError:
            return web.json_response({'ok': False, 'error': 'Invalid session'}, status=401)
        except PermissionError:
            return web.json_response({'ok': False, 'error': 'Access denied'}, status=403)
        except Exception as error:  # noqa: BLE001 - redact credential-bearing gateway failures
            logger.error('vk_shared_gateway_auth_error type=%s', type(error).__name__)
            return web.json_response({'ok': False, 'error': 'Account unavailable'}, status=503)

        adapter = full_vk_adapter(request.app)
        if adapter is None:
            # Linked accounts have a legacy working studio. An operator
            # accidentally enabling an incomplete adapter cannot break it.
            if actor.linked_telegram_id is not None:
                return await handler(request)
            return web.json_response({
                'ok': False, 'error': 'VK studio integration unavailable',
            }, status=503)

        request['platform_actor'] = actor
        try:
            result = await adapter.handle(request, actor=actor)
        except (AuthenticationError, PermissionError):
            return web.json_response({'ok': False, 'error': 'Access denied'}, status=403)
        except ValueError:
            return web.json_response({'ok': False, 'error': 'Invalid request'}, status=400)
        except Exception as error:  # noqa: BLE001 - redact provider and request state
            logger.error('vk_shared_gateway_operation_failed type=%s', type(error).__name__)
            return web.json_response({'ok': False, 'error': 'Service temporarily unavailable'}, status=503)
        if not isinstance(result, web.StreamResponse):
            return web.json_response({'ok': False, 'error': 'Invalid service response'}, status=503)
        result.headers['Cache-Control'] = 'no-store'
        return result

    return middleware
