"""Durable report queue: owner scoping, leases, retries, encryption, breaker."""
import asyncio

import pytest
from cryptography.fernet import Fernet

from bot.services.astro_report_jobs import AstroJobPolicy, AstroReportJobs
from bot.services.astro_report_pipeline import load_report_plan


def store(tmp_path):
    return AstroReportJobs(
        db_path=str(tmp_path / "jobs.db"), fingerprint_secret="test-only-dedup",
        data_key=Fernet.generate_key(),
        policy=AstroJobPolicy(max_attempts=3, retry_base_seconds=3,
                              retry_max_seconds=60, lease_seconds=20,
                              circuit_failures=2, circuit_cooldown_seconds=60),
    )


def facts():
    return {"schema_version": "astro.natal-facts.v1", "chart": {
        "bodies": {"Sun": {"lon": 12.5}}, "birth_city": "private city"},
    }


def test_enqueue_is_idempotent_per_request_not_per_birth_facts(tmp_path):
    async def check():
        jobs = store(tmp_path)
        plan = load_report_plan("natal")
        a = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True,
                               now=100, request_id="a" * 32)
        b = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True,
                               now=101, request_id="a" * 32)
        c = await jobs.enqueue(owner_id=2, plan=plan, facts=facts(), consent=True,
                               now=102, request_id="a" * 32)
        d = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True,
                               now=103, request_id="b" * 32)
        e = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True, now=104)
        f = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True, now=105)
        assert a == b  # HTTP replay of one click is not double-charged.
        assert len({a, c, d, e, f}) == 5  # Same birth facts: unlimited fresh reports.
        assert await jobs.status(owner_id=2, job_id=a) is None
        assert (await jobs.status(owner_id=1, job_id=a, now=106))["status"] == "queued"
        assert b"private city" not in (tmp_path / "jobs.db").read_bytes()

        changed = {**facts(), "chart": {"bodies": {"Sun": {"lon": 44}}}}
        with pytest.raises(ValueError, match="request"):
            await jobs.enqueue(owner_id=1, plan=plan, facts=changed, consent=True,
                               now=107, request_id="a" * 32)
        with pytest.raises(ValueError):
            await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True,
                               now=108, request_id="not-a-valid-key")
    asyncio.run(check())


def test_claim_single_owner_heartbeat_retry_and_lease_recovery(tmp_path):
    async def check():
        jobs = store(tmp_path)
        ident = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=100)
        a = await jobs.claim(worker_id="a", now=101)
        assert a.job_id == ident and a.attempt == 1
        assert await jobs.claim(worker_id="b", now=102) is None
        assert await jobs.heartbeat(job_id=ident, worker_id="a", now=110)
        assert await jobs.claim(worker_id="b", now=122) is None
        assert await jobs.claim(worker_id="b", now=131) is not None
        assert not await jobs.complete(job_id=ident, worker_id="a", now=132, report={"status": "completed", "word_count": 9000})
        assert await jobs.reschedule(job_id=ident, worker_id="b", now=132,
                                     retry=True, error_code="rate_limited")
        assert await jobs.claim(worker_id="c", now=133) is None
        assert await jobs.claim(worker_id="c", now=137) is None
        next_job = await jobs.claim(worker_id="c", now=138)
        assert next_job.attempt == 3
        assert await jobs.complete(job_id=ident, worker_id="c", now=139,
                                   report={"status": "completed", "word_count": 9000})
        status = await jobs.status(owner_id=1, job_id=ident, now=139)
        assert status["report"]["word_count"] == 9000
        assert await jobs.claim(worker_id="d", now=140) is None
    asyncio.run(check())


def test_circuit_breaker_persisted_across_restarts(tmp_path):
    async def check():
        jobs = store(tmp_path)
        assert await jobs.circuit_allows(now=100)
        await jobs.circuit_failure(now=100)
        assert await jobs.circuit_allows(now=101)
        await jobs.circuit_failure(now=102)
        other = AstroReportJobs(db_path=jobs.db_path,
                                fingerprint_secret=jobs.fingerprint_secret,
                                data_key=jobs.data_key, policy=jobs.policy)
        assert not await other.circuit_allows(now=130)
        assert await other.circuit_allows(now=163)
        await other.circuit_success()
        assert await other.circuit_allows(now=120)
    asyncio.run(check())


