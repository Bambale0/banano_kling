"""Public shared-account routes plus administrator-only control routes."""
from __future__ import annotations

import json
import logging
import os

from aiohttp import web

from bot.config import config

from .actor import resolve_platform_actor
from .auth import external_id, verify_telegram, verify_vk
from .commercial import CommercialValidation
from .commercial_store import CommercialStore
from .errors import AuthenticationError, PreviewConflict
from .gateway import full_vk_adapter
from .links import LinkExpired, LinkService
from .policy import VKDeliveryConfigurationError, load_policy, save_policy
from .store import (
    create_session,
    get_session,
    revoke_session,
)
from .task_view import serialize_native_vk_tasks
from .vk_image_refs import MAX_UPLOAD_BYTES, save_vk_image, verified_image_urls
from .vk_native import (
    fetch_native_vk_commerce,
    fetch_native_vk_models,
    fetch_native_vk_state,
    submit_native_vk_image,
    submit_native_vk_video,
)
from .vk_trend_contract import NATIVE_IMAGE_MODELS, supports_native_vk_image_trend
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


async def vk_login(request: web.Request) -> web.Response:
    """Enter the VK-owned login flow; never accept an actor ID from the URL.

    VK will prompt for sign-in when needed and then supply fresh launch params.
    The actual Mini App session still requires signature and timestamp checks.
    """
    policy = await load_policy()
    if not policy.enabled or not policy.vk_app_id:
        return response({'ok': False, 'error': 'VK Mini App is unavailable'}, 404)
    # Fixed trusted origin, app ID from server-owned policy only. No next
    # parameter, caller-supplied app ID or auth credentials in the redirect.
    # The VK app may be installed in a community. Returning to a bare
    # app<ID> after an expired launch drops that context and can reopen the
    # developer's personal app instead of the NEUROMIX bot workspace.
    launch_url = f'https://vk.com/app{policy.vk_app_id}'
    if policy.vk_community_id is not None:
        launch_url += f'_-{policy.vk_community_id}'
    return web.Response(
        status=303,
        headers={
            'Location': launch_url,
            'Cache-Control': 'no-store',
            'Referrer-Policy': 'no-referrer',
        },
    )


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


# Readiness belongs to the server, not to the browser's platform flag.
# Every domain operation must have a native VK actor/storage/payment adapter
# before the shared Telegram UI can be safely used by a VK-only identity.
def _vk_full_app_ready(request: web.Request, *, platform: str, telegram_linked: bool) -> bool:
    if platform != 'vk':
        return True
    # Telegram linking is never proof of native VK domain readiness.
    # The shared shell may mount only when every native VK operation is
    # registered, regardless of whether this actor linked Telegram.
    return full_vk_adapter(request.app) is not None


async def profile(request: web.Request) -> web.Response:
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    actor = await resolve_platform_actor(_bearer(request))
    is_linked = actor.linked_telegram_id is not None
    return response({'ok': True, 'account': actor.payload(), 'preview': {
        'revision': policy.revision, 'vk_app_id': policy.vk_app_id,
        'full_app_ready': _vk_full_app_ready(
            request, platform=actor.platform, telegram_linked=is_linked,
        ),
        'telegram_bot_username': os.getenv('TELEGRAM_BOT_USERNAME', '').strip().lstrip('@'),
        'vk_community_id': policy.vk_community_id if actor.platform == 'vk' else None,
        'telegram_linked': is_linked,
        'linked_platforms': list(actor.linked_platforms),
        'link_ttl_seconds': policy.link_ttl_seconds,
    }})


