"""Authenticated HTTP interface; private internals never pass through to clients."""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from aiohttp import web

from .contract import (
    CATALOG,
    PipelineError,
    integer,
    object_fields,
    text,
    validate_settings,
)
from .provider import ProviderFailure, request_id

logger = logging.getLogger(__name__)

# Never copy an arbitrary request action into diagnostic logs.
KNOWN_ACTIONS = frozenset({
    'availability', 'bootstrap', 'presets', 'save_project', 'project', 'versions',
    'trim', 'import', 'quote', 'start', 'run', 'cancel', 'continue', 'redeliver',
    'settings', 'save_settings', 'admin_runs', 'admin_refund', 'admin_reconcile',
    'admin_adopt', 'events', 'recipe_get', 'recipe_preview', 'recipe_costs', 'recipe_list',
    'recipe_publish', 'recipe_archive', 'recipe_quote', 'feed_publish', 'upload', 'callback',
})

# Stable codes are also consumed by the Mini App. Raw provider errors are never returned.
MESSAGES = {
    'invalid_notification_templates': 'Проверьте тексты уведомлений и обязательные поля в фигурных скобках.',
    'invalid_title': 'Введите название проекта от 1 до 120 символов.',
    'invalid_reference_count': 'Проверьте количество фото-референсов для выбранного режима: добавьте недостающие или удалите лишние фото.',
    'reference_required': 'Добавьте фото-референс для выбранного режима.',
    'reference_unavailable': 'Фото-референс недоступен. Загрузите его заново.',
    'asset_unavailable': 'Один из исходных файлов недоступен. Загрузите видео или фото заново.',
    'duplicate_reference': 'Одно фото добавлено несколько раз. Удалите повторный референс.',
    'preset_required': 'Выберите стиль для обработки видео.',
    'completed_output_required': 'В ленту можно опубликовать только готовый итоговый результат.',
    'private_recipe_publication_forbidden': 'Работу по чужому приватному рецепту нельзя опубликовать как новый рецепт.',
    'feed_publication_conflict': 'Этот результат уже опубликован с другими настройками повтора.',
    'feed_publication_withdrawn': 'Публикация снята с ленты. Вернуть её можно в настройках публикации в профиле.',
    'feed_storage_failed': 'Не удалось сохранить видео для ленты. Попробуйте ещё раз.',

    'integration_not_configured': '\u0418\u043d\u0442\u0435\u0433\u0440\u0430\u0446\u0438\u044f Genjutsu \u0435\u0449\u0451 \u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0430.',
    'feature_disabled': 'Genjutsu \u043f\u043e\u043a\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0434\u043b\u044f \u043d\u043e\u0432\u044b\u0445 \u0437\u0430\u043f\u0443\u0441\u043a\u043e\u0432.',
    'price_not_configured': '\u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440 \u0435\u0449\u0451 \u043d\u0435 \u0437\u0430\u0434\u0430\u043b \u0446\u0435\u043d\u0443 \u044d\u0442\u043e\u0439 \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u0438.',
    'insufficient_balance': '\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u0431\u0430\u043d\u0430\u043d\u043e\u0432.',
    'quote_expired': '\u0420\u0430\u0441\u0447\u0451\u0442 \u0446\u0435\u043d\u044b \u0443\u0441\u0442\u0430\u0440\u0435\u043b. \u041f\u0435\u0440\u0435\u0441\u0447\u0438\u0442\u0430\u0439\u0442\u0435 \u0435\u0433\u043e \u043f\u0435\u0440\u0435\u0434 \u0437\u0430\u043f\u0443\u0441\u043a\u043e\u043c.',
    'quote_changed': '\u0422\u0430\u0440\u0438\u0444 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0441\u044f. \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 \u043d\u043e\u0432\u0443\u044e \u0446\u0435\u043d\u0443.',
    'project_conflict': '\u041f\u0440\u043e\u0435\u043a\u0442 \u0438\u0437\u043c\u0435\u043d\u0451\u043d \u0432 \u0434\u0440\u0443\u0433\u043e\u043c \u043e\u043a\u043d\u0435. \u041e\u0431\u043d\u043e\u0432\u0438\u0442\u0435 \u0432\u0435\u0440\u0441\u0438\u044e.',
    'storage_quota': '\u041b\u0438\u043c\u0438\u0442 \u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043d.',
    'preset_unavailable': '\u042d\u0442\u043e\u0442 \u0441\u0442\u0438\u043b\u044c \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0440\u0443\u0433\u043e\u0439.',
    'invalid_video_duration': '\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u0432\u044b\u0445\u043e\u0434\u0438\u0442 \u0437\u0430 \u0433\u0440\u0430\u043d\u0438\u0446\u044b \u0440\u0435\u0436\u0438\u043c\u0430. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u043e\u0434\u0445\u043e\u0434\u044f\u0449\u0438\u0439 \u0444\u0440\u0430\u0433\u043c\u0435\u043d\u0442.',
    'operation_not_verified': '\u0420\u0435\u0436\u0438\u043c \u0435\u0449\u0451 \u043f\u0440\u043e\u0445\u043e\u0434\u0438\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443.',
    'provider_temporarily_unavailable': 'Higgsfield \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435 \u043f\u0440\u0438\u043d\u0438\u043c\u0430\u0435\u0442 \u043d\u043e\u0432\u044b\u0435 \u0437\u0430\u0434\u0430\u0447\u0438. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.',
    'source_resolution_too_low': '\u0418\u0441\u0445\u043e\u0434\u043d\u043e\u0435 \u0432\u0438\u0434\u0435\u043e \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u043c\u0430\u043b\u043e\u0433\u043e \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u044f \u0434\u043b\u044f Object Swap.',
    'recipe_live_verification_required': '\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0443\u0441\u043f\u0435\u0448\u043d\u044b\u0439 \u0430\u0434\u043c\u0438\u043d\u0441\u043a\u0438\u0439 Genjutsu-\u043f\u0440\u043e\u0433\u043e\u043d \u044d\u0442\u043e\u0439 \u0432\u0435\u0440\u0441\u0438\u0438 \u043f\u0440\u043e\u0435\u043a\u0442\u0430.',
    'recipe_reference_count': '\u0417\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0432\u0441\u0435 \u0440\u0435\u0444\u0435\u0440\u0435\u043d\u0441\u044b, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0442\u0440\u0435\u0431\u0443\u0435\u0442 \u044d\u0442\u043e\u0442 \u0442\u0440\u0435\u043d\u0434.',
    'source_required': '\u041f\u0440\u0438\u043a\u0440\u0435\u043f\u0438\u0442\u0435 \u0432\u0438\u0434\u0435\u043e-\u0440\u0435\u0444\u0435\u0440\u0435\u043d\u0441 \u0434\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u0442\u0440\u0435\u043d\u0434\u0430.',
    'source_unavailable': '\u0412\u0438\u0434\u0435\u043e-\u0440\u0435\u0444\u0435\u0440\u0435\u043d\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0438\u043b\u0438 \u0438\u043c\u0435\u0435\u0442 \u043d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u0444\u043e\u0440\u043c\u0430\u0442.',
}


