"""Seven complete versioned reports: HTTP -> queue -> worker -> HTTP replay.

Uses synthetic actor/factual inputs and deterministic long-text fixture; no
KIE billing and no real customer data. Entire output, not one section.
"""
import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from bot import astro_report_api, miniapp
from bot.config import config
from bot.services.astro_encrypted_checkpoint import EncryptedCheckpointStore
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_store import AstroReportSqlStore
from bot.services.astro_report_worker import AstroReportWorker
from tests.test_astro_seven_complete_reports import LongFormFixtureProvider, fixtures

SERVICES = ("natal", "compatibility", "karma", "year", "month", "solar", "lunar")


def test_seven_complete_reports_survive_sql_restart_and_are_readable_only_to_owner(tmp_path):
    async def run():
        db_file = str(tmp_path / "astro.db")
        key = Fernet.generate_key()
        jobs = AstroReportJobs(db_path=db_file, fingerprint_secret="test-astro-complete-secret",
                               data_key=key)
        app = web.Application()
        astro_report_api.setup_astro_report_routes(app, "/mini-app", initialize_worker=False)
        app[astro_report_api.ASTRO_REPORT_JOBS] = jobs
        provider = LongFormFixtureProvider()

        async def actor(_app, token):
            if token == "test-first":
                return 101, {"platform": "telegram"}
            if token == "test-other":
                return 102, {"platform": "telegram"}
            raise ValueError("invalid test token")

        async def facts(service, _input):
            return fixtures(service)

        with (patch.object(miniapp, "_get_user_context", actor),
              patch.object(config, "is_admin", lambda _: True),
              patch.object(astro_report_api, "calculate_verified_facts", facts)):
            async with TestClient(TestServer(app)) as client:
                ids = {}
                for service in SERVICES:
                    result = await client.post("/mini-app/api/astro/reports/start", json={
                        "init_data": "test-first", "service_id": service,
                        "input": {"test": True}, "consent": True,
                    })
                    assert result.status == 202, (service, await result.text())
                    ids[service] = (await result.json())["job_id"]
                worker = AstroReportWorker(
                    jobs=jobs, provider=provider,
                    checkpoints=EncryptedCheckpointStore(
                        AstroReportSqlStore(db_path=db_file), key=key,
                    ),
                    is_admin=lambda owner: owner == 101,
                )
                for service in SERVICES:
                    assert await worker.run_once(), service
                assert not await worker.run_once()
                assert len(ids) == len(set(ids.values()))
                for service, ident in ids.items():
                    query = {"init_data": "test-first", "job_id": ident}
                    reply = await client.post("/mini-app/api/astro/reports/status", json=query)
                    assert reply.status == 200
                    output = await reply.json()
                    assert output["status"] == "completed", service
                    assert output["service_id"] == service
                    assert output["report"]["service_id"] == service
                    assert output["report"]["word_count"] >= 5000
                    denied = await client.post("/mini-app/api/astro/reports/status", json={
                        "init_data": "test-other", "job_id": ident,
                    })
                    assert denied.status == 404
                assert "символическая".encode() not in (
                    tmp_path / "astro.db"
                ).read_bytes()
                count = len(provider.section_ids)
                second = await client.post("/mini-app/api/astro/reports/start", json={
                    "init_data": "test-first", "service_id": "natal",
                    "input": {}, "consent": True,
                })
                assert (await second.json())["job_id"] == ids["natal"]
                assert len(provider.section_ids) == count
        # Independent store instance proves persistence across worker restart.
        restarted = AstroReportJobs(db_path=db_file, fingerprint_secret="test-astro-complete-secret",
                                    data_key=key)
        assert (await restarted.status(owner_id=101, job_id=ids["lunar"]))["report"]["status"] == "completed"
    asyncio.run(run())