def _vk_public_trend_card(card: dict, *, vk_app_id: int | None = None,
                          vk_community_id: int | None = None) -> dict:
    from bot.miniapp_links import prompt_link
    from bot.trend_visibility import public_trend_settings

    settings = card.get('generation_settings') or {}
    safe = public_trend_settings(card)
    return {
        'id': int(card['id']),
        'share_link': (
            prompt_link(None, card['id'], platform='vk', vk_app_id=vk_app_id, vk_community_id=vk_community_id)
            if vk_app_id else None
        ),
        'title': str(card.get('title') or ''),
        'description': str(card.get('description') or ''),
        'preview_url': card.get('preview_url'),
        'preview_poster_url': card.get('preview_poster_url'),
        'generation_type': 'video' if settings.get('kind') == 'video' else 'image',
        'can_repeat_in_app': (
            os.getenv('VK_MINIAPP_WRITES_ENABLED') == '1'
            and card.get('vk_native_image_repeat_supported') is True
        ),
        'user_fields': safe.get('user_fields', []),
    }


async def vk_native_state(request: web.Request) -> web.Response:
    """Verified VK session owns its native wallet, regardless of Telegram."""
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    actor = await resolve_platform_actor(_bearer(request), expected_platform='vk')
    data = await fetch_native_vk_state(actor.external_id)
    # The same history-card DTO used by the common Telegram Mini App.
    # Keep the legacy native rows for backward compatibility until every
    # detail/repeat route accepts platform-namespaced task identifiers.
    common_tasks = serialize_native_vk_tasks(data['tasks'], strict=False)
    return response({'ok': True, **data, 'recent_tasks': common_tasks})


async def vk_native_models(request: web.Request) -> web.Response:
    """Expose native worker capabilities to the signed VK actor only."""
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok':False,'error':'Preview unavailable'},404)
    actor=await resolve_platform_actor(_bearer(request),expected_platform='vk')
    return response(await fetch_native_vk_models(actor.external_id))


async def vk_native_commerce(request: web.Request) -> web.Response:
    """Verified VK session reads ONLY its actual VK payment/partner ledger."""
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    actor = await resolve_platform_actor(_bearer(request), expected_platform='vk')
    return response(await fetch_native_vk_commerce(actor.external_id))


async def _vk_writer_actor(request: web.Request) -> int:
    actor = await resolve_platform_actor(_bearer(request), expected_platform='vk')
    # Compatibility until the full common VK shell routes ALL financial
    # operations to the VK-native wallet. Never silently mix VK/TG funds.
    if 'telegram' in actor.linked_platforms:
        raise PermissionError('Linked accounts must use the common studio')
    return actor.external_id


