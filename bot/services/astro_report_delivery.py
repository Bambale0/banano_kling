"""Durable Telegram notification of completed/failed Astro report jobs.

An encrypted owner-scoped job is the source of truth. The outbox stores only
metadata, claims one row atomically, retries uncertain transports with bounded
backoff and never claims exactly-once delivery across Telegram timeouts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from threading import Event
from uuid import uuid4

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from bot import db
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_pdf import PDF_FILENAME, SERVICE_NAMES, render_astro_pdf

logger = logging.getLogger(__name__)

class AstroTelegramDelivery:
    def __init__(self, *, jobs: AstroReportJobs, telegram_bot, is_admin,
                 worker_id: str | None = None):
        self.jobs = jobs
        self.telegram_bot = telegram_bot
        self.is_admin = is_admin
        self.worker_id = worker_id or uuid4().hex
        self.max_attempts = int(os.getenv("ASTRO_TELEGRAM_DELIVERY_MAX_ATTEMPTS", "8"))
        self.timeout_seconds = float(os.getenv("ASTRO_TELEGRAM_DELIVERY_TIMEOUT_SECONDS", "90"))
        self.lease_seconds = int(os.getenv("ASTRO_TELEGRAM_DELIVERY_LEASE_SECONDS", "180"))
        self.retry_base = int(os.getenv("ASTRO_TELEGRAM_DELIVERY_RETRY_BASE_SECONDS", "10"))
        self.retry_max = int(os.getenv("ASTRO_TELEGRAM_DELIVERY_RETRY_MAX_SECONDS", "300"))
        self.poll_seconds = float(os.getenv("ASTRO_TELEGRAM_DELIVERY_POLL_SECONDS", "5"))
        if not (1 <= self.max_attempts <= 50 and 5 <= self.timeout_seconds <= 300
                and self.timeout_seconds < self.lease_seconds <= 900
                and 1 <= self.retry_base <= self.retry_max <= 3600
                and 0.25 <= self.poll_seconds <= 120):
            raise ValueError("Invalid Astro Telegram delivery policy")

    async def _claim(self, now: int):
        # PostgreSQL row locking and SQLite's atomic UPDATE ... RETURNING.
        pg_lock = " FOR UPDATE SKIP LOCKED" if db.is_postgres() else ""
        async with self.jobs._connect() as conn:
            # A process may die after claiming its final attempt. Settle that
            # uncertain outcome after lease expiry instead of leaving it sending.
            await conn.execute("""
                UPDATE astro_report_deliveries
                SET status='failed', worker_id=NULL, lease_until=0,
                    error_code='telegram_delivery_uncertain', updated_at=?
                WHERE status='sending' AND lease_until <= ? AND attempts >= ?
            """, (now, now, self.max_attempts))
            cursor = await conn.execute(f"""
                WITH candidate AS (
                    SELECT job_id, event_kind FROM astro_report_deliveries
                    WHERE next_run_at <= ? AND attempts < ?
                      AND (status='pending' OR (status='sending' AND lease_until <= ?))
                    ORDER BY next_run_at, updated_at, job_id
                    LIMIT 1{pg_lock}
                )
                UPDATE astro_report_deliveries
                SET status='sending', worker_id=?, lease_until=?,
                    attempts=attempts+1, updated_at=?
                WHERE (job_id, event_kind) IN (SELECT job_id, event_kind FROM candidate)
                  AND next_run_at <= ? AND attempts < ?
                  AND (status='pending' OR (status='sending' AND lease_until <= ?))
                RETURNING job_id, event_kind, owner_id, attempts
            """, (now, self.max_attempts, now,
                  self.worker_id, now + self.lease_seconds, now,
                  now, self.max_attempts, now))
            row = await cursor.fetchone()
            await conn.commit()
        if row is None:
            return None
        return str(row[0]), str(row[1]), int(row[2]), int(row[3])

    async def _finish(self, *, job_id: str, event_kind: str, now: int,
                      status: str, message_id: int | None = None,
                      attempts: int = 1, error_code: str | None = None) -> None:
        next_run = now + min(self.retry_max, self.retry_base * 2 ** max(0, attempts-1))
        async with self.jobs._connect() as conn:
            cursor = await conn.execute("""
                UPDATE astro_report_deliveries SET
                    status=?, worker_id=NULL, lease_until=0,
                    next_run_at=?, updated_at=?,
                    delivered_at=?, message_id=?, error_code=?
                WHERE job_id=? AND event_kind=? AND worker_id=?
                  AND status='sending' AND lease_until > ?
            """, (status, next_run if status == 'pending' else now,
                  now, now if status == 'delivered' else None,
                  message_id, error_code, job_id, event_kind, self.worker_id, now))
            await conn.commit()
        if cursor.rowcount != 1:
            logger.warning("astro_telegram_delivery_lease_lost job_id=%s kind=%s", job_id, event_kind)

    async def run_once(self, *, now: int | None = None) -> bool:
        started = time.monotonic()
        await self.jobs.initialize()
        now = int(time.time()) if now is None else now
        claim = await self._claim(now)
        if claim is None:
            return False
        job_id, event_kind, owner_id, attempts = claim
        state = await self.jobs.status(owner_id=owner_id, job_id=job_id, now=now)
        if state is None or state.get("status") != event_kind:
            # E.g. explicit owner retry after a terminal failure, or expired job.
            await self._finish(job_id=job_id, event_kind=event_kind, now=now,
                               status="cancelled", attempts=attempts)
            return True
        if owner_id <= 0 or not self.is_admin(owner_id):
            await self._finish(job_id=job_id, event_kind=event_kind, now=now,
                               status="failed", attempts=attempts,
                               error_code="owner_not_authorized")
            return True
        try:
            if event_kind == "completed":
                report = state.get("report")
                if not isinstance(report, dict):
                    raise ValueError("Missing completed report")
                cancel_render = Event()
                try:
                    data = await asyncio.wait_for(
                        asyncio.to_thread(render_astro_pdf, report, cancel_event=cancel_render,
                                          deadline=started + self.timeout_seconds),
                        timeout=self.timeout_seconds,
                    )
                finally:
                    # wait_for cannot kill a thread: the renderer cooperates at
                    # every bounded block/page, including process-task cancellation.
                    cancel_render.set()
                # Rendering yields the loop: recheck deletion, expiry and revocation.
                current_now = now + int(time.monotonic() - started)
                current = await self.jobs.status(owner_id=owner_id, job_id=job_id, now=current_now)
                if current is None or current.get("status") != "completed" or not self.is_admin(owner_id):
                    await self._finish(job_id=job_id, event_kind=event_kind, now=current_now,
                                       status="cancelled", attempts=attempts)
                    return True
                service = str(state.get("service_id") or "")
                label = SERVICE_NAMES.get(service, "Астрологический разбор")
                remaining = self.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Astro delivery budget exhausted")
                message = await asyncio.wait_for(self.telegram_bot.send_document(
                    chat_id=owner_id,
                    document=BufferedInputFile(data, filename=PDF_FILENAME),
                    caption=f"✨ {label} готов! Полный текст во вложении и в истории Mini App.",
                ), timeout=remaining)
            elif event_kind == "failed":
                message = await asyncio.wait_for(self.telegram_bot.send_message(
                    chat_id=owner_id,
                    text=("⚠️ Не удалось завершить ИИ-разбор Astro. "
                          "Проверьте статус в Mini App → Мои предыдущие отчёты. "
                          "Баланс не списан."),
                ), timeout=self.timeout_seconds)
            else:
                raise ValueError("Unknown delivery kind")
            message_id = getattr(message, "message_id", None)
            if type(message_id) is not int or message_id <= 0:
                raise RuntimeError("Telegram delivery result not confirmed")
            await self._finish(job_id=job_id, event_kind=event_kind,
                               now=now + int(time.monotonic() - started),
                               status="delivered", message_id=message_id, attempts=attempts)
            logger.info("astro_telegram_delivered job_id=%s kind=%s attempt=%s",
                        job_id, event_kind, attempts)
        except (TelegramForbiddenError, TelegramBadRequest, ValueError, TypeError):
            await self._finish(job_id=job_id, event_kind=event_kind,
                               now=now + int(time.monotonic() - started),
                               status="failed", attempts=attempts,
                               error_code="delivery_not_permitted")
            logger.warning("astro_telegram_delivery_rejected job_id=%s kind=%s", job_id, event_kind)
        except Exception:  # noqa: BLE001 -- unknown Telegram transport result; bounded retry
            will_retry = attempts < self.max_attempts
            await self._finish(job_id=job_id, event_kind=event_kind,
                               now=now + int(time.monotonic() - started),
                               status="pending" if will_retry else "failed",
                               attempts=attempts, error_code="telegram_delivery_uncertain")
            logger.warning("astro_telegram_delivery_uncertain job_id=%s kind=%s attempt=%s",
                           job_id, event_kind, attempts)
        return True

    async def run_forever(self, stop: asyncio.Event):
        while not stop.is_set():
            try:
                handled = await self.run_once()
            except Exception:  # noqa: BLE001 -- database outage must not kill delivery task
                logger.error("astro_telegram_delivery_recovering")
                handled = False
            if not handled:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass
