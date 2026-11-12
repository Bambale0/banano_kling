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
    'bootstrap', 'photo', 'video', 'trends', 'feed',
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
    native_task_paths = frozenset({
        base + 'task-history', base + 'task-detail',
    })

    @web.middleware
    async def middleware(request: web.Request, handler):
        # Never allow a VK bearer in the URL, including while parity is off.
        # This must precede the feature-flag no-op: reverse proxies, logs and
        # browser history can otherwise persist a valid signed session.
        if request.path.startswith(base) and any(
            value.startswith('vk_session:')
            for key, value in request.query.items()
            if key == 'init_data' and isinstance(value, str)
        ):
            return web.json_response({
                'ok': False, 'error': 'VK session must not be sent in the URL',
            }, status=400)
        # Existing TG routes remain untouched until an explicit native VK
        # domain flag is enabled. Partial task-history never unlocks the full
        # VK shell; it only adds an owner-scoped adapter to the SAME routes.
        full_enabled = os.getenv('VK_FULL_APP_PARITY_ENABLED') == '1'
        native_tasks_enabled = (
            os.getenv('VK_NATIVE_TASKS_ENABLED') == '1'
            and request.path in native_task_paths
        )
        if not full_enabled and not native_tasks_enabled:
            # A disabled VK-native task adapter must not fall through to
            # legacy Telegram history/detail. A linked VK actor still owns
            # a separate native SQLite task ledger.
            if request.path in native_task_paths:
                supplied = request.headers.get('X-Telegram-Init-Data', '')
                if not supplied and request.content_type == 'application/json':
                    if (request.content_length is not None
                        and request.content_length > MAX_GATEWAY_JSON_BYTES):
                        return await handler(request)
                    try:
                        body = await request.json()
                    except (ValueError, TypeError):
                        body = None
                    if isinstance(body, dict):
                        supplied = body.get('init_data', '')
                if isinstance(supplied, str) and supplied.startswith('vk_session:'):
                    return web.json_response({
                        'ok': False, 'error': 'VK native task history unavailable',
                    }, status=503, headers={'Cache-Control': 'no-store'})
            return await handler(request)
        if (request.method == 'OPTIONS'
            or not request.path.startswith(base)
            or request.path.startswith(base + 'account-preview/')):
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

        # A VK header and a different body credential is an ambiguous actor.
        # Do not pass mixed credentials to native adapters or legacy handlers.
        if parsed and 'init_data' in parsed and parsed['init_data'] != init_data:
            return web.json_response({
                'ok': False, 'error': 'Conflicting session credentials',
            }, status=400)

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
        # A Telegram link is never authorization to use Telegram's legacy
        # wallet or generation routes. VK requests fail closed until the
        # native adapter is ready, regardless of optional account links.
        if adapter is None and native_tasks_enabled:
            task_adapter = request.app.get('vk_native_tasks_adapter')
            if (getattr(task_adapter, 'ready_operations', None) == frozenset({'tasks'})
                and callable(getattr(task_adapter, 'handle', None))):
                adapter = task_adapter
        if adapter is None:
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
