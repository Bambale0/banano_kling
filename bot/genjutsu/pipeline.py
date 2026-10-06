"""Application orchestration shared by Mini App, Telegram and recipes.

The durable database is the source of job state. Workers make one bounded unit
of progress at a time and recover through fenced leases after restarts.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time

from .contract import (
    CATALOG,
    PipelineError,
    asset_ids,
    compile_plan,
    provider_input,
    quote_plan,
    request_key,
)
from .provider import ProviderFailure

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, repository, provider, media, *, plan_resolver=None):
        self.repository = repository
        self.provider = provider
        self.media = media
        self.plan_resolver = plan_resolver
        self._presets: tuple[float, list[dict]] = (0, [])
        self._preset_lock = asyncio.Lock()
        self._provider_circuit_until = 0.0

    @property
    def configured(self) -> bool:
        return self.provider.configured and self.media.configured

    async def presets(self, *, force=False) -> list[dict]:
        settings, _ = await self.repository.settings()
        async with self._preset_lock:
            if not force and self._presets[0] > time.monotonic():
                return self._presets[1]
            items = await self.provider.presets(timeout=settings['request_timeout_seconds'])
            self._presets = (time.monotonic() + settings['presets_ttl_seconds'], items)
            return items

    async def quote(self, owner: int, project_id: str, revision: int) -> dict:
        project = await self.repository.get_project(owner, project_id)
        if project['revision'] != revision:
            raise PipelineError('project_conflict', status=409)
        draft, grants, private = project['plan'], set(), False
        if self.plan_resolver:
            draft, grants, private = await self.plan_resolver(owner, project_id, revision, draft)
        settings, version = await self.repository.settings()
        assets = await self.repository.get_assets(owner, asset_ids(draft), grants=grants)
        for asset in assets.values():
            await self.media.ensure_asset(asset)
        presets = None
        if any(s.get('operation') == 'restyle' for s in draft.get('steps', [])):
            presets = {item['id'] for item in await self.presets(force=True)}
        plan = compile_plan(draft, assets, settings, presets=presets)
        quote = quote_plan(plan, assets, settings)
        return await self.repository.create_quote(owner, project_id, revision, plan, quote,
                                                  version, settings, private_recipe=private)

    async def start(self, owner: int, key: str, quote_id: str, *, admin_free=False,
                    acknowledge_provider_cost=False) -> dict:
        request_key(key)
        existing = await self.repository.existing_run(owner, key, quote_id)
        if existing:
            return existing
        if time.monotonic() < self._provider_circuit_until:
            raise PipelineError('provider_temporarily_unavailable', status=503)
        if not self.configured:
            raise PipelineError('integration_not_configured', status=503)
        if admin_free and not acknowledge_provider_cost:
            raise PipelineError('admin_provider_cost_confirmation_required')
        return await self.repository.start(owner, key, quote_id, admin_free=admin_free)

    async def store_upload(self, owner: int, kind: str, stream) -> dict:
        settings, _ = await self.repository.settings()
        if kind not in ('video', 'image', 'audio'):
            raise PipelineError('unsupported_media_kind')
        token = await self.repository.reserve_upload(owner, settings[f'upload_{kind}_bytes'], settings)
        blob = None
        try:
            blob = await self.media.ingest(stream, kind, settings)
            return await self._commit_blob(token, owner, kind, blob)
        finally:
            await self.repository.release_upload(token, owner)

    async def _commit_blob(self, token, owner, kind, blob, *, asset_id=None):
        key = blob['storage_key']
        try:
            return await self.repository.commit_upload(token, owner, kind, key,
                {k: v for k, v in blob.items() if k != 'storage_key'}, asset_id=asset_id)
        except BaseException:
            # A database connection may be lost just after commit. Never remove
            # the file until we have positively established that it is unowned.
            try:
                exists = await self.repository.asset_by_storage_key(key)
                if not exists:
                    self.media.discard(key)
            except Exception:  # noqa: BLE001 - commit outcome requires a conservative orphan check.
                logger.warning('genjutsu_orphan_check_pending', extra={'storage_key': key})
            raise

    async def trim(self, owner: int, asset_id: str, start_ms: int, end_ms: int) -> dict:
        assets = await self.repository.get_assets(owner, {asset_id})
        source = assets[asset_id]
        if source['kind'] != 'video':
            raise PipelineError('video_required')
        await self.media.ensure_asset(source)
        settings, _ = await self.repository.settings()
        token = await self.repository.reserve_upload(owner, settings['upload_video_bytes'], settings)
        try:
            blob = await self.media.trim(source['storage_key'], start_ms, end_ms, settings)
            blob['source_asset_id'] = asset_id
            return await self._commit_blob(token, owner, 'video', blob)
        finally:
            await self.repository.release_upload(token, owner)

    async def tick(self) -> bool:
        current, _ = await self.repository.settings()
        step = await self.repository.claim_step(current)
        if not step:
            return False
        sid, token = step['id'], step['lease_token']
        settings = step['settings']
        # Credentials and admission flags are live; accepted work retains its
        # rates and media policy. Disabling public admission does not stop jobs.
        try:
            if step['status'] == 'ready':
                if not self.configured:
                    await self._defer_or_fail(step, 'integration_not_configured')
                    return True
                await self._submit(step)
            elif step['status'] == 'storing':
                await self._persist(step)
            else:
                if step['cancel_requested']:
                    try:
                        await self.provider.cancel(
                            step['provider_request_id'],
                            timeout=settings['request_timeout_seconds'],
                            cancel_url=step.get('provider_cancel_url'),
                        )
                        await self.repository.record_provider_observation(
                            sid, token, None, 'provider_cancel_requested'
                        )
                    except ProviderFailure as exc:
                        # Failed or ineligible cancellation is not a refund.
                        logger.warning('genjutsu_cancel_failed', extra={
                            'run_id': step['run_id'], 'step_id': sid, 'error_code': exc.code,
                        })
                result = await self.provider.status(
                    step['provider_request_id'],
                    timeout=settings['request_timeout_seconds'],
                    status_url=step.get('provider_status_url'),
                )
                state = result['status']
                await self.repository.record_provider_observation(
                    sid,
                    token,
                    result.get('correlation_id'),
                    'provider_status_observed',
                    details={
                        'provider_status': state,
                        'provider_reason': result.get('reason'),
                    },
                )
                if state == 'completed':
                    await self.repository.defer_step(sid, token, status='storing', delay_seconds=0,
                                                     remote_result_url=result['result_url'])
                elif state in ('failed', 'nsfw', 'canceled'):
                    await self.repository.finish_step(sid, token, 'canceled' if state == 'canceled' else 'failed',
                                                      error_code='provider_' + state)
                else:
                    await self.repository.defer_step(sid, token, status=state, delay_seconds=self._delay(step))
        except ProviderFailure as exc:
            if exc.http_status in {401, 402, 403}:
                self._provider_circuit_until = max(
                    self._provider_circuit_until,
                    time.monotonic() + max(60, current['poll_seconds'] * 6),
                )
            if step['status'] == 'ready' and not step.get('provider_request_id'):
                if self._provider_failure_is_transient(exc):
                    await self._defer_or_fail(step, exc.code)
                else:
                    await self._fail_safely(step, exc.code)
            elif self._provider_failure_is_transient(exc):
                await self._defer_or_fail(step, exc.code)
            else:
                # A non-2xx status lookup is not proof that an accepted
                # generation failed. Keep the debit and quarantine the task;
                # only a terminal provider status may trigger settlement.
                try:
                    await self.repository.park_step(step['id'], step['lease_token'], exc.code)
                except PipelineError as park_exc:
                    if park_exc.code != 'lease_lost':
                        raise
        except PipelineError as exc:
            if exc.code != 'lease_lost':
                if step['status'] == 'ready':
                    await self._fail_safely(step, exc.code)
                elif exc.code in {'result_download_failed', 'media_timeout', 'storage_quota',
                                   'upload_limit', 'asset_file_unavailable'}:
                    await self._defer_or_fail(step, exc.code)
                else:
                    await self._fail_safely(step, exc.code)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - durable worker records a safe code and continues.
            # Keep exception text out of logs; external libraries sometimes
            # embed credential-bearing URLs. Durable events hold safe codes.
            logger.error('genjutsu_worker_error', extra={'step_id': sid, 'error_type': type(exc).__name__})
            await self._defer_or_fail(step, 'worker_error')
        return True

    @staticmethod
    def _delay(step) -> int:
        base = step['settings']['poll_seconds']
        return min(120, base * (1 + min(10, step['poll_count'] // 5))) + random.randrange(max(1, base))

    async def _submit(self, step):
        sid, token, spec = step['id'], step['lease_token'], step['spec']
        source = await self.repository.get_asset_internal(step['source_asset_id'])
        if not source:
            raise PipelineError('source_unavailable')
        await self.media.ensure_asset(source)
        if spec['operation'] == 'object_swap':
            width, height = source.get('width'), source.get('height')
            if (type(width) is not int or type(height) is not int
                    or width * height < CATALOG['object_swap']['minimum_source_pixels']):
                raise PipelineError('source_resolution_too_low')
        images = []
        for ref in spec['references']:
            asset = await self.repository.get_asset_internal(ref['asset_id'])
            if not asset:
                raise PipelineError('reference_unavailable')
            await self.media.ensure_asset(asset)
            images.append(self.media.url(asset['id'], ttl=step['settings']['input_url_ttl_seconds']))
        if (
            spec['operation'] == 'restyle'
            and spec['preset_id'] not in {p['id'] for p in await self.presets(force=True)}
        ):
            raise PipelineError('preset_unavailable')
        body = provider_input(spec, self.media.url(source['id'], ttl=step['settings']['input_url_ttl_seconds']), images)
        attempt = await self.repository.begin_submission(sid, token, source['duration_ms'])
        # From this point an unclassified failure is conservatively ambiguous.
        try:
            handle = await self.provider.submit(spec['provider_path'], body,
                timeout=step['settings']['request_timeout_seconds'],
                idempotency_key=attempt,
                webhook=self.media.callback_url(sid, attempt, ttl=step['settings']['input_url_ttl_seconds']))
        except ProviderFailure as exc:
            if exc.http_status in {401, 402, 403}:
                self._provider_circuit_until = max(
                    self._provider_circuit_until,
                    time.monotonic() + max(60, step['settings']['poll_seconds'] * 6),
                )
            if exc.uncertain:
                await self.repository.defer_step(sid, token, status='submission_unknown', error_code=exc.code)
            else:
                await self.repository.finish_step(sid, token, 'failed', error_code=exc.code)
            return
        except asyncio.CancelledError:
            raise  # expiry recovery retains the durable submitting attempt
        except Exception:  # noqa: BLE001 - an unclassified submit outcome cannot be retried blindly.
            await self.repository.defer_step(sid, token, status='submission_unknown', error_code='submit_outcome_unknown')
            return
        # accept_submission uses the attempt ID, not an expired worker lease.
        await self.repository.accept_submission(
            sid,
            attempt,
            handle['request_id'],
            status_url=handle['status_url'],
            cancel_url=handle['cancel_url'],
            correlation_id=handle['correlation_id'],
        )
        logger.info('genjutsu_provider_accepted', extra={
            'step_id': sid,
            'run_id': step['run_id'],
            'provider_request_id': handle['request_id'],
            'provider_correlation_id': handle['correlation_id'],
        })

    async def _persist(self, step):
        output_id = hashlib.sha256(('genjutsu-result:' + step['id']).encode()).hexdigest()[:32]
        existing = await self.repository.get_asset_internal(output_id)
        if not existing:
            settings = step['settings']
            held = await self.repository.reserve_upload(step['owner'], settings['result_max_bytes'], settings)
            try:
                blob = await self.media.download_result(step['remote_result_url'], settings)
                await self._commit_blob(held, step['owner'], 'video', blob, asset_id=output_id)
            finally:
                await self.repository.release_upload(held, step['owner'])
        await self.repository.finish_step(step['id'], step['lease_token'], 'completed', output_asset_id=output_id)
        logger.info('genjutsu_result_persisted', extra={'run_id': step['run_id'], 'step_id': step['id'], 'asset_id': output_id})

    async def _fail_safely(self, step, code):
        try:
            await self.repository.finish_step(step['id'], step['lease_token'], 'failed', error_code=code)
        except PipelineError as exc:
            if exc.code != 'lease_lost':
                raise

    async def _defer_safely(self, step, code):
        try:
            await self.repository.defer_step(step['id'], step['lease_token'], error_code=code,
                                             delay_seconds=self._delay(step))
        except PipelineError as exc:
            if exc.code != 'lease_lost':
                raise

    @staticmethod
    def _provider_failure_is_transient(exc: ProviderFailure) -> bool:
        if exc.code == 'provider_transport_error':
            return True
        return exc.http_status in {401, 402, 403, 408, 409, 425, 429} or bool(
            exc.http_status and exc.http_status >= 500
        )

    def _retry_expired(self, step) -> bool:
        return self.repository.clock() - step['created_ms'] >= (
            step['settings']['provider_retry_deadline_seconds'] * 1000
        )

    async def _defer_or_fail(self, step, code):
        if not self._retry_expired(step):
            await self._defer_safely(step, code)
            return
        # Before submit, failing is safe: no provider task exists. Once a task
        # has been accepted or a result URL exists, never refund based only on
        # our inability to poll/store it; quarantine for explicit recovery.
        if step['status'] == 'ready' and not step.get('provider_request_id'):
            await self._fail_safely(step, 'retry_deadline_exceeded:' + code)
        else:
            try:
                await self.repository.park_step(
                    step['id'], step['lease_token'], 'retry_deadline_exceeded:' + code
                )
            except PipelineError as exc:
                if exc.code != 'lease_lost':
                    raise

    async def worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self.tick()
                settings, _ = await self.repository.settings()
                delay = 0 if worked else settings['poll_seconds']
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the durable worker alive.
                logger.error('genjutsu_worker_unavailable', extra={'error_type': type(exc).__name__})
                delay = 5
            if delay:
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)
