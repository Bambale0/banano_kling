"""Delivery is separate from paid generation; ambiguous sends are not replayed."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .contract import default_settings, validate_notification_templates

logger = logging.getLogger(__name__)


class DeliveryFailure(Exception):
    def __init__(self, code: str, *, retry_after: int = 0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


class Delivery:
    def __init__(self, pipeline, send: Callable[..., Awaitable[str]]):
        self.pipeline = pipeline
        self.repository = pipeline.repository
        self.send = send

    async def tick(self) -> bool:
        settings, _ = await self.repository.settings()
        item = await self.repository.claim_delivery(settings)
        if not item:
            return False
        sid, token = item['step_id'], item['lease_token']
        try:
            asset = await self.repository.get_asset_internal(item['output_asset_id'])
            if not asset:
                raise DeliveryFailure('asset_unavailable')
            await self.pipeline.media.ensure_asset(asset)
        except Exception:  # noqa: BLE001 - normalize any storage failure before delivery.
            await self.repository.finish_delivery(sid, token, 'unavailable', error_code='asset_unavailable')
            return True
        try:
            message_id = await self.send(item['owner'], asset, item['run_id'], settings['media_timeout_seconds'])
        except DeliveryFailure as exc:
            if exc.code == 'rate_limited':
                await self.repository.finish_delivery(sid, token, 'pending', error_code=exc.code,
                    delay_seconds=max(1, min(exc.retry_after, 86400)))
            else:
                status = 'unavailable' if exc.code in {'chat_unavailable', 'media_rejected'} else 'delivery_unknown'
                await self.repository.finish_delivery(sid, token, status, error_code=exc.code)
        except asyncio.CancelledError:
            # Keep the sending lease: the next worker marks the unknown outcome.
            raise
        except Exception:  # noqa: BLE001 - unknown Telegram outcome must stay ambiguous.
            await self.repository.finish_delivery(sid, token, 'delivery_unknown', error_code='transport_unknown')
        else:
            await self.repository.finish_delivery(sid, token, 'delivered', message_id=str(message_id))
        logger.info('genjutsu_delivery_processed', extra={'task_id': item['run_id'], 'step_id': sid})
        return True

    async def worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if await self.tick():
                    continue
                delay = (await self.repository.settings())[0]['poll_seconds']
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the durable worker alive.
                logger.error('genjutsu_delivery_worker_error', extra={'error_type': type(exc).__name__})
                delay = 5
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass


def terminal_notification_text(summary: dict, templates: dict | None = None) -> str:
    """Select categories server-side; substitute only settled ledger amounts."""
    copy = validate_notification_templates(
        default_settings()['notification_templates'] if templates is None else templates)
    lines = [copy[summary['state']]]
    if summary['moderation_count']:
        lines.append(copy['moderation'])
    if summary['provider_failure_count']:
        lines.append(copy['provider_failure'])
    if summary['technical_failure_count']:
        lines.append(copy['technical_failure'])
    if summary['canceled_count'] and summary['state'] != 'canceled':
        lines.append(copy['canceled_steps'])
    if summary['reserved_credits'] == 0:
        lines.append(copy['no_charge'])
    else:
        if summary['refunded_credits']:
            lines.append(copy['refund'].replace('{refunded_credits}', str(summary['refunded_credits'])))
        lines.append(copy['charge'].replace('{charged_credits}', str(summary['charged_credits'])))
    lines.append(copy['details'])
    return '\n'.join(lines)


class TerminalNotifications:
    """One durable terminal notice per run; uncertain sends are never replayed."""

    def __init__(self, repository, send: Callable[..., Awaitable[str]]):
        self.repository = repository
        self.send = send

    async def tick(self) -> bool:
        settings, _ = await self.repository.settings()
        item = await self.repository.claim_notification(settings)
        if item is None:
            return False
        run_id, token = item['run_id'], item['lease_token']
        try:
            message_id = await self.send(item['owner'], terminal_notification_text(item['summary'], settings['notification_templates']),
                                         run_id, settings['request_timeout_seconds'])
        except DeliveryFailure as exc:
            if exc.code == 'rate_limited':
                delay = max(settings['poll_seconds'], exc.retry_after)
                exhausted = (item['attempts'] >= item['max_attempts'] or
                             self.repository.clock() + delay * 1000 >= item['deadline_ms'])
                await self.repository.finish_notification(
                    run_id, token, 'unavailable' if exhausted else 'pending',
                    error_code='notification_retry_exhausted' if exhausted else exc.code,
                    delay_seconds=0 if exhausted else delay)
            else:
                state = 'unavailable' if exc.code in {'chat_unavailable', 'message_rejected'} else 'delivery_unknown'
                await self.repository.finish_notification(run_id, token, state, error_code=exc.code)
        except asyncio.CancelledError:
            # The sending lease expires into delivery_unknown after restart.
            raise
        except Exception:  # noqa: BLE001 - never assume a missing acknowledgement means no send.
            await self.repository.finish_notification(run_id, token, 'delivery_unknown', error_code='transport_unknown')
        else:
            await self.repository.finish_notification(run_id, token, 'delivered', message_id=str(message_id))
        logger.info('genjutsu_notification_processed', extra={'task_id': run_id})
        return True

    async def worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if await self.tick():
                    continue
                delay = (await self.repository.settings())[0]['poll_seconds']
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - persistent state safely fences restarts.
                logger.error('genjutsu_notification_worker_error', extra={'error_type': type(exc).__name__})
                delay = 5
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
