"""Delivery is separate from paid generation; ambiguous sends are not replayed."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

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
