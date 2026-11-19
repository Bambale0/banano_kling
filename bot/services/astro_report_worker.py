"""Leased Astro report worker: retry/backoff, heartbeat and durable checkpoints.

Never charges user balances. In-flight vendor calls have at-least-once
semantics after a process crash; use checkpointed sections to reduce repeats.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from bot.services.astro_kie_gpt6 import KiePermanentError, KieRetryableError
from bot.services.astro_report_jobs import AstroReportJobs, ClaimedAstroJob
from bot.services.astro_report_pipeline import (
    AstroReportError,
    AstroSectionValidationError,
    ReportPlan,
    compose_report,
    load_report_plan,
    report_fingerprint,
)

logger = logging.getLogger(__name__)


_ARCHIVED_NATAL_PLAN_PATHS = (
    Path(__file__).resolve().parents[1] / "astro_report_plans_natal_v3_legacy.json",
    Path(__file__).resolve().parents[1] / "astro_report_plans_natal_v2_legacy.json",
)


def resolve_astro_job_plan(job: ClaimedAstroJob, secret: str) -> tuple[ReportPlan, str | None]:
    """Match an encrypted job's exact immutable prompt and section contract.

    On a natal prompt update, existing failed/manual-retry jobs must keep their
    original verified template and encrypted checkpoints. The current v4
    release also supports signed v3 and v2 natal jobs. Unauthenticated/tampered fingerprints fail
    closed; we never silently swap templates or reuse someone else's content.
    """
    latest = load_report_plan(job.service_id)
    candidates = [latest]
    if job.service_id == "natal":
        candidates.extend(load_report_plan("natal", path=p) for p in _ARCHIVED_NATAL_PLAN_PATHS)
    for plan in candidates:
        fingerprint = report_fingerprint(
            owner_id=job.owner_id, plan=plan, facts=job.facts,
            secret=secret, generation_id=job.job_id,
        )
        if job.fingerprint == fingerprint:
            if plan is not latest:
                logger.info(
                    "astro_report_archived_plan_selected job_id=%s service=%s version=%s",
                    job.job_id, job.service_id, plan.version,
                )
            return plan, job.job_id
        # Prior to per-click generation IDs, fingerprints were facts-only.
        legacy_fingerprint = report_fingerprint(
            owner_id=job.owner_id, plan=plan, facts=job.facts, secret=secret,
        )
        if job.fingerprint == legacy_fingerprint:
            if plan is not latest:
                logger.info(
                    "astro_report_archived_plan_selected job_id=%s service=%s version=%s",
                    job.job_id, job.service_id, plan.version,
                )
            return plan, None
    raise ValueError("Astro source facts or template changed")


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
                # Extract only the trusted section identifier; never log prompts,
                # user birth data, or response text.
                section_id = "unknown"
                try:
                    section = json.loads(kwargs.get("user_instruction", "{}")).get("section_id")
                    if isinstance(section, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,60}", section):
                        section_id = section
                except (TypeError, ValueError, AttributeError):
                    pass
                logger.info(
                    "astro_provider_call_started job_id=%s service=%s attempt=%s "
                    "call_no=%s section=%s",
                    job.job_id, job.service_id, job.attempt, call_no, section_id,
                )
                try:
                    response = await self.provider.analyze_text(**kwargs)
                except KieRetryableError:
                    logger.warning("astro_provider_call_retryable job_id=%s service=%s call_no=%s section=%s",
                                   job.job_id, job.service_id, call_no, section_id)
                    raise
                except KiePermanentError:
                    logger.warning("astro_provider_call_permanent job_id=%s service=%s call_no=%s section=%s",
                                   job.job_id, job.service_id, call_no, section_id)
                    raise
                logger.info(
                    "astro_provider_call_succeeded job_id=%s service=%s call_no=%s "
                    "section=%s latency_ms=%d",
                    job.job_id, job.service_id, call_no, section_id,
                    round((time.monotonic() - call_started) * 1000),
                )
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
            plan, generation_id = resolve_astro_job_plan(
                job, self.jobs.fingerprint_secret,
            )
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