def test_no_consent_and_permanent_fail_closed(tmp_path):
    async def check():
        jobs = store(tmp_path)
        plan = load_report_plan("natal")
        try:
            await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=False, now=1)
        except ValueError:
            pass
        else:
            raise AssertionError("missing consent allowed")
        ident = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True, now=2)
        assert await jobs.claim(worker_id="a", now=3)
        assert await jobs.reschedule(job_id=ident, worker_id="a", now=4,
                                     retry=False, error_code="invalid_provider_config")
        assert (await jobs.status(owner_id=1, job_id=ident, now=139))["status"] == "failed"
        assert await jobs.claim(worker_id="b", now=999) is None
    asyncio.run(check())


def test_crashed_worker_never_exceeds_max_lease_attempts(tmp_path):
    async def check():
        jobs = store(tmp_path)
        ident = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=100)
        for attempt, now in enumerate((101, 122, 143), start=1):
            claim = await jobs.claim(worker_id=f"worker-{attempt}", now=now)
            assert claim.job_id == ident and claim.attempt == attempt
        assert await jobs.claim(worker_id="worker-4", now=164) is None
        state = await jobs.status(owner_id=1, job_id=ident, now=164)
        assert state["status"] == "failed"
        assert state["error_code"] == "lease_exhausted"
    asyncio.run(check())



def test_explicit_failed_report_retry_is_owner_scoped_atomic_and_bounded(tmp_path):
    async def check():
        jobs = store(tmp_path)
        plan = load_report_plan("natal")
        job_id = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(),
                                    consent=True, now=100)
        assert await jobs.claim(worker_id="a", now=101)
        assert await jobs.reschedule(job_id=job_id, worker_id="a", retry=False,
                                     error_code="temporary_provider_failure", now=102)
        assert (await jobs.status(owner_id=1, job_id=job_id, now=104))["status"] == "failed"
        # This test exercises only the explicit retry path; a new report
        # would be a distinct queued job, covered in the fresh-generation test.
        assert not await jobs.retry_failed(owner_id=2, job_id=job_id, consent=True, now=106)
        assert not await jobs.retry_failed(owner_id=1, job_id=job_id, consent=False, now=106)
        outcomes = await asyncio.gather(*[
            jobs.retry_failed(owner_id=1, job_id=job_id, consent=True, now=107)
            for _ in range(2)
        ])
        assert sorted(outcomes) == [False, True]
        assert (await jobs.status(owner_id=1, job_id=job_id, now=107))["status"] == "queued"
        claim = await jobs.claim(worker_id="b", now=108)
        assert claim is not None and claim.job_id == job_id and claim.attempt == 1
        assert await jobs.reschedule(job_id=job_id, worker_id="b", retry=False,
                                     error_code="temporary_provider_failure", now=109)
        assert await jobs.retry_failed(owner_id=1, job_id=job_id, consent=True, now=110)
        claim_again = await jobs.claim(worker_id="c", now=111)
        assert claim_again is not None and claim_again.job_id == job_id
        assert await jobs.reschedule(job_id=job_id, worker_id="c", retry=False,
                                     error_code="temporary_provider_failure", now=112)
        assert not await jobs.retry_failed(owner_id=1, job_id=job_id, consent=True, now=113)
    asyncio.run(check())


def test_failed_legacy_report_can_use_one_additional_explicit_retry(tmp_path):
    """A paid retry consumed before the fix must not trap the admin forever."""
    async def check():
        jobs = store(tmp_path)
        job = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                 facts=facts(), consent=True, now=100)
        assert await jobs.claim(worker_id="first", now=101)
        assert await jobs.reschedule(job_id=job, worker_id="first", retry=False,
                                     error_code="temporary_provider_failure", now=102)
        assert await jobs.retry_failed(owner_id=1, job_id=job, consent=True, now=103)
        assert await jobs.claim(worker_id="legacy", now=104)
        assert await jobs.reschedule(job_id=job, worker_id="legacy", retry=False,
                                     error_code="temporary_provider_failure", now=105)
        assert (await jobs.status(owner_id=1, job_id=job, now=106))["retry_available"] is True
        assert not await jobs.retry_failed(owner_id=2, job_id=job, consent=True, now=106)
        outcomes = await asyncio.gather(*[
            jobs.retry_failed(owner_id=1, job_id=job, consent=True, now=107)
            for _ in range(2)
        ])
        assert sorted(outcomes) == [False, True]
        assert await jobs.claim(worker_id="recovery", now=108)
        assert await jobs.reschedule(job_id=job, worker_id="recovery", retry=False,
                                     error_code="temporary_provider_failure", now=109)
        assert (await jobs.status(owner_id=1, job_id=job, now=110))["retry_available"] is False
        assert not await jobs.retry_failed(owner_id=1, job_id=job, consent=True, now=110)

    asyncio.run(check())


