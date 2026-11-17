"""Worker executes entire reports and resumes after retry without redoing committed sections."""
import asyncio
import json
import time

from cryptography.fernet import Fernet

from bot.services.astro_kie_gpt6 import KieRetryableError
from bot.services.astro_report_jobs import AstroJobPolicy, AstroReportJobs
from bot.services.astro_report_pipeline import load_report_plan
from bot.services.astro_report_store import AstroReportSqlStore
from bot.services.astro_report_worker import AstroReportWorker


class Provider:
    def __init__(self):
        self.requests = []
        self.fail_once_at = 2

    async def analyze_text(self, *, user_instruction, system_prompt, json_response):
        section = json.loads(user_instruction)
        self.requests.append(section["section_id"])
        if len(self.requests) == self.fail_once_at:
            self.fail_once_at = -1
            raise KieRetryableError("fake 429")
        return json.dumps({"section_id": section["section_id"],
                           "text": "символический анализ " * (section["minimum_words"] + 10)})


def test_job_recovers_full_natal_after_provider_error_and_reuses_checkpoint(tmp_path, caplog):
    async def check():
        db_path = str(tmp_path / "reports.db")
        jobs = AstroReportJobs(
            db_path=db_path, fingerprint_secret="test-only-secret-for-hmac",
            data_key=Fernet.generate_key(),
            policy=AstroJobPolicy(retry_base_seconds=1, lease_seconds=20),
        )
        facts = {"schema_version": "astro.natal-facts.v1", "chart": {
            "bodies": {"Sun": {"lon": 11.2}},
        }}
        ident = await jobs.enqueue(owner_id=99, plan=load_report_plan("natal"),
                                   facts=facts, consent=True)
        provider = Provider()
        worker = AstroReportWorker(
            jobs=jobs, provider=provider,
            checkpoints=AstroReportSqlStore(db_path=db_path),
            is_admin=lambda owner: owner == 99,
        )
        assert await worker.run_once()
        assert (await jobs.status(owner_id=99, job_id=ident))["status"] == "queued"
        assert await worker.run_once(now=int(time.time()) + 5)
        response = await jobs.status(owner_id=99, job_id=ident)
        assert response["status"] == "completed"
        assert response["report"]["word_count"] >= 10000
        assert provider.requests.count(provider.requests[0]) == 1
        assert len(response["report"]["sections"]) == len(load_report_plan("natal").sections)
        assert await worker.run_once() is False
    with caplog.at_level('INFO', logger='bot.services.astro_report_worker'):
        asyncio.run(check())
    events = [record.getMessage() for record in caplog.records]
    assert any('astro_provider_call_started' in event for event in events)
    assert any('astro_provider_call_succeeded' in event for event in events)
    assert any('astro_provider_call_retryable' in event for event in events)
    assert all('fake 429' not in event and 'символический анализ' not in event for event in events)


def test_revoked_admin_blocks_provider_without_starting_generation(tmp_path):
    async def check():
        db_path = str(tmp_path / "reports.db")
        jobs = AstroReportJobs(db_path=db_path, fingerprint_secret="test-only-secret-for-hmac",
                               data_key=Fernet.generate_key())
        ident = await jobs.enqueue(owner_id=99, plan=load_report_plan("natal"),
                                   facts={"schema_version": "v1", "chart": {}}, consent=True)
        provider = Provider()
        worker = AstroReportWorker(jobs=jobs, provider=provider,
                                   checkpoints=AstroReportSqlStore(db_path=db_path),
                                   is_admin=lambda _: False)
        assert await worker.run_once()
        assert not provider.requests
        assert (await jobs.status(owner_id=99, job_id=ident))["status"] == "failed"
    asyncio.run(check())


def test_worker_loop_survives_temporary_queue_database_outage(monkeypatch):
    async def run():
        worker = AstroReportWorker(jobs=object(), provider=object(),
                                   checkpoints=object(), is_admin=lambda _: True)
        stop = asyncio.Event()
        called = []

        async def unstable_run_once():
            called.append(1)
            if len(called) == 1:
                raise OSError("temporary database connection dropped")
            stop.set()
            return False

        monkeypatch.setattr(worker, "run_once", unstable_run_once)
        monkeypatch.setenv("ASTRO_REPORT_POLL_SECONDS", "0.25")
        await asyncio.wait_for(worker.run_forever(stop), timeout=2)
        assert len(called) == 2
    asyncio.run(run())
