"""Public shared-account routes plus administrator-only control routes."""
from __future__ import annotations

import json
import logging
import os

from aiohttp import web

from bot.config import config

from .auth import external_id, verify_telegram, verify_vk
from .commercial import CommercialValidation
from .commercial_store import CommercialStore
from .errors import AuthenticationError, PreviewConflict
from .links import LinkExpired, LinkService
from .policy import VKDeliveryConfigurationError, load_policy, save_policy
from .store import (
    create_session,
    get_session,
    linked_platforms,
    linked_telegram_id,
    revoke_session,
)
from .wallet import InsufficientFunds, WalletService

logger = logging.getLogger(__name__)


def response(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


async def _body(request: web.Request) -> dict:
    if request.content_length and request.content_length > 32768:
        raise ValueError('Request is too large')
    try:
        raw = await request.read()
        if len(raw) > 32768:
            raise ValueError('Request is too large')
        data = json.loads(raw)
    except (ValueError, web.HTTPException) as exc:
        raise ValueError('Invalid JSON request') from exc
    if not isinstance(data, dict):
        raise TypeError('Expected an object')
    return data


async def _administrator(request: web.Request, body: dict) -> int:
    policy = await load_policy()
    identity = verify_telegram(
        request.headers.get('X-Telegram-Init-Data') or body.get('init_data', ''),
        config.BOT_TOKEN, max_age=policy.launch_max_age_seconds,
    )
    if not config.is_admin(identity.external_id):
        raise PermissionError('Administrator access required')
    return identity.external_id


async def settings(request: web.Request) -> web.Response:
    body = await _body(request) if request.method == 'PUT' else {}
    actor_id = await _administrator(request, body)
    if request.method == 'PUT':
        policy = await save_policy(actor_id, body.get('settings'), body.get('expected_revision'))
        logger.info('shared_account_settings_updated actor_telegram_id=%s revision=%s', actor_id, policy.revision)
    else:
        policy = await load_policy()
    return response({'ok': True, 'settings': policy.payload()})


async def session(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    body = await _body(request)
    platform = body.get('platform')
    if platform == 'telegram':
        identity = verify_telegram(body.get('launch_data', ''), config.BOT_TOKEN, max_age=policy.launch_max_age_seconds)
    elif platform == 'vk':
        identity = verify_vk(body.get('launch_data', ''), policy.vk_app_id, os.getenv('VK_MINI_APP_SECRET', ''), max_age=policy.launch_max_age_seconds)
    else:
        raise ValueError('Unknown platform')
    if not policy.allows_public(identity):
        raise PermissionError('Account access unavailable')
    account, token, expires = await create_session(identity, policy.session_ttl_seconds, policy.revision)
    logger.info('shared_account_session_created account_id=%s platform=%s', account.id, identity.platform)
    return response({'ok': True, 'account': account.payload(), 'session_token': token, 'expires_at': expires})


def _bearer(request: web.Request) -> str:
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise AuthenticationError('Session required')
    return header[7:]


async def profile(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if not policy.allows_public(account.identity):
        raise PermissionError('Account access unavailable')
    return response({'ok': True, 'account': account.payload(), 'preview': {
        'revision': policy.revision, 'vk_app_id': policy.vk_app_id,
        'telegram_bot_username': os.getenv('TELEGRAM_BOT_USERNAME', '').strip().lstrip('@'),
        # A verified VK identity may return to the existing native community
        # bot without claiming access to a second or migrated money source.
        'vk_community_id': policy.vk_community_id if account.identity.platform == 'vk' else None,
        'telegram_linked': await linked_telegram_id(account.id) is not None,
        'linked_platforms': await linked_platforms(account.id),
        'link_ttl_seconds': policy.link_ttl_seconds,
    }})


async def logout(request: web.Request) -> web.Response:
    # Revoking one's own opaque token remains safe after account merging or
    # preview shutdown. It grants no access and is intentionally idempotent.
    await revoke_session(_bearer(request))
    return response({'ok': True})


async def wallet(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if not policy.allows_admin(account.identity):
        raise PermissionError('Administrator access required')
    # No client field can select the live wallet or another account.
    service = WalletService('sandbox')
    if request.path.endswith('/wallet/reconcile'):
        report = await service.reconcile(account.id)
        logger.info('shared_wallet_reconciliation account_id=%s scope=sandbox consistent=%s issues=%s',
                    account.id, report['consistent'], ','.join(report['issues']))
        return response({'ok': True, **report})
    receipt = None
    if request.method == 'POST':
        body = await _body(request)
        receipt = await service.apply(account.id, body.get('action'), body.get('amount'),
                                      body.get('idempotency_key'), body.get('reference_key', ''))
    return response({'ok': True, **(await service.snapshot(account.id)), 'receipt': receipt})


async def links(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if not policy.allows_public(account.identity):
        raise PermissionError('Account access unavailable')
    service = LinkService(policy)
    body = await _body(request) if request.method == 'POST' else {}
    link_id = request.match_info.get('link_id')
    if request.path.endswith('/links/preview'):
        result = await service.preview_token(account, body.get('token'))
    elif request.path.endswith('/links/accept'):
        confirm = body.get('confirm', False)
        if type(confirm) is not bool:
            raise ValueError('Invalid recipient confirmation')
        result = await service.accept_token(account, body.get('token'), confirm=confirm)
    elif link_id is None:
        confirm_source = body.get('confirm_source', False)
        if type(confirm_source) is not bool:
            raise ValueError('Invalid source confirmation')
        result = await service.create(account, body.get('target_platform'), confirm_source=confirm_source)
    else:
        result = await service.operate(account, link_id, request.match_info.get('action', 'get'), body)
    return response({'ok': True, 'link': result})


async def commerce(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if not policy.allows_admin(account.identity):
        raise PermissionError('Administrator access required')
    service = CommercialStore()
    if request.path.endswith('/commerce/quote'):
        body = await _body(request)
        if set(body) - {'price_key', 'quantity'}:
            raise CommercialValidation('Тариф и платформа определяются сервером.')
        quote = await service.quote(account, body.get('price_key'), body.get('quantity', 1))
        logger.info('shared_commerce_quote_created quote_id=%s account_id=%s platform=%s catalog_revision=%s',
                    quote['id'], account.id, account.identity.platform, quote['catalog_revision'])
        return response({'ok': True, 'quote': quote})
    if request.match_info.get('quote_id'):
        return response({'ok': True, 'quote': await service.get_quote(account.id, request.match_info['quote_id'])})
    if request.path.endswith('/commerce/accounts'):
        platform = request.query.get('platform')
        if platform not in {'telegram', 'vk'}:
            raise CommercialValidation('Выберите платформу аккаунта.')
        try:
            target_external_id = external_id(request.query.get('external_id'))
        except AuthenticationError as exc:
            raise CommercialValidation('Укажите корректный ID пользователя.') from exc
        target = await service.find_account(platform, target_external_id)
        return response({'ok': True, 'target': target})
    if request.match_info.get('account_id'):
        target_id = request.match_info['account_id']
        if request.method == 'PUT':
            body = await _body(request)
            target = await service.save_terms(account.identity, target_id, body.get('settings'), body.get('expected_revision'))
            logger.info('shared_commerce_terms_updated account_id=%s actor_platform=%s actor_external_id=%s revision=%s',
                        target['account_id'], account.identity.platform, account.identity.external_id, target['settings']['revision'])
        else:
            target = await service.terms(target_id)
        return response({'ok': True, 'target': target})
    if request.method == 'PUT':
        body = await _body(request)
        catalog = await service.save_catalog(account.identity, body.get('settings'), body.get('expected_revision'))
        logger.info('shared_commerce_catalog_updated actor_platform=%s actor_external_id=%s revision=%s',
                    account.identity.platform, account.identity.external_id, catalog.revision)
    else:
        catalog = await service.catalog()
    return response({'ok': True, 'catalog': catalog.payload()})


def _guard(handler):
    async def guarded(request):
        try:
            return await handler(request)
        except AuthenticationError as exc:
            logger.info('shared_account_authentication_rejected path=%s reason=%s', request.path, str(exc))
            return response({'ok': False, 'error': str(exc)}, 401)
        except PermissionError as exc:
            return response({'ok': False, 'error': str(exc)}, 403)
        except PreviewConflict as exc:
            return response({'ok': False, 'error': str(exc)}, 409)
        except LinkExpired:
            return response({'ok': False, 'error': 'Invitation expired or cancelled'}, 410)
        except InsufficientFunds:
            return response({'ok': False, 'error': 'Insufficient available balance'}, 402)
        except CommercialValidation as exc:
            return response({'ok': False, 'error': str(exc), 'error_code': 'commerce_invalid'}, 400)
        except VKDeliveryConfigurationError:
            return response({'ok': False, 'error_code': 'vk_sender_unconfigured'}, 400)
        except (ValueError, TypeError):
            return response({'ok': False, 'error': 'Invalid request'}, 400)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary returns a stable, redacted failure.
            # Never log a request body, launch credentials, or session token.
            logger.error('shared_account_preview_failed path=%s error_type=%s', request.path, type(exc).__name__)
            return response({'ok': False, 'error': 'Preview temporarily unavailable'}, 503)
    return guarded


def setup_shared_account_routes(app: web.Application, miniapp_root: str) -> None:
    from .vk_delivery import vk_delivery

    root = miniapp_root + '/api/account-preview'
    app.router.add_get(root + '/vk-deliveries/{task_id}', _guard(vk_delivery))
    # Auth and bounded JSON belong to this route, not the legacy body guard.
    app.router.add_route('POST', root + '/vk-deliveries/{task_id}', _guard(vk_delivery))
    app.router.add_get(root + '/settings', _guard(settings))
    app.router.add_put(root + '/settings', _guard(settings))
    app.router.add_post(root + '/session', _guard(session))
    app.router.add_get(root + '/me', _guard(profile))
    app.router.add_post(root + '/logout', _guard(logout))
    app.router.add_get(root + '/wallet', _guard(wallet))
    app.router.add_post(root + '/wallet', _guard(wallet))
    app.router.add_get(root + '/wallet/reconcile', _guard(wallet))
    app.router.add_post(root + '/links', _guard(links))
    app.router.add_post(root + '/links/accept', _guard(links))
    app.router.add_post(root + '/links/preview', _guard(links))
    app.router.add_get(root + '/links/{link_id}', _guard(links))
    app.router.add_post(root + '/links/{link_id}/{action:accept|confirm|cancel}', _guard(links))
    app.router.add_get(root + '/commerce', _guard(commerce))
    app.router.add_put(root + '/commerce', _guard(commerce))
    app.router.add_get(root + '/commerce/accounts', _guard(commerce))
    app.router.add_get(root + '/commerce/accounts/{account_id}', _guard(commerce))
    app.router.add_put(root + '/commerce/accounts/{account_id}', _guard(commerce))
    app.router.add_post(root + '/commerce/quote', _guard(commerce))
    app.router.add_get(root + '/commerce/quotes/{quote_id}', _guard(commerce))
