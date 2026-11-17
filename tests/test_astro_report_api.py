"""Authenticated job request lifecycle with only synthetic Telegram actors."""
import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from bot import astro_report_api, miniapp
from bot.config import config
from bot.services.astro_report_jobs import AstroReportJobs


def test_report_start_requires_consent_and_deduplicates_by_verified_facts(tmp_path):
    async def run():
        async def synthetic_actor(_app, init_data):
            if init_data == "fixture-actor-one":
                return 101, {"platform": "telegram"}
            if init_data == "fixture-actor-two":
                return 202, {"platform": "telegram"}
            raise ValueError("synthetic signature rejected")

        async def verified(service, inputs):
            assert service == "natal"
            assert inputs == {"place_id": 498817, "date": "29.02.2000"}
            return {"schema_version": "astro.natal-facts.v1", "chart": {"bodies": {"Sun": {"lon": 3}}}}

        app = web.Application()
        astro_report_api.setup_astro_report_routes(app, "/mini-app", initialize_worker=False)
        app[astro_report_api.ASTRO_REPORT_JOBS] = AstroReportJobs(
            db_path=str(tmp_path / "queue.db"), data_key=Fernet.generate_key(),
            fingerprint_secret="synthetic-queue-secret",
        )
        with (patch.object(miniapp, "_get_user_context", synthetic_actor),
              patch.object(config, "is_admin", lambda _: True),
              patch.object(astro_report_api, "calculate_verified_facts", verified)):
            async with TestClient(TestServer(app)) as client:
                path = "/mini-app/api/astro/reports/start"
                body = {"init_data": "fixture-actor-one", "service_id": "natal",
                        "input": {"place_id": 498817, "date": "29.02.2000"}, "consent": True}
                missing_consent = await client.post(path, json={**body, "consent": False})
                assert missing_consent.status == 400
                first = await client.post(path, json=body)
                assert first.status == 202, await first.text()
                job_id = (await first.json())["job_id"]
                second = await client.post(path, json=body)
                assert second.status == 202 and (await second.json())["job_id"] == job_id
                status = "/mini-app/api/astro/reports/status"
                own = await client.post(status, json={"init_data": "fixture-actor-one", "job_id": job_id})
                assert own.status == 200 and (await own.json())["status"] == "queued"
                other = await client.post(status, json={"init_data": "fixture-actor-two", "job_id": job_id})
                assert other.status == 404
                unsigned = await client.post(path, json={**body, "init_data": ""})
                assert unsigned.status == 401
                history_path = "/mini-app/api/astro/reports/history"
                history = await client.post(history_path, json={
                    "init_data": "fixture-actor-one", "service_id": "natal",
                })
                assert history.status == 200
                items = (await history.json())["jobs"]
                assert len(items) == 1 and items[0]["job_id"] == job_id
                assert "facts" not in items[0] and "report" not in items[0]
                other_history = await client.post(history_path, json={
                    "init_data": "fixture-actor-two", "service_id": "natal",
                })
                assert other_history.status == 200
                assert (await other_history.json())["jobs"] == []
                denied_history = await client.post(history_path, json={
                    "init_data": "", "service_id": "natal",
                })
                assert denied_history.status == 401
    asyncio.run(run())
