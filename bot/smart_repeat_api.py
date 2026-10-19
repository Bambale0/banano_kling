"""Authenticated smart-repeat routes delegating to the existing generation engines."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

from aiohttp import web

from bot import smart_repeat_store as store
from bot.smart_repeat_contract import (
    AUTHORIZED_REPEAT,
    SmartRepeatError,
    digest,
    fail,
    public_template,
    source_fingerprint,
)


async def _source(user, source_id, *, author=False):
    from bot import miniapp
    from bot.database import get_generation_task_payload
    if type(source_id) is not int or source_id <= 0:
        fail('INVALID_SOURCE', 'Некорректная публикация.', 400)
    source = await get_generation_task_payload(source_id)
    if not source or source.get('status') != 'completed' or source.get('type') not in {'image', 'video'}:
        fail('SOURCE_UNAVAILABLE', 'Публикация недоступна.', 404)
    if author:
        if source['user_id'] != user.id:
            fail('FORBIDDEN', 'Настраивать поля может только автор.', 403)
    elif not (source.get('is_public_feed') or source.get('is_profile_visible')) or not await miniapp._get_repeat_source_card(source_id, viewer_user_id=user.id):
        fail('SOURCE_UNAVAILABLE', 'Публикация больше недоступна.', 404)
    return source


def _context(user, source, template, draft, compiled):
    effective = compiled['source']
    return {'user_id': user.id, 'telegram_id': user.telegram_id,
        'request_task': asyncio.current_task(),
        'draft_id': draft['id'], 'source_id': source['id'],
        'source_hash': source_fingerprint(source), 'template_version': template['version'],
        'owned_inputs': {ref['url'] for ref in compiled['snapshot']['references'].values() if ref['binding'] == 'upload'},
        'overrides': {key: deepcopy(effective[key]) for key in (
            'prompt', 'request_data', 'feed_repeat_reference_selection', 'feed_references_visible', 'feed_reference_selection') if key in effective}}


def _engine_body(user, source, compiled, auth_body, draft, *, quote=False):
    from bot.video_repeat_reference_contract import MEDIA_KEYS, source_request
    data = {key: deepcopy(value) for key, value in source_request(source).items()
            if key not in MEDIA_KEYS and key not in {'init_data', 'initData', 'token', 'api_key'}}
    # Only stored model settings are inherited. Client input never picks a
    # different model or changes the author's hidden provider recipe.
    body = {**data, **compiled['body'], 'prompt': '',
        'init_data': auth_body.get('init_data', ''),
        'start_param_fallback': auth_body.get('start_param_fallback'),
        'img_service': source['model'], 'v_model': source['model'],
        'img_ratio': source.get('aspect_ratio') or data.get('img_ratio') or '1:1',
        'img_quality': data.get('img_quality') or data.get('quality') or '2K',
        'v_ratio': source.get('aspect_ratio') or data.get('v_ratio') or '16:9',
        'v_duration': source.get('duration') or data.get('v_duration') or 5,
        'pricing_quote_only': quote, 'seedance25_quote_only': quote}
    engine = (draft.get('quote') or {}).get('engine') or {}
    body.update(pricing_quote_hash=engine.get('quote_hash'),
        seedance25_reference_quote_hash=engine.get('quote_hash'),
        seedance25_identity_quote=engine.get('seedance25_identity_quote'))
    if source['model'] in {'wan_3', 'wan_3_prime'}:
        body = {**compiled['body'], 'init_data': auth_body.get('init_data', ''),
            'start_param_fallback': auth_body.get('start_param_fallback'),
            'quoteOnly': quote, 'quote_hash': engine.get('quote_hash'), 'idempotency_key': draft['id']}
    return body


async def _delegate(request, user, source, template, draft, compiled, auth_body, *, quote):
    from bot import miniapp
    from bot.handlers.miniapp_video_continuity_compat import _replace_cached_json
    context = _context(user, source, template, draft, compiled)
    token = AUTHORIZED_REPEAT.set(context)
    try:
        body = _engine_body(user, source, compiled, auth_body, draft, quote=quote)
        if source['type'] == 'image' and quote:
            cost = miniapp._resolve_image_unit_cost(body['img_service'], body['img_quality'])
            return {'cost': 0 if miniapp.config.is_admin(user.telegram_id) else cost, 'engine': {'cost': cost}}
        if source['model'] in {'wan_3', 'wan_3_prime'}:
            from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
            from bot.services.wan3_prime_repeat import get_repeat_plan
            from bot.wan3_prime_api import miniapp_generate_wan
            plan = await get_repeat_plan(Wan3PrimeActor(user.id, user.telegram_id), source['id'])
            body['repeat_plan_hash'] = plan['hash']
            response = await miniapp_generate_wan(request, body)
        else:
            _replace_cached_json(request, body)
            response = await (miniapp.miniapp_generate_image(request) if source['type'] == 'image'
                              else miniapp.miniapp_generate_video(request))
        if not quote:
            return response
        result = json.loads(response.text)
        if response.status >= 400 or not result.get('ok'):
            fail(str(result.get('code') or 'REPEAT_VALIDATION_FAILED'),
                 str(result.get('error') or 'Проверьте референсы и повторите расчёт.'), response.status)
        amount = result.get('reserve_cost', result.get('cost'))
        return {'cost': 0 if result.get('admin_free') else amount, 'engine': result}
    finally:
        AUTHORIZED_REPEAT.reset(token)


def _json(payload, *, status=200):
    return web.json_response(payload, status=status, headers={'Cache-Control': 'private, no-store'})


async def smart_repeat_route(request):
    from bot import miniapp
    user, draft, auth_body = None, None, {}
    try:
        auth_body = await request.json()
        if not isinstance(auth_body, dict):
            fail('INVALID_REQUEST', 'Некорректный запрос.', 400)
        telegram_id, context = await miniapp._get_user_context(request.app,
            str(auth_body.get('init_data') or ''), auth_body.get('start_param_fallback'))
        user = context['user']
        from bot.database import is_user_banned
        if await is_user_banned(telegram_id):
            fail('FORBIDDEN', 'Доступ к генерации ограничен.', 403)
        if not getattr(user, 'telegram_id', None):
            from types import SimpleNamespace
            user = SimpleNamespace(id=user.id, telegram_id=telegram_id)
        action = request.match_info['action']
        if action == 'migration':
            if not miniapp.config.is_admin(telegram_id):
                fail('FORBIDDEN', 'Проверка старых публикаций доступна администратору.', 403)
            after_id, limit = auth_body.get('after_id', 0), auth_body.get('limit', 25)
            if type(after_id) is not int or after_id < 0 or type(limit) is not int or not 1 <= limit <= 100:
                fail('INVALID_REQUEST', 'Некорректный диапазон проверки.', 400)
            return _json({'ok': True, **await store.migrate_public_templates(after_id=after_id, limit=limit)})
        if action == 'rollout':
            if not miniapp.config.is_admin(telegram_id):
                fail('FORBIDDEN', 'Эта настройка доступна только администратору.', 403)
            enabled, ids = auth_body.get('enabled'), auth_body.get('telegram_ids', [])
            if type(enabled) is not bool or not isinstance(ids, list) or any(type(value) is not int or value <= 0 for value in ids):
                fail('INVALID_REQUEST', 'Некорректная настройка выпуска.', 400)
            from bot.database import set_bot_setting
            await set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': enabled, 'telegram_ids': ids}),
                                  updated_by_telegram_id=telegram_id)
            return _json({'ok': True, 'enabled': enabled})
        if action in {'template', 'configure'}:
            author = action == 'configure' or auth_body.get('author') is True
            source = await _source(user, auth_body.get('source_id'), author=author)
            template = await (store.save_template(user, source, auth_body.get('template') or {})
                if action == 'configure' else store.get_template(source, author=author))
            return _json({'ok': True, 'template': public_template(template, author=author)})
        if action == 'open':
            if type(auth_body.get('source_id')) is not int:
                fail('INVALID_SOURCE', 'Некорректная публикация.', 400)
            previous = await store.latest_draft(user.id, auth_body['source_id'])
            if previous and previous['status'] != 'draft' and auth_body.get('new') is not True:
                previous = await store.recover_draft(user, previous)
                return _json({'ok': True, **store.public_draft(previous, await store._template_for_draft(previous))})
            if not await store.rollout_enabled(telegram_id):
                fail('FEATURE_DISABLED', 'Умные повторы пока недоступны для этого аккаунта.', 403)
            source = await _source(user, auth_body.get('source_id'))
            template = await store.get_template(source)
            draft = await store.open_draft(user, source, template, new=auth_body.get('new') is True)
            draft = await store.refresh_draft_media(user, draft)
            return _json({'ok': True, **store.public_draft(draft, template)})
        if action == 'diagnostics' and miniapp.config.is_admin(telegram_id):
            from bot import db as db_backend
            async with db_backend.connect() as db:
                db.row_factory = db_backend.Row
                row = await (await db.execute('SELECT * FROM smart_repeat_drafts WHERE id = ? OR task_id = ? '
                    'ORDER BY created_at DESC LIMIT 1', (auth_body.get('draft_id'), auth_body.get('task_id')))).fetchone()
            draft = store._decode(row)
            template = await store._template_for_draft(draft)
            return _json({'ok': True, 'draft_id': draft['id'], 'user_id': draft['user_id'],
                'task_id': draft['task_id'], 'status': draft['status'], 'snapshot': _diagnostic_snapshot(draft),
                'expected_slots': public_template(template)['slots'],
                **await store.diagnostic_finance(draft)})
        draft_id = auth_body.get('draft_id')
        if not isinstance(draft_id, str) or len(draft_id) != 32:
            fail('DRAFT_NOT_FOUND', 'Черновик не найден.', 404)
        draft = await store.load_draft(user.id, draft_id)
        if action in {'launch', 'quote'} and draft['status'] != 'draft':
            draft = await store.recover_draft(user, draft)
        if action == 'diagnostics':
            return _json({'ok': True, 'draft_id': draft_id, 'status': draft['status'],
                'snapshot': _diagnostic_snapshot(draft), 'task_id': draft.get('task_id'),
                **await store.diagnostic_finance(draft)})
        if action in {'launch', 'quote'} and draft['status'] != 'draft':
            if draft.get('result'):
                return _json(draft['result']['body'], status=draft['result']['status'])
            return _json({'ok': False, 'code': 'OPERATION_PENDING', 'task_id': draft.get('task_id'),
                'error': 'Операция уже создана. Проверьте историю.'}, status=202)
        if not await store.rollout_enabled(telegram_id):
            fail('FEATURE_DISABLED', 'Умные повторы временно отключены. Ваши файлы сохранены.', 403)
        source = await _source(user, draft['source_id'])
        template = await store.get_template(source)
        if draft['template_version'] != template['version']:
            fail('TEMPLATE_CHANGED', 'Автор обновил поля. Откройте повтор заново.')
        if action == 'update':
            draft = await store.mutate_draft(user, draft_id, template, str(auth_body.get('operation') or ''),
                slot_id=auth_body.get('slot_id'), upload_token=auth_body.get('upload_token'),
                url=auth_body.get('url'), saved_reference_id=auth_body.get('saved_reference_id'),
                wan3_media_id=auth_body.get('wan3_media_id'),
                preset_id=auth_body.get('preset_id'), user_values=auth_body.get('user_values'),
                prompt_changes=auth_body.get('prompt_changes'))
            return _json({'ok': True, **store.public_draft(draft, template)})
        if action not in {'quote', 'launch'}:
            fail('INVALID_OPERATION', 'Неизвестная операция.', 400)
        if draft['status'] != 'draft':
            if draft.get('result'):
                return _json(draft['result']['body'], status=draft['result']['status'])
            return _json({'ok': False, 'code': 'OPERATION_PENDING', 'task_id': draft.get('task_id'),
                'error': 'Операция уже создана. Проверьте историю.'}, status=202)
        compiled = await store.validate_inputs(user, source, template, draft)
        fresh_quote = await _delegate(request, user, source, template, draft, compiled, auth_body, quote=True)
        if action == 'quote':
            await store.save_quote(user, draft, template, fresh_quote)
            draft = await store.load_draft(user.id, draft_id)
            return _json({'ok': True, **store.public_draft(draft, template)})
        previous = draft.get('quote')
        if not previous or digest(fresh_quote) != digest({key: previous[key] for key in ('cost', 'engine')}):
            fail('PRICE_CHANGED', 'Стоимость или параметры изменились. Рассчитайте цену заново.')
        await store.claim_launch(user, source, template, draft, auth_body.get('quote_id'), compiled)
        response = await _delegate(request, user, source, template, draft, compiled, auth_body, quote=False)
        result = await store.finish_launch(user, draft_id, response)
        if response.status >= 400:
            current = await store.load_draft(user.id, draft_id)
            if current.get('task_id') and current['status'] != 'rejected':
                return _json({'ok': True, 'status': 'queued', 'task_id': current['task_id'],
                    'source_feed_gen_id': source['id'], 'prompt_hidden': True}, status=202)
        return _json(result, status=response.status)
    except SmartRepeatError as exc:
        store.event('validation_failed', user_id=user.id if user else None,
            source_id=(draft or {}).get('source_id', auth_body.get('source_id')), code=exc.code,
            draft_id=(draft or {}).get('id'), template_version=(draft or {}).get('template_version'))
        return _json({'ok': False, 'code': exc.code, 'error': exc.message}, status=exc.status)
    except Exception as exc:  # noqa: BLE001 - sanitize the HTTP boundary and preserve uncertain operations
        expected = miniapp._miniapp_expected_error_response(exc)
        if expected is not None:
            return expected
        store.logger.error('smart_repeat request_failed error_type=%s', type(exc).__name__)
        return _json({'ok': False, 'code': 'REPEAT_UNAVAILABLE',
            'error': 'Не удалось подтвердить состояние повтора. Обновите его; повторного списания не будет.'}, status=503)


def _diagnostic_snapshot(draft):
    snapshot = draft.get('snapshot') or {}
    return {key: value for key, value in snapshot.items() if key in {
        'draft_id', 'revision', 'contract_version', 'source_id', 'template_version', 'model', 'preset_id'}} | {
        'references': {sid: {key: value for key, value in ref.items() if key != 'url'}
                       for sid, ref in snapshot.get('references', {}).items()}}


def setup_smart_repeat_routes(app, miniapp_root):
    app.middlewares.append(legacy_repeat_gateway)
    app.router.add_post(miniapp_root + '/api/repeat/{action}', smart_repeat_route)


@web.middleware
async def legacy_repeat_gateway(request, handler):
    """Stale clients cannot bypass the slot form during a staged rollout."""
    targets = ('/api/generate-image', '/api/generate-video', '/api/feed/remix',
               '/api/wan3/generate', '/api/wan3/launch', '/api/v1/generate/image', '/api/v1/generate/video')
    rest_remix = request.path.startswith('/api/v1/feed/') and request.path.endswith('/remix')
    if request.method != 'POST' or not (request.path.endswith(targets) or rest_remix):
        return await handler(request)
    from bot import miniapp
    try:
        body = await miniapp._miniapp_payload(request)
    except (ValueError, TypeError):
        return await handler(request)
    if not isinstance(body, dict):
        return await handler(request)
    recipe = body.get('recipe') if isinstance(body.get('recipe'), dict) else body
    source_id = (recipe.get('source_feed_gen_id') or recipe.get('sourceFeedGenId') or
        ((body.get('gen_id') or request.match_info.get('gen_id')) if '/remix' in request.path else None))
    if not source_id:
        return await handler(request)
    try:
        telegram_id, _ = await miniapp._get_user_context(request.app, str(body.get('init_data') or ''), body.get('start_param_fallback'))
        if await store.rollout_enabled(telegram_id):
            from bot.database import get_generation_task_payload
            source = await get_generation_task_payload(source_id)
            if source and (source.get('is_public_feed') or source.get('is_profile_visible')):
                return _json({'ok': False, 'code': 'SMART_REPEAT_REQUIRED', 'source_id': source['id'],
                    'error': 'Обновите Mini App и откройте повтор с подписанными полями.'}, status=409)
    except Exception as exc:  # noqa: BLE001 - fail closed at the legacy HTTP boundary
        expected = miniapp._miniapp_expected_error_response(exc)
        if expected is not None:
            return expected
        store.logger.error('smart_repeat gateway_failed error_type=%s', type(exc).__name__)
        return _json({'ok': False, 'code': 'REPEAT_UNAVAILABLE', 'error': 'Не удалось проверить повтор. Попробуйте позже.'}, status=503)
    return await handler(request)
