"""Leased Astro report worker: retry/backoff, heartbeat and durable checkpoints.

Never charges user balances. In-flight vendor calls have at-least-once
semantics after a process crash; use checkpointed sections to reduce repeats.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import suppress
from uuid import uuid4

from bot.services.astro_kie_gpt6 import KiePermanentError, KieRetryableError
from bot.services.astro_report_jobs import AstroReportJobs, ClaimedAstroJob
from bot.services.astro_report_pipeline import (
    AstroReportError,
    AstroSectionValidationError,
    compose_report,
    load_report_plan,
    report_fingerprint,
)

logger = logging.getLogger(__name__)


class AstroReportWorker:
    def __init__(
        self, *, jobs: AstroReportJobs, provider, checkpoints,
        is_admin, worker_id: str | None = None,
        job_timeout_seconds: float | None = None,
    ):
        self.jobs = jobs
        self.provider = provider
        self.checkpoints = checkpoints
        self.is_admin = is_admin
        self.worker_id = worker_id or uuid4().hex
        self.job_timeout_seconds = job_timeout_seconds or float(
            os.getenv("ASTRO_REPORT_JOB_TIMEOUT_SECONDS", "7200")
        )
        if not 60 <= self.job_timeout_seconds <= 86400:
            raise ValueError("Invalid Astro report worker timeout")

    async def _heartbeat(self, job: ClaimedAstroJob):
        interval = max(1, self.jobs.policy.lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            if not await self.jobs.heartbeat(job_id=job.job_id, worker_id=self.worker_id):
                raise RuntimeError("Astro report worker lost generation lease")

    async def run_once(self, *, now: int | None = None) -> bool:
        if not await self.jobs.circuit_allows(now=now):
            return False
        job = await self.jobs.claim(worker_id=self.worker_id, now=now)
        if job is None:
            return False
        started = time.monotonic()
        heartbeat = asyncio.create_task(self._heartbeat(job), name="astro-report-lease")

        provider_call_count = 0

        class AuthorizedProvider:
            async def analyze_text(_, **kwargs):
                nonlocal provider_call_count
                if not self.is_admin(job.owner_id):
                    raise PermissionError("Astro owner role revoked")
                if not await self.jobs.heartbeat(job_id=job.job_id, worker_id=self.worker_id):
                    raise PermissionError("Astro job lease unavailable")
                provider_call_count += 1
                call_no = provider_call_count
                call_started = time.monotonic()
                # Correlate KIE requests with durable jobs, not sensitive birth facts.
                logger.info("astro_provider_call_started job_id=%s service=%s attempt=%s call_no=%s",
                            job.job_id, job.service_id, job.attempt, call_no)
                try:
                    response = await self.provider.analyze_text(**kwargs)
                except KieRetryableError:
                    logger.warning("astro_provider_call_retryable job_id=%s service=%s call_no=%s",
                                   job.job_id, job.service_id, call_no)
                    raise
                except KiePermanentError:
                    logger.warning("astro_provider_call_permanent job_id=%s service=%s call_no=%s",
                                   job.job_id, job.service_id, call_no)
                    raise
                logger.info("astro_provider_call_succeeded job_id=%s service=%s call_no=%s latency_ms=%d",
                            job.job_id, job.service_id, call_no,
                            round((time.monotonic() - call_started) * 1000))
                if not self.is_admin(job.owner_id):
                    raise PermissionError("Astro owner role revoked")
                if not await self.jobs.heartbeat(job_id=job.job_id, worker_id=self.worker_id):
                    raise PermissionError("Astro job lease unavailable")
                # Provider health is independent of the local content proof gate.
                # A successful transport probe closes a stale circuit even if
                # the generated section later fails deterministic validation.
                await self.jobs.circuit_success()
                return response

        try:
            if not self.is_admin(job.owner_id):
                raise PermissionError("Astro owner role revoked")
            plan = load_report_plan(job.service_id)
            expected = report_fingerprint(
                owner_id=job.owner_id, plan=plan, facts=job.facts,
                secret=self.jobs.fingerprint_secret, generation_id=job.job_id,
            )
            # Historic queued jobs use the original facts-only HMAC. Keep them
            # resumable after release; new jobs have an isolated checkpoint key.
            legacy = report_fingerprint(
                owner_id=job.owner_id, plan=plan, facts=job.facts,
                secret=self.jobs.fingerprint_secret,
            )
            if job.fingerprint == expected:
                generation_id = job.job_id
            elif job.fingerprint == legacy:
                generation_id = None
            else:
                raise ValueError("Astro source facts or template changed")
            report = await asyncio.wait_for(compose_report(
                owner_id=job.owner_id, plan=plan, facts=job.facts,
                secret=self.jobs.fingerprint_secret, store=self.checkpoints,
                provider=AuthorizedProvider(), generation_id=generation_id,
            ), timeout=self.job_timeout_seconds)
            if not self.is_admin(job.owner_id):
                raise PermissionError("Astro owner role revoked")
            if not await self.jobs.complete(job_id=job.job_id, worker_id=self.worker_id,
                                            report=report, now=now):
                raise PermissionError("Astro report job lease expired")
            await self.jobs.circuit_success()
            logger.info("astro_report_completed job_id=%s owner_id=%s service=%s "
                        "sections=%s latency_ms=%d", job.job_id, job.owner_id,
                        job.service_id, len(report["sections"]),
                        round((time.monotonic() - started) * 1000))
        except AstroSectionValidationError:
            # KIE responded successfully: a rejected local section must not
            # trip the provider-wide circuit breaker or stall other admins.
            await self.jobs.reschedule(job_id=job.job_id, worker_id=self.worker_id,
                                       retry=True, error_code="section_validation_failed", now=now)
            logger.warning("astro_report_content_retry job_id=%s owner_id=%s service=%s attempt=%s",
                           job.job_id, job.owner_id, job.service_id, job.attempt)
        except (KieRetryableError, TimeoutError):
            await self.jobs.circuit_failure(now=now)
            await self.jobs.reschedule(job_id=job.job_id, worker_id=self.worker_id,
                                       retry=True, error_code="temporary_provider_failure", now=now)
            logger.warning("astro_report_retry job_id=%s owner_id=%s service=%s attempt=%s",
                           job.job_id, job.owner_id, job.service_id, job.attempt)
        except AstroReportError:
            await self.jobs.reschedule(job_id=job.job_id, worker_id=self.worker_id,
                                       retry=True, error_code="invalid_report_content", now=now)
            logger.warning("astro_report_invalid_content job_id=%s owner_id=%s service=%s attempt=%s",
                           job.job_id, job.owner_id, job.service_id, job.attempt)
        except (KiePermanentError, ValueError, PermissionError):
            await self.jobs.reschedule(job_id=job.job_id, worker_id=self.worker_id,
                                       retry=False, error_code="report_not_allowed", now=now)
            logger.warning("astro_report_rejected job_id=%s owner_id=%s service=%s",
                           job.job_id, job.owner_id, job.service_id)
        except Exception:  # noqa: BLE001 -- task boundary: do not drop a leased job
            # Fail safely; no raw fact data/provider text should enter logs.
            await self.jobs.reschedule(job_id=job.job_id, worker_id=self.worker_id,
                                       retry=True, error_code="internal_retry", now=now)
            logger.error("astro_report_internal_retry job_id=%s", job.job_id)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def run_forever(self, stop: asyncio.Event):
        interval = float(os.getenv("ASTRO_REPORT_POLL_SECONDS", "3"))
        if not 0.25 <= interval <= 60:
            raise ValueError("Invalid Astro queue poll interval")
        while not stop.is_set():
            try:
                worked = await self.run_once()
            except Exception:  # noqa: BLE001 -- DB/network outage must not kill worker
                logger.error("astro_report_worker_loop_recovering")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
