"""Independent report sections overlap without losing checkpoints or authorization."""
import asyncio
import json

import pytest
from cryptography.fernet import Fernet

from bot.services.astro_kie_gpt6 import KieRetryableError
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_pipeline import ReportPlan, SectionSpec, compose_report
from bot.services.astro_report_store import AstroReportSqlStore
from bot.services.astro_report_worker import AstroReportWorker
from tests.test_astro_report_pipeline import Checkpoints, facts


def parallel_plan(count=7):
    return ReportPlan("natal", "parallel-test", "Только проверенные факты.", tuple(
        SectionSpec(f"part_{i}", f"Раздел {i}", "Символическая интерпретация.", 5)
        for i in range(count)
    ), count * 5)


def response(payload):
    return json.dumps({"section_id": payload["section_id"],
                       "text": "Символическая интерпретация проверенных данных. " *
                       (payload["minimum_words"] + 1)})


async def compose(store, provider, count=7):
    return await compose_report(owner_id=19, plan=parallel_plan(count), facts=facts(),
                                secret="parallel-fixture-secret", store=store,
                                provider=provider)


def test_independent_sections_overlap_with_bound_and_keep_report_order(monkeypatch):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "3")

    async def run():
        ready, release, last, others_done = (asyncio.Event() for _ in range(4))
        active = peak = finished_others = 0
        started = []

        class Provider:
            async def analyze_text(self, **kwargs):
                nonlocal active, peak, finished_others
                payload = json.loads(kwargs["user_instruction"])
                started.append(payload["section_id"])
                active += 1
                peak = max(peak, active)
                if len(started) == 3:
                    ready.set()
                try:
                    await release.wait()
                    if payload["section_id"] == "part_0":
                        await last.wait()
                    else:
                        finished_others += 1
                        if finished_others == 6:
                            others_done.set()
                    return response(payload)
                finally:
                    active -= 1

        store = Checkpoints()
        task = asyncio.create_task(compose(store, Provider()))
        try:
            await asyncio.wait_for(ready.wait(), 1)
            assert peak == 3
            release.set()
            await asyncio.wait_for(others_done.wait(), 1)
            assert not task.done()
            last.set()
            result = await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert [item["id"] for item in result["sections"]] == [
            f"part_{i}" for i in range(7)
        ]
        assert len(store.saved) == 7 and active == 0 and peak == 3

    asyncio.run(run())