def test_manual_retry_never_restarts_permanently_rejected_job(tmp_path):
    async def check():
        jobs = store(tmp_path)
        job_id = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                    facts=facts(), consent=True, now=100)
        assert await jobs.claim(worker_id="a", now=101)
        assert await jobs.reschedule(job_id=job_id, worker_id="a", retry=False,
                                     error_code="report_not_allowed", now=102)
        assert not await jobs.retry_failed(owner_id=1, job_id=job_id, consent=True, now=103)
        assert (await jobs.status(owner_id=1, job_id=job_id, now=103))["status"] == "failed"
    asyncio.run(check())


def test_two_concurrent_workers_cannot_claim_same_report(tmp_path):
    async def check():
        jobs = store(tmp_path)
        await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                           facts=facts(), consent=True, now=100)
        claims = await asyncio.gather(*(
            jobs.claim(worker_id=f"worker-{i}", now=101) for i in range(8)
        ))
        assert len([claim for claim in claims if claim is not None]) == 1
    asyncio.run(check())


def test_expired_report_can_be_recreated_without_reusing_purged_identity(tmp_path):
    async def check():
        jobs = store(tmp_path)
        first = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=100)
        second = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                    facts=facts(), consent=True, now=100 + 366 * 86400)
        assert second != first
        assert await jobs.status(owner_id=1, job_id=first, now=100 + 366 * 86400) is None
    asyncio.run(check())


def test_retention_purge_removes_sensitive_encrypted_job_data(tmp_path):
    async def check():
        jobs = store(tmp_path)
        ident = await jobs.enqueue(owner_id=1, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=100)
        assert await jobs.purge_expired(now=101) == 0
        assert await jobs.purge_expired(now=100 + 365 * 86400) == 1
        assert await jobs.status(owner_id=1, job_id=ident, now=100 + 365 * 86400) is None
    asyncio.run(check())


def test_report_history_is_owner_scoped_sorted_and_excludes_private_facts(tmp_path):
    async def check():
        jobs = store(tmp_path)
        natal = await jobs.enqueue(owner_id=11, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=100)
        karma = await jobs.enqueue(owner_id=11, plan=load_report_plan("karma"),
                                   facts={**facts(), "schema_version": "astro.karma-indicators.v1"},
                                   consent=True, now=102)
        other = await jobs.enqueue(owner_id=22, plan=load_report_plan("natal"),
                                   facts=facts(), consent=True, now=103)
        history = await jobs.list_owner(owner_id=11, limit=10, now=105)
        assert [entry["job_id"] for entry in history] == [karma, natal]
        assert [entry["service_id"] for entry in history] == ["karma", "natal"]
        assert all(entry["status"] == "queued" for entry in history)
        assert all("facts" not in entry and "report" not in entry for entry in history)
        assert all("sealed" not in key for entry in history for key in entry)
        assert all(entry["job_id"] != other for entry in history)
        assert (await jobs.list_owner(owner_id=22, now=105))[0]["job_id"] == other
        assert await jobs.list_owner(owner_id=33, now=105) == []
    asyncio.run(check())


def test_repeated_fresh_generations_use_distinct_checkpoint_namespaces(tmp_path):
    """New reports must not borrow a completed report or its paid sections."""
    from bot.services.astro_report_pipeline import report_fingerprint
    async def check():
        jobs = store(tmp_path)
        plan = load_report_plan("natal")
        a = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True, now=100)
        b = await jobs.enqueue(owner_id=1, plan=plan, facts=facts(), consent=True, now=101)
        assert a != b
        first = await jobs.claim(worker_id="first", now=102)
        second = await jobs.claim(worker_id="second", now=102)
        assert first is not None and second is not None
        assert first.fingerprint != second.fingerprint
        assert first.fingerprint == report_fingerprint(
            owner_id=1, plan=plan, facts=facts(), secret=jobs.fingerprint_secret,
            generation_id=first.job_id,
        )
        assert second.fingerprint == report_fingerprint(
            owner_id=1, plan=plan, facts=facts(), secret=jobs.fingerprint_secret,
            generation_id=second.job_id,
        )
        assert first.fingerprint != report_fingerprint(
            owner_id=1, plan=plan, facts=facts(), secret=jobs.fingerprint_secret,
        )
    asyncio.run(check())