class API:
    def __init__(self, pipeline, authenticate: Callable[..., Awaitable[tuple[int, bool]]], *, importer=None, recipes=None, feed=None):
        self.pipeline = pipeline
        self.repository = pipeline.repository
        self.authenticate = authenticate
        self.importer = importer
        self.recipes = recipes
        self.feed = feed

    def register(self, app: web.Application, *, base='/mini-app/api') -> None:
        # Legacy add_post wrappers eagerly parse JSON/multipart. These two
        # handlers authenticate and enforce the ban check themselves, before
        # bounded body reads; use the direct router primitive to preserve it.
        app.router.add_route('POST', base + '/genjutsu', self.handle)
        app.router.add_route('POST', base + '/genjutsu/upload', self.upload)
        app.router.add_get('/genjutsu/media/{asset_id}', self.media)
        app.router.add_post('/genjutsu/callback/{step_id}/{attempt}', self.callback)

    @staticmethod
    async def body(request: web.Request) -> dict:
        raw = bytearray()
        async for chunk in request.content.iter_chunked(16384):
            raw.extend(chunk)
            if len(raw) > 200000:
                raise PipelineError('request_too_large', status=413)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise PipelineError('invalid_json') from exc
        if not isinstance(body, dict):
            raise PipelineError('invalid_request')
        return body

    @staticmethod
    def fields(body, allowed):
        object_fields(body, set(allowed) | {'action', 'init_data', 'start_param_fallback'}, 'invalid_request')

    @staticmethod
    def ident(body, key):
        value = text(body.get(key), 200, 'invalid_' + key)
        if not value:
            raise PipelineError('invalid_' + key)
        return value

    async def require_creation(self, admin: bool):
        settings, _ = await self.repository.settings()
        if not settings['admin_enabled' if admin else 'public_enabled']:
            raise PipelineError('feature_disabled', status=503)

    def public_asset(self, asset: dict, settings: dict) -> dict:
        allowed = {'id','kind','duration_ms','width','height','has_audio','mime','size_bytes','created_ms'}
        result = {k:v for k,v in asset.items() if k in allowed}
        result['url'] = self.pipeline.media.url(asset['id'], ttl=settings['preview_url_ttl_seconds']) if self.pipeline.media.configured else None
        return result

    async def run_view(self, owner: int, run_id: str, *, privileged=False) -> dict:
        run = await self.repository.get_run(owner, run_id, admin=privileged)
        settings, _ = await self.repository.settings()
        # Older quotes/runs can carry a false privacy flag. The persistent
        # project binding still requires redaction after recipe archival.
        if not run['private_recipe'] and self.recipes and await self.recipes.is_private_project(run['project_id']):
            run['private_recipe'] = 1
        private = bool(run['private_recipe']) and not privileged
        visible_fields = ('id','state','created_ms','updated_ms','cancel_requested','admin_free','private_recipe')
        result = {k:run[k] for k in visible_fields}
        if privileged:
            result['owner'] = run['owner']
        if not private:
            result['project_id'] = run['project_id']
            result['plan'] = run['plan']
        result['steps'] = []
        for step in run['steps']:
            item = {k:step[k] for k in ('id','variant','ordinal','status','reserved_credits','actual_credits',
                'refunded_credits','error_code','delivery_status','delivery_error')}
            item['spec'] = {k:v for k,v in step['spec'].items() if k in (
                {'operation','resolution'} if private else {'operation','resolution','prompt','preserve','references','preset_id'})}
            for field in ('source_asset_id','output_asset_id'):
                if field == 'source_asset_id' and private:
                    continue
                aid = step.get(field)
                asset = await self.repository.get_asset_internal(aid) if aid else None
                item[field.removesuffix('_id')] = self.public_asset(asset, settings) if asset else None
            if privileged:
                item['provider_request_id'] = step['provider_request_id']
                item['provider_correlation_id'] = step['provider_correlation_id']
                item['attempt_id'] = step['attempt_id']
            result['steps'].append(item)
        result['credits'] = float(await self.repository.balance(run['owner']))
        return result

    @staticmethod
    def error(exc: Exception, *, action=None) -> web.Response:
        if isinstance(exc, PipelineError):
            code, status = exc.code, exc.status
        elif isinstance(exc, ProviderFailure):
            code, status = exc.code, 502
        elif isinstance(exc, PermissionError):
            code, status = 'unauthorized', 403
        else:
            code, status = 'internal_error', 500
        safe_action = action if isinstance(action, str) and action in KNOWN_ACTIONS else 'unknown'
        logger.log(
            logging.ERROR if status >= 500 else logging.WARNING,
            'genjutsu_api_error action=%s code=%s status=%s error_type=%s',
            safe_action, code, status, type(exc).__name__,
            extra={'action':safe_action, 'code':code, 'status':status, 'error_type':type(exc).__name__},
        )
        message = MESSAGES.get(code, '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u044e. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0432\u0445\u043e\u0434\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u0438\u043b\u0438 \u043e\u0431\u0440\u0430\u0442\u0438\u0442\u0435\u0441\u044c \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443.')
        return web.json_response({'ok':False,'code':code,'error':message}, status=status,
                                 headers={'Cache-Control':'no-store'})

    async def handle(self, request):
        action = None
        try:
            body = await self.body(request)
            owner, admin = await self.authenticate(request, body)
            action = body.get('action')
            if not isinstance(action, str):
                raise PipelineError('invalid_action')
            if action in {'settings','save_settings','admin_runs','admin_refund','admin_reconcile','admin_adopt','events'} and not admin:
                raise PipelineError('admin_required', status=403)
            data = await self.dispatch(owner, admin, action, body)
            return web.json_response({'ok':True, **data}, headers={'Cache-Control':'no-store'})
        except (ValueError, TypeError, KeyError) as exc:
            return self.error(exc if isinstance(exc, PipelineError) else PipelineError('invalid_request'), action=action)
        except Exception as exc:  # noqa: BLE001 - HTTP boundary maps unknown failures safely.
            return self.error(exc, action=action)

    async def dispatch(self, owner, admin, action, body):
        repo, pipeline = self.repository, self.pipeline
        if action == 'feed_publish':
            self.fields(body, {'run_id', 'step_id', 'title', 'source_binding'})
            if self.feed is None:
                raise PipelineError('feed_publication_unavailable', status=503)
            return await self.feed.publish(owner, self.ident(body, 'run_id'), self.ident(body, 'step_id'),
                                           body.get('title'), body.get('source_binding'))
        if action == 'availability':
            self.fields(body, set())
            settings, _ = await repo.settings()
            visible = settings['admin_enabled' if admin else 'public_enabled']
            if not visible:
                visible = bool(await repo.list_runs(owner))
            return {'visible': visible, 'is_admin': admin}
        if action == 'bootstrap':
            self.fields(body, set())
            settings, version = await repo.settings()
            return {'catalog':CATALOG, 'prices':settings['prices'], 'is_admin':admin,
                'configured':pipeline.configured, 'provider_ready':pipeline.provider.configured,
                'media_ready':pipeline.media.configured,
                'enabled':settings['admin_enabled' if admin else 'public_enabled'],
                'limits':{k:v for k,v in settings.items() if k not in ('prices','public_enabled','admin_enabled','notification_templates')},
                'config_version':version, 'credits':float(await repo.balance(owner)),
                'projects':await repo.list_projects(owner), 'runs':await repo.list_runs(owner),
                'assets':[self.public_asset(a,settings) for a in await repo.list_assets(owner)]}
        if action == 'presets':
            self.fields(body, set())
            await self.require_creation(admin)
            return {'items':await pipeline.presets(force=True)}
        if action == 'save_project':
            self.fields(body, {'title','plan','project_id','expected_revision'})
            await self.require_creation(admin)
            return {'project':await repo.save_project(owner, body.get('title'), body.get('plan'),
                        project_id=body.get('project_id'), expected_revision=body.get('expected_revision'))}
        if action == 'project':
            self.fields(body, {'project_id','revision'})
            project_id = self.ident(body,'project_id')
            if self.recipes and await self.recipes.is_private_project(project_id):
                raise PipelineError('project_unavailable', status=404)
            project = await repo.get_project(owner,project_id,body.get('revision'))
            source_asset = None
            source_id = project['plan'].get('source_asset_id')
            if isinstance(source_id, str) and source_id:
                try:
                    assets = await repo.get_assets(owner, {source_id})
                except PipelineError as exc:
                    # Saved drafts remain repairable when the source is missing or foreign.
                    if exc.code != 'asset_unavailable':
                        raise
                else:
                    asset = assets[source_id]
                    if asset['kind'] == 'video':
                        source_asset = {key:asset[key] for key in ('id','kind','duration_ms')
                                        if key in asset and asset[key] is not None}
            return {'project':project, 'source_asset':source_asset}
        if action == 'versions':
            self.fields(body, {'project_id'})
            project_id = self.ident(body,'project_id')
            if self.recipes and await self.recipes.is_private_project(project_id):
                raise PipelineError('project_unavailable', status=404)
            return {'items':await repo.project_versions(owner,project_id)}
        if action == 'trim':
            self.fields(body, {'asset_id','start_ms','end_ms'})
            await self.require_creation(admin)
            asset = await pipeline.trim(owner, self.ident(body,'asset_id'), body.get('start_ms'), body.get('end_ms'))
            return {'asset':self.public_asset(asset, (await repo.settings())[0])}
        if action == 'import':
            self.fields(body, {'saved_reference_id','task_id'})
            await self.require_creation(admin)
            if self.importer is None:
                raise PipelineError('import_not_available', status=503)
            asset = await self.importer(owner, body)
            return {'asset':self.public_asset(asset, (await repo.settings())[0])}
        if action == 'quote':
            self.fields(body, {'project_id','revision'})
            await self.require_creation(admin)
            quote = await pipeline.quote(owner, self.ident(body,'project_id'), body.get('revision'))
            return {'quote':quote, 'admin_free':admin}
        if action == 'start':
            self.fields(body, {'quote_id','request_key','acknowledge_provider_cost'})
            run = await pipeline.start(owner, self.ident(body,'request_key'), self.ident(body,'quote_id'),
                admin_free=admin, acknowledge_provider_cost=body.get('acknowledge_provider_cost') is True)
            return {'run':await self.run_view(owner,run['id'])}
        if action == 'run':
            self.fields(body, {'run_id','admin_view'})
            if body.get('admin_view') and not admin:
                raise PipelineError('admin_required', status=403)
            return {'run':await self.run_view(owner,self.ident(body,'run_id'),privileged=admin and body.get('admin_view') is True)}
        if action == 'cancel':
            self.fields(body, {'run_id'})
            await repo.cancel(owner,self.ident(body,'run_id'))
            return {'run':await self.run_view(owner,body['run_id'])}
        if action == 'continue':
            self.fields(body, {'run_id','step_id'})
            await repo.continue_run(owner,self.ident(body,'run_id'),self.ident(body,'step_id'))
            return {'run':await self.run_view(owner,body['run_id'])}
        if action == 'redeliver':
            self.fields(body, {'run_id','step_id','acknowledge_duplicate_risk'})
            if body.get('acknowledge_duplicate_risk') is not True:
                raise PipelineError('redelivery_confirmation_required')
            await repo.redeliver(owner,self.ident(body,'run_id'),self.ident(body,'step_id'))
            return {'run':await self.run_view(owner,body['run_id'])}
        if action == 'settings':
            self.fields(body,set())
            settings,version = await repo.settings()
            return {'settings':settings,'version':version,'coverage':await repo.verified_coverage()}
        if action == 'save_settings':
            self.fields(body, {'settings','expected_version'})
            settings = validate_settings(body.get('settings'))
            coverage = await repo.verified_coverage()
            proven = {(row['operation'],row['resolution']) for row in coverage}
            for op in settings['verified_operations']:
                if any((op,resolution) not in proven for resolution in CATALOG[op]['resolutions']):
                    raise PipelineError('live_verification_required', status=409)
            if settings['public_enabled']:
                if not pipeline.configured or set(settings['verified_operations']) != set(CATALOG):
                    raise PipelineError('release_gate_not_passed', status=409)
                if any(rate is None for rates in settings['prices'].values() for rate in rates.values()):
                    raise PipelineError('price_not_configured', status=409)
            version = await repo.update_settings(owner, integer(body.get('expected_version'),0,1000000,'invalid_version'), settings)
            return {'version':version}
        if action == 'admin_runs':
            self.fields(body,set())
            return {'items':await repo.list_runs(owner,admin=True)}
        if action in {'admin_refund','admin_reconcile','admin_adopt','events'}:
            self.fields(body, {'run_id','step_id','reason','provider_request_id','confirm_request_ownership'})
            rid = self.ident(body,'run_id')
            run = await repo.get_run(owner,rid,admin=True)
            if action == 'events':
                return {'items':await repo.events(rid)}
            sid = self.ident(body,'step_id')
            step = next((s for s in run['steps'] if s['id']==sid),None)
            if not step:
                raise PipelineError('step_unavailable', status=404)
            if action == 'admin_refund':
                await repo.admin_refund(owner,rid,sid,body.get('reason'))
            elif action == 'admin_reconcile':
                await repo.request_reconciliation(owner,rid,sid)
            else:
                if body.get('confirm_request_ownership') is not True or step['status'] != 'submission_unknown':
                    raise PipelineError('adoption_confirmation_required')
                external = request_id(body.get('provider_request_id'))
                await pipeline.provider.status(external, timeout=(await repo.settings())[0]['request_timeout_seconds'])
                await repo.accept_submission(sid,step['attempt_id'],external)
                await repo.request_reconciliation(owner,rid,sid)
            return {'run':await self.run_view(owner,rid,privileged=True)}
        if action.startswith('recipe_') and self.recipes:
            return await self.recipes.dispatch(owner,admin,action,body,self)
        raise PipelineError('invalid_action')

    async def upload(self, request):
        try:
            # Authenticate before reading file bytes. The header is only read
            # by the production authenticator; it is never logged or persisted.
            owner,admin = await self.authenticate(request, {'init_data':request.headers.get('X-Telegram-Init-Data','')})
            await self.require_creation(admin)
            reader = await request.multipart()
            part = await reader.next()
            kind = request.query.get('kind')
            if part is None or part.name != 'file':
                raise PipelineError('file_required')
            async def chunks():
                while True:
                    chunk = await part.read_chunk(262144)
                    if not chunk:
                        break
                    yield chunk
            asset = await self.pipeline.store_upload(owner,kind,chunks())
            return web.json_response({'ok':True,'asset':self.public_asset(asset,(await self.repository.settings())[0])},
                                     headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError) as exc:
            return self.error(exc if isinstance(exc,PipelineError) else PipelineError('invalid_upload'), action='upload')
        except Exception as exc:  # noqa: BLE001 - upload boundary must not leak internals.
            return self.error(exc, action='upload')

    async def media(self, request):
        aid = request.match_info['asset_id']
        if not self.pipeline.media.verify(aid,request.query.get('expires'),request.query.get('signature')):
            raise web.HTTPForbidden()
        asset = await self.repository.get_asset_internal(aid)
        if not asset:
            raise web.HTTPNotFound()
        path = self.pipeline.media.path(asset['storage_key'])
        if not path.is_file():
            raise web.HTTPNotFound()
        disposition = 'attachment' if request.query.get('download') == '1' else 'inline'
        return web.FileResponse(path, headers={'Cache-Control':'private, no-store',
            'Content-Type':asset['mime'],'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Disposition':f'{disposition}; filename="genjutsu-{aid}{path.suffix}"'})

    async def callback(self, request):
        sid,attempt = request.match_info['step_id'],request.match_info['attempt']
        if not self.pipeline.media.verify_callback(sid,attempt,request.query.get('expires'),request.query.get('signature')):
            raise web.HTTPForbidden()
        try:
            data = await self.body(request)
            rid = request_id(data.get('request_id'))
            # Callback is a wake-up only; an authenticated status GET establishes
            # the actual outcome before result persistence or financial mutation.
            await self.repository.wake_step(sid,attempt,rid)
            return web.json_response({'ok':True})
        except (PipelineError,ProviderFailure) as exc:
            return self.error(exc, action='callback')