async def vk_image_upload(request: web.Request) -> web.Response:
    actor_id = await _vk_writer_actor(request)
    if os.getenv('VK_MINIAPP_WRITES_ENABLED') != '1':
        return response({'ok': False, 'error': 'VK upload unavailable'}, 404)
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES + 64 * 1024:
        return response({'ok': False, 'error': 'VK image is too large'}, 413)
    if request.content_type != 'multipart/form-data':
        raise ValueError('Expected an image upload')
    reader = await request.multipart()
    part = await reader.next()
    if part is None or part.name != 'image':
        raise ValueError('Expected an image')
    pieces = []
    size = 0
    while True:
        chunk = await part.read_chunk(64 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            return response({'ok': False, 'error': 'VK image is too large'}, 413)
        pieces.append(chunk)
    if await reader.next() is not None:
        raise ValueError('Expected one image')
    image_url = await save_vk_image(actor_id, b''.join(pieces))
    return response({'ok': True, 'url': image_url})


async def vk_native_image(request: web.Request) -> web.Response:
    """VK authenticated account, native VK wallet; no Telegram ID or funds."""
    actor_id = await _vk_writer_actor(request)
    if os.getenv('VK_MINIAPP_WRITES_ENABLED') != '1':
        return response({'ok': False, 'error': 'VK image generation unavailable'}, 404)
    payload = await _body(request)
    if set(payload) - {'model', 'prompt', 'aspect', 'resolution', 'client_request_id', 'quote_only', 'reference_photos', 'expected_cost'}:
        raise ValueError('Invalid VK image request')
    payload['reference_photos'] = verified_image_urls(actor_id, payload.get('reference_photos', []))
    result = await submit_native_vk_image(actor_id, payload)
    return response({'ok': True, **result})


async def vk_native_video(request: web.Request) -> web.Response:
    """Quote or submit an owner-scoped VK video, independent of Telegram.

    The native VK service owns all debits/refunds and task IDs; this proxy
    cannot create or modify a Telegram balance.
    """
    actor_id = await _vk_writer_actor(request)
    if os.getenv('VK_MINIAPP_VIDEO_WRITES_ENABLED') != '1':
        return response({'ok': False, 'error': 'VK video generation unavailable'}, 404)
    payload = await _body(request)
    if set(payload) - {'model', 'prompt', 'aspect', 'duration', 'client_request_id',
                       'quote_only', 'reference_photos', 'expected_cost'}:
        raise ValueError('Invalid VK video request')
    payload['reference_photos'] = verified_image_urls(
        actor_id, payload.get('reference_photos', []),
    )
    result = await submit_native_vk_video(actor_id, payload)
    return response({'ok': True, **result})


async def vk_native_trend(request: web.Request) -> web.Response:
    """Run only approved image trends using a server-owned hidden recipe.

    Reference-dependent or video trends remain fail-closed until their
    platform-specific asset ownership and pricing contracts are implemented.
    """
    actor_id = await _vk_writer_actor(request)
    if os.getenv('VK_MINIAPP_WRITES_ENABLED') != '1':
        return response({'ok': False, 'error': 'VK repeat unavailable'}, 404)
    body = await _body(request)
    if set(body) - {'trend_id', 'user_values', 'reference_urls', 'client_request_id', 'quote_only', 'expected_cost'}:
        raise ValueError('Invalid trend request')
    from bot import trend_api, trend_catalog
    from bot.database import get_prompt_by_id
    try:
        parsed = trend_api.parse_trend_run_request(body)
        # A guessed trend ID must not bypass the same editorial visibility
        # rules as public VK deep links. Hidden-category/unlisted recipes
        # must never be executable, even when approved in the database.
        if not await trend_catalog.public_trend_by_id(parsed.trend_id):
            raise ValueError('Trend unavailable')
        prompt = await get_prompt_by_id(parsed.trend_id, approved_public_only=True)
        if not prompt:
            raise ValueError('Trend unavailable')
        if not supports_native_vk_image_trend(prompt):
            raise ValueError('Trend is not supported by VK generation')
        trusted = trend_api.trusted_trend_run(
            prompt, parsed.reference_urls, parsed.user_values,
        )
    except trend_api.TrendRunValidationError as exc:
        raise ValueError('Invalid or unavailable trend') from exc
    if (trusted.kind != 'image'
        or trusted.template_image_urls or trusted.provider_video_urls
        or trusted.provider_audio_urls
        or trusted.reference_contract
        or int(trusted.settings.get('count') or 1) != 1):
        raise ValueError('Trend requires a different generation workflow')
    model = NATIVE_IMAGE_MODELS.get(trusted.model)
    quality = str(trusted.settings.get('quality') or '2K')
    if not model or quality not in {'2K', '4K'}:
        raise ValueError('Trend is not supported by VK generation')
    key = parsed.client_request_id
    if body.get('quote_only') is not True and (not key or len(key) < 16 or len(key) > 80):
        raise ValueError('Missing idempotent request key')
    references = verified_image_urls(actor_id, list(parsed.reference_urls))
    payload = {'model': model, 'prompt': trusted.prompt, 'aspect': trusted.ratio,
               'resolution': quality, 'reference_photos': references}
    if key:
        payload['client_request_id'] = key
    if body.get('quote_only') is True:
        payload['quote_only'] = True
    else:
        payload['expected_cost'] = body.get('expected_cost')
    result = await submit_native_vk_image(actor_id, payload)
    # Never send the secret prompt or effective provider inputs to VK browser.
    return response({'ok': True, **result})


def _vk_public_feed_card(card: dict, *, vk_app_id: int,
                         vk_community_id: int | None = None) -> dict:
    """Public media and share navigation only, never the original task recipe.

    Feed publication IDs live in a separate namespace from editorial prompt
    IDs. Source prompt/reference content can only be used server-side by a
    fully authenticated, authorized platform-specific remix operation.
    """
    from bot.miniapp_links import feed_link

    if str(card.get('gen_type')) not in {'image', 'video'}:
        raise ValueError('Unsupported feed media')
    return {
        'id': int(card['id']),
        'generation_type': str(card['gen_type']),
        'model': str(card.get('model') or ''),
        'preview_url': card.get('preview_url'),
        'preview_poster_url': card.get('preview_poster_url'),
        'result_url': card.get('result_url'),
        'likes_count': int(card.get('likes_count') or 0),
        'shares_count': int(card.get('shares_count') or 0),
        'comments_count': int(card.get('comments_count') or 0),
        'aspect_ratio': str(card.get('aspect_ratio') or ''),
        'duration': card.get('duration'),
        'feed_blurred': bool(card.get('feed_blurred')),
        'media_unavailable': bool(card.get('media_unavailable')),
        'share_link': feed_link(None, int(card['id']), platform='vk', vk_app_id=vk_app_id, vk_community_id=vk_community_id),
        # Never interpret visible content or public status as authorization
        # for a paid remix. That is a separate actor/ledger/ref contract.
        'can_repeat_in_app': False,
    }


async def vk_public_discovery(request: web.Request) -> web.Response:
    # Browsing is separate from paid repeats: never invent a Telegram actor.
    policy = await load_policy()
    if not policy.enabled:
        return response({'ok': False, 'error': 'Preview unavailable'}, 404)
    account = await get_session(_bearer(request), policy.revision)
    if not policy.allows_public(account.identity) or account.identity.platform != 'vk':
        raise PermissionError('VK session required')
    view = request.query.get('view', 'trends')
    if view == 'feed_item':
        from bot import database

        raw_id = request.query.get('gen_id', '')
        if not raw_id.isascii() or not raw_id.isdecimal() or not 0 < len(raw_id) <= 16:
            raise ValueError('Invalid public feed identifier')
        gen_id = int(raw_id)
        if gen_id <= 0:
            raise ValueError('Invalid public feed identifier')
        # Do not resolve profile/private feed cards: this route is a publicly
        # shared feed link and is intentionally viewer-neutral.
        card = await database.get_feed_generation_card(
            gen_id, viewer_user_id=None, include_unavailable=True,
        )
        if not card:
            return response({'ok': False, 'error': 'Публикация не найдена'}, 404)
        return response({
            'ok': True,
            'item': _vk_public_feed_card(card, vk_app_id=policy.vk_app_id, vk_community_id=policy.vk_community_id),
        })
    if view == 'item':
        from bot import trend_catalog

        raw_id = request.query.get('trend_id', '')
        if not raw_id.isascii() or not raw_id.isdecimal() or not 0 < len(raw_id) <= 16:
            raise ValueError('Invalid trend identifier')
        trend_id = int(raw_id)
        if trend_id <= 0:
            raise ValueError('Invalid trend identifier')
        item = await trend_catalog.public_trend_by_id(trend_id)
        if item is None:
            return response({'ok': False, 'error': 'Тренд не найден'}, 404)
        return response({
            'ok': True,
            'item': _vk_public_trend_card(item, vk_app_id=policy.vk_app_id, vk_community_id=policy.vk_community_id),
            'can_generate_in_app': os.getenv('VK_MINIAPP_WRITES_ENABLED') == '1',
        })
    if view == 'trends':
        from bot import trend_catalog
        categories = await trend_catalog.list_catalog(
            is_admin=False, per_category=6, tariff='standard',
        )
        result = [
            {
                'id': item['id'],
                'title': item['title'],
                'emoji': item['emoji'],
                'total': item['total'],
                'items': [_vk_public_trend_card(card, vk_app_id=policy.vk_app_id, vk_community_id=policy.vk_community_id) for card in item['items']],
            }
            for item in categories
        ]
        return response({'ok': True, 'categories': result, 'can_generate_in_app': os.getenv('VK_MINIAPP_WRITES_ENABLED') == '1'})
    if view == 'category':
        from bot import trend_catalog
        category_id = request.query.get('category_id', '')
        if category_id != 'unassigned':
            if not category_id.isascii() or not category_id.isdecimal():
                raise ValueError('Invalid category')
            category_id = int(category_id)
        page_raw = request.query.get('page', '1')
        if not page_raw.isascii() or not page_raw.isdecimal():
            raise ValueError('Invalid page')
        page = int(page_raw)
        if page < 1 or page > 1000:
            raise ValueError('Invalid page')
        category = await trend_catalog.category_page(
            category_id, is_admin=False, page=page, limit=24, tariff='standard',
        )
        meta = category['category']
        return response({
            'ok': True,
            'category': {'id': meta['id'], 'title': meta['title'], 'emoji': meta['emoji']},
            'items': [_vk_public_trend_card(card, vk_app_id=policy.vk_app_id, vk_community_id=policy.vk_community_id) for card in category['items']],
            'has_more': bool(category['has_more']),
            'page': page,
            'can_generate_in_app': os.getenv('VK_MINIAPP_WRITES_ENABLED') == '1',
        })
    if view == 'feed':
        from bot import database
        source = request.query.get('source', 'recent')
        if source not in {'recent', 'top', 'top_day'}:
            raise ValueError('Invalid feed source')
        cards = await database.get_feed_generations(
            limit=18, source=source, viewer_user_id=None, include_unavailable=False,
        )
        items = [
            {
                'id': int(card['id']),
                'generation_type': str(card['gen_type']),
                'preview_url': card.get('preview_url'),
                'result_url': card.get('result_url'),
                'likes_count': int(card.get('likes_count') or 0),
            }
            for card in cards if card.get('gen_type') in {'image', 'video'}
        ]
        return response({'ok': True, 'items': items, 'can_generate_in_app': os.getenv('VK_MINIAPP_WRITES_ENABLED') == '1'})
    raise ValueError('Unknown discovery view')


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
            denied = response({'ok': False, 'error': str(exc)}, 401)
            # An unauthenticated multipart upload has not been consumed.
            # Never reuse its keep-alive connection: the unread boundary can
            # corrupt parsing of the next authorized request on that socket.
            if request.path.endswith('/vk-image-upload'):
                denied.force_close()
            return denied
        except PermissionError as exc:
            denied = response({'ok': False, 'error': str(exc)}, 403)
            if request.path.endswith('/vk-image-upload'):
                denied.force_close()
            return denied
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
    app.router.add_get(root + '/vk-login', _guard(vk_login))
    app.router.add_post(root + '/session', _guard(session))
    app.router.add_get(root + '/me', _guard(profile))
    app.router.add_get(root + '/trends', _guard(vk_public_discovery))
    app.router.add_get(root + '/vk-native-state', _guard(vk_native_state))
    app.router.add_get(root + '/vk-commerce', _guard(vk_native_commerce))
    app.router.add_get(root + '/vk-models', _guard(vk_native_models))
    # This route authenticates the signed VK session before reading bytes.
    # The legacy add_post wrapper attempts JSON parsing first and drains a
    # multipart body. Register directly, as the existing owned-media APIs do.
    app.router.add_route('POST', root + '/vk-image-upload', _guard(vk_image_upload))
    app.router.add_post(root + '/vk-image', _guard(vk_native_image))
    app.router.add_post(root + '/vk-video', _guard(vk_native_video))
    app.router.add_post(root + '/vk-trend', _guard(vk_native_trend))
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