def test_failure_drains_started_calls_and_resume_reuses_their_checkpoints(monkeypatch):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "3")

    async def run():
        ready, release, failed, finish = (asyncio.Event() for _ in range(4))
        started, cancelled = [], []

        class Failing:
            async def analyze_text(self, **kwargs):
                payload = json.loads(kwargs["user_instruction"])
                section = payload["section_id"]
                started.append(section)
                if len(started) == 3:
                    ready.set()
                try:
                    await release.wait()
                    if section == "part_0":
                        failed.set()
                        raise KieRetryableError("synthetic temporary failure")
                    await finish.wait()
                    return response(payload)
                except asyncio.CancelledError:
                    cancelled.append(section)
                    raise

        store = Checkpoints()
        task = asyncio.create_task(compose(store, Failing(), 5))
        try:
            await asyncio.wait_for(ready.wait(), 1)
            release.set()
            await asyncio.wait_for(failed.wait(), 1)
            assert not task.done()
            finish.set()
            with pytest.raises(KieRetryableError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert set(started) == {"part_0", "part_1", "part_2"}
        assert not cancelled
        assert {key[2] for key in store.saved} == {"part_1", "part_2"}
        resumed = []

        class Healthy:
            async def analyze_text(self, **kwargs):
                payload = json.loads(kwargs["user_instruction"])
                resumed.append(payload["section_id"])
                return response(payload)

        assert (await compose(store, Healthy(), 5))["status"] == "completed"
        assert set(resumed) == {"part_0", "part_3", "part_4"}

    asyncio.run(run())


def test_cancellation_joins_all_started_provider_calls(monkeypatch):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "3")

    async def run():
        ready, never = asyncio.Event(), asyncio.Event()
        active = 0

        class Provider:
            async def analyze_text(self, **_):
                nonlocal active
                active += 1
                if active == 3:
                    ready.set()
                try:
                    await never.wait()
                finally:
                    active -= 1

        task = asyncio.create_task(compose(Checkpoints(), Provider()))
        try:
            await asyncio.wait_for(ready.wait(), 1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert active == 0

    asyncio.run(run())


@pytest.mark.parametrize("value", ["0", "-1", "9", "invalid"])
def test_invalid_parallel_budget_fails_before_provider_calls(monkeypatch, value):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", value)

    class Provider:
        async def analyze_text(self, **_):
            pytest.fail("Invalid configuration must not start a paid call")

    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(compose(Checkpoints(), Provider()))


def test_workers_share_provider_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "4")

    async def run():
        path = str(tmp_path / "queue.db")
        jobs = AstroReportJobs(db_path=path, fingerprint_secret="parallel-worker-fixture",
                               data_key=Fernet.generate_key())
        from bot.services.astro_report_pipeline import load_report_plan
        ids = [await jobs.enqueue(owner_id=19, plan=load_report_plan("natal"),
                                  facts=facts(), consent=True) for _ in range(2)]
        ready, release = asyncio.Event(), asyncio.Event()
        active = peak = 0

        class Provider:
            async def analyze_text(self, **kwargs):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                if active == 2:
                    ready.set()
                try:
                    await release.wait()
                    await asyncio.sleep(0)
                    return response(json.loads(kwargs["user_instruction"]))
                finally:
                    active -= 1

        limiter, provider = asyncio.Semaphore(2), Provider()
        workers = [AstroReportWorker(jobs=jobs, provider=provider,
                    checkpoints=AstroReportSqlStore(db_path=path), is_admin=lambda _: True,
                    provider_limiter=limiter) for _ in range(2)]
        tasks = [asyncio.create_task(worker.run_once()) for worker in workers]
        try:
            await asyncio.wait_for(ready.wait(), 2)
            assert peak == 2
            release.set()
            assert all(await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert peak == 2 and active == 0
        for job_id in ids:
            assert (await jobs.status(owner_id=19, job_id=job_id))["status"] == "completed"

    asyncio.run(run())


def test_role_is_rechecked_after_waiting_for_provider_slot(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "4")

    async def run():
        from bot.services.astro_report_pipeline import load_report_plan
        path = str(tmp_path / "revoked.db")
        jobs = AstroReportJobs(db_path=path, fingerprint_secret="parallel-revocation-fixture",
                               data_key=Fernet.generate_key())
        job_id = await jobs.enqueue(owner_id=19, plan=load_report_plan("natal"),
                                    facts=facts(), consent=True)
        waiting = asyncio.Event()
        current = {"admin": True}

        class Limiter(asyncio.Semaphore):
            async def __aenter__(self):
                waiting.set()
                return await super().__aenter__()

        class Provider:
            async def analyze_text(self, **_):
                pytest.fail("Revoked owner must not send facts after waiting for a slot")

        limiter = Limiter(1)
        await limiter.acquire()
        worker = AstroReportWorker(jobs=jobs, provider=Provider(),
                    checkpoints=AstroReportSqlStore(db_path=path),
                    is_admin=lambda _: current["admin"], provider_limiter=limiter)
        task = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            current["admin"] = False
            limiter.release()
            assert await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        status = await jobs.status(owner_id=19, job_id=job_id)
        assert status["status"] == "failed" and status["error_code"] == "report_not_allowed"

    asyncio.run(run())


def test_changing_parallel_budget_reuses_existing_checkpoint_identity(monkeypatch):
    store = Checkpoints()

    class Provider:
        async def analyze_text(self, **kwargs):
            return response(json.loads(kwargs["user_instruction"]))

    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "1")
    first = asyncio.run(compose(store, Provider()))

    class NoPaidCalls:
        async def analyze_text(self, **_):
            pytest.fail("Changing scheduling must not regenerate completed sections")

    monkeypatch.setenv("ASTRO_REPORT_SECTION_CONCURRENCY", "4")
    second = asyncio.run(compose(store, NoPaidCalls()))
    assert second == first and len(store.saved) == 7
