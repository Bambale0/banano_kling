from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from bot import db
from bot.services.seedance_provider_fallback import (
    resolve_seedance_status,
    submit_seedance,
)


@pytest.fixture
def neironych_primary(monkeypatch):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kie_market_service import KieMarketService

    monkeypatch.setenv("SEEDANCE_PRIMARY_PROVIDER", "neironych")
    monkeypatch.setenv("SEEDANCE_FALLBACK_PROVIDER", "kie")
    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "nr-primary"}
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(routing, "neironych_seedance_admin_service", client)
    monkeypatch.setattr(
        KieMarketService,
        "_get_json",
        AsyncMock(
            return_value={
                "code": 200,
                "data": {"taskId": "kie-secondary", "state": "generating"},
            }
        ),
    )
    return client


def primary_payload():
    return {
        "model": "bytedance/seedance-2-5",
        "input": {
            "prompt": "Person @Image1 wears clothing @Image2 following @Video1 with @Audio1",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "reference_image_urls": [
                "https://example.org/person.png",
                "https://example.org/dress.png",
            ],
            "reference_video_urls": ["https://example.org/motion.mp4"],
            "reference_audio_urls": ["https://example.org/audio.mp3"],
        },
        "callBackUrl": "https://example.org/private-callback",
    }


@pytest.mark.asyncio
async def test_neironych_primary_has_no_kie_create_and_waits_for_owner(
    neironych_primary,
):
    primary = AsyncMock(side_effect=AssertionError("KIE must not run first"))
    result = await submit_seedance(primary_payload(), primary)
    primary.assert_not_awaited()
    neironych_primary.submit.assert_not_awaited()
    await resolve_seedance_status(result["task_id"], AsyncMock())
    neironych_primary.submit.assert_not_awaited()
    await _attach(result["task_id"])
    record = await resolve_seedance_status(result["task_id"], AsyncMock())
    assert record["state"] == "generating"
    body = neironych_primary.submit.call_args.args[0]
    assert body["prompt"] == primary_payload()["input"]["prompt"]
    for kind in ["image", "video", "audio"]:
        assert [r["url"] for r in body["reference_" + kind + "s"]] == primary_payload()[
            "input"
        ]["reference_" + kind + "_urls"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [402, 422, "terminal"])
async def test_neironych_failure_falls_back_to_kie_once_with_stable_receipt(
    monkeypatch,
    neironych_primary,
    failure,
):
    import asyncio

    from bot.services import seedance_provider_fallback as routing
    from bot.services.kling_service import KlingService

    if failure == "terminal":
        neironych_primary.get_status.return_value = {"status": "failed"}
    else:
        neironych_primary.submit.side_effect = routing.NeironychAPIError(
            "rejected", status=failure
        )
    create = AsyncMock(return_value={"task_id": "kie-secondary"})
    monkeypatch.setattr(KlingService, "_kie_post", create)
    result = await _submit_and_attach(
        primary_payload(), AsyncMock(side_effect=AssertionError("early KIE"))
    )
    records = await asyncio.gather(
        *(resolve_seedance_status(result["task_id"], AsyncMock()) for _ in range(5))
    )
    assert all(r["state"] == "generating" for r in records)
    assert create.await_count == 1
    body = create.call_args.args[-1]
    assert body == {k: v for k, v in primary_payload().items() if k != "callBackUrl"}
    route = await routing._load(result["task_id"])
    assert route["request_id"] == "kie-secondary"
    assert route["phase"] == "kie_submitted"


@pytest.mark.asyncio
async def test_neironych_primary_uncertain_acceptance_never_launches_kie(
    monkeypatch, neironych_primary
):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kling_service import KlingService

    create = AsyncMock()
    monkeypatch.setattr(KlingService, "_kie_post", create)
    neironych_primary.submit.side_effect = TimeoutError()
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    monkeypatch.setattr(routing.time, "time", lambda: 9999999999)
    await resolve_seedance_status(result["task_id"], AsyncMock())
    assert neironych_primary.submit.await_count == 2
    assert (
        neironych_primary.submit.call_args_list[0]
        == neironych_primary.submit.call_args_list[1]
    )
    create.assert_not_awaited()
    assert await routing.has_unresolved_fallback(result["task_id"])


@pytest.mark.asyncio
async def test_kie_secondary_result_uses_local_task_id_and_never_polls_local_id_at_kie(
    monkeypatch, neironych_primary
):
    from bot.services.kie_market_service import KieMarketService
    from bot.services.kling_service import KlingService

    neironych_primary.get_status.return_value = {"status": "failed"}
    monkeypatch.setattr(
        KlingService, "_kie_post", AsyncMock(return_value={"task_id": "kie-secondary"})
    )
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    get = AsyncMock(
        return_value={
            "code": 200,
            "data": {
                "taskId": "kie-secondary",
                "state": "success",
                "resultJson": json.dumps(
                    {"resultUrls": ["https://example.org/result.mp4"]}
                ),
            },
        }
    )
    monkeypatch.setattr(KieMarketService, "_get_json", get)
    market = KieMarketService(api_key="synthetic")
    record = await market.get_task_status(result["task_id"])
    assert record["taskId"] == result["task_id"]
    assert record["state"] == "success"
    assert get.call_args.kwargs["params"] == {"taskId": "kie-secondary"}
    get.reset_mock()
    assert await market.get_task_status(result["task_id"]) == record
    get.assert_not_awaited()


@pytest.mark.asyncio
async def test_kie_uncertain_create_is_not_repeated_or_refunded(
    monkeypatch, neironych_primary
):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kling_service import KlingService

    neironych_primary.get_status.return_value = {"status": "failed"}
    create = AsyncMock(return_value={"error": "network_error"})
    monkeypatch.setattr(KlingService, "_kie_post", create)
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    monkeypatch.setattr(routing.time, "time", lambda: 9999999999)
    await resolve_seedance_status(result["task_id"], AsyncMock())
    assert create.await_count == 1
    assert await routing.has_unresolved_fallback(result["task_id"])


@pytest.mark.asyncio
async def test_secondary_never_launches_for_refunded_task(
    monkeypatch, neironych_primary
):
    from bot.services.kling_service import KlingService

    create = AsyncMock()
    monkeypatch.setattr(KlingService, "_kie_post", create)
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE generation_tasks SET status='failed' WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    neironych_primary.get_status.return_value = {"status": "failed"}
    await resolve_seedance_status(result["task_id"], AsyncMock())
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_primary_keeps_unsupported_controls_by_using_kie_before_submission(
    neironych_primary,
):
    payload = primary_payload()
    payload["input"]["generate_audio"] = False
    kie = AsyncMock(return_value={"task_id": "kie-compatible", "status": "pending"})
    assert (await submit_seedance(payload, kie))["task_id"] == "kie-compatible"
    kie.assert_awaited_once_with(payload)
    neironych_primary.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_primary_does_not_require_kie_key(
    monkeypatch, neironych_primary
):
    from bot.services.seedance_25_service import Seedance25Service

    service = Seedance25Service(kie_key="synthetic")
    service.kie_key = ""
    service._kie_post = AsyncMock(side_effect=AssertionError("KIE must not run first"))
    result = await service.generate_video(
        prompt="a blue paper boat", duration=4, resolution="480p", aspect_ratio="16:9"
    )
    assert result.get("provider") == "neironych"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [409, 500, 503])
async def test_neironych_primary_server_errors_keep_same_idempotency_key(
    monkeypatch, neironych_primary, status
):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kling_service import KlingService

    create = AsyncMock()
    monkeypatch.setattr(KlingService, "_kie_post", create)
    neironych_primary.submit.side_effect = routing.NeironychAPIError(
        "uncertain", status=status
    )
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    assert await routing.has_unresolved_fallback(result["task_id"])
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_inflight_primary_route_ignores_later_provider_config_change(
    monkeypatch, neironych_primary
):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kling_service import KlingService

    create = AsyncMock(return_value={"task_id": "kie-secondary"})
    monkeypatch.setattr(KlingService, "_kie_post", create)
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    monkeypatch.setenv("SEEDANCE_PRIMARY_PROVIDER", "kie")
    monkeypatch.setenv("SEEDANCE_FALLBACK_PROVIDER", "off")
    neironych_primary.get_status.return_value = {"status": "failed"}
    await resolve_seedance_status(result["task_id"], AsyncMock())
    assert create.await_count == 1
    assert (await routing._load(result["task_id"]))["phase"] == "kie_submitted"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["fail", "outage"])
async def test_kie_secondary_terminal_failure_or_outage_never_relaunches(
    monkeypatch, neironych_primary, state
):
    from bot.services import seedance_provider_fallback as routing
    from bot.services.kie_market_service import KieMarketService
    from bot.services.kling_service import KlingService

    create = AsyncMock(return_value={"task_id": "kie-secondary"})
    monkeypatch.setattr(KlingService, "_kie_post", create)
    neironych_primary.get_status.return_value = {"status": "failed"}
    result = await _submit_and_attach(primary_payload(), AsyncMock())
    await resolve_seedance_status(result["task_id"], AsyncMock())
    if state == "outage":
        monkeypatch.setattr(
            KieMarketService, "_get_json", AsyncMock(side_effect=TimeoutError())
        )
    else:
        monkeypatch.setattr(
            KieMarketService,
            "_get_json",
            AsyncMock(
                return_value={
                    "code": 200,
                    "data": {"taskId": "kie-secondary", "state": "fail"},
                }
            ),
        )
    record = await resolve_seedance_status(result["task_id"], AsyncMock())
    assert record["state"] == ("fail" if state == "fail" else "generating")
    assert await routing.has_unresolved_fallback(result["task_id"]) == (
        state == "outage"
    )
    assert create.await_count == 1
    assert neironych_primary.submit.await_count == 1


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDANCE_PRIMARY_PROVIDER", "kie")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "routes.db"))
    postgres_url = os.getenv("TEST_SEEDANCE_POSTGRES_URL", "")
    schema = "seedance_test_" + uuid.uuid4().hex
    if postgres_url:
        import psycopg
        from psycopg import sql

        with psycopg.connect(postgres_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            conn.execute(
                (
                    Path(__file__).resolve().parents[1] / "schema_postgres.sql"
                ).read_text()
            )
        monkeypatch.setenv(
            "DATABASE_URL", postgres_url + "?options=-csearch_path%3D" + schema
        )
    else:
        monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SEEDANCE_FALLBACK_PROVIDER", "neironych")
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "routes.db"))
    import sys

    if "bot.database" in sys.modules:
        monkeypatch.setattr(
            sys.modules["bot.database"], "DATABASE_PATH", str(tmp_path / "routes.db")
        )
    yield
    if postgres_url:
        from bot.postgres_pool import close_postgres_pool

        await close_postgres_pool()
        with psycopg.connect(postgres_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


async def _attach(task_id, model="seedance_2"):
    async with db.connect() as conn:
        if db.is_postgres():
            await conn.execute(
                "INSERT INTO users (id, telegram_id) VALUES (42, 987654321) ON CONFLICT DO NOTHING"
            )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS generation_tasks (id INTEGER PRIMARY KEY, user_id INTEGER, task_id TEXT UNIQUE, "
            "model TEXT, status TEXT, request_data TEXT, completed_at TEXT, updated_at TEXT, type TEXT, preset_id TEXT)"
        )
        await conn.execute(
            "INSERT INTO generation_tasks (id, user_id, task_id, model, status, request_data, type, preset_id) "
            "VALUES (1, 42, ?, ?, 'pending', '{}', 'video', 'test') ON CONFLICT (task_id) DO NOTHING",
            (task_id, model),
        )
        await conn.commit()


async def _submit_and_attach(payload, primary):
    result = await submit_seedance(payload, primary)
    if result.get("task_id"):
        await _attach(result["task_id"])
    return result


@pytest.mark.asyncio
async def test_explicit_primary_rejection_uses_neironych_and_persists_poll_route(
    monkeypatch,
):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "nr-request"}
    client.build_payload = fallback.NeironychSeedanceAdminService.build_payload
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    primary = AsyncMock(return_value={"error": "api_error", "status_code": 402})
    async with db.connect() as conn:
        execute_ddl = getattr(conn, "execute_native_ddl", conn.execute)
        await execute_ddl("DROP TABLE IF EXISTS seedance_provider_routes")
        await conn.commit()
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "paper boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(payload, primary)
    assert result["task_id"].startswith("seedance_nr_")
    assert result["provider"] == "neironych"
    assert client.submit.await_count == 0
    client.get_status.return_value = {"status": "pending"}
    record = await resolve_seedance_status(result["task_id"], AsyncMock())
    assert record["state"] == "generating"
    assert record["taskId"] == result["task_id"]
    assert client.submit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        {"error": "network_error", "status_code": 0},
        {"error": "invalid_json"},
        {"error": "no_task_id"},
        {"error": "api_error", "status_code": 422},
        {
            "error": "api_error",
            "status_code": 500,
            "raw": {"data": {"taskId": "accepted"}},
        },
    ],
)
async def test_unknown_acceptance_or_invalid_request_never_launches_second_provider(
    monkeypatch, failure
):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    result = await _submit_and_attach(
        {"model": "bytedance/seedance-2"}, AsyncMock(return_value=failure)
    )
    assert result == failure
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_primary_terminal_failure_switches_once_under_concurrency(
    monkeypatch,
):
    import asyncio

    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "nr-video"}
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2-5",
        "input": {
            "prompt": "Change clothing using @Image1, preserve @Video1",
            "duration": -1,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "reference_image_urls": ["https://example.org/person.png"],
            "reference_video_urls": ["https://example.org/source.mp4"],
            "omni_reference_task_type": "edit",
            "generate_audio": True,
        },
    }
    result = await _submit_and_attach(
        payload,
        AsyncMock(return_value={"task_id": "kie-accepted", "status": "pending"}),
    )
    assert result["task_id"] == "kie-accepted"
    client.submit.assert_not_awaited()
    primary = AsyncMock(
        return_value={
            "code": 200,
            "data": {"taskId": "kie-accepted", "state": "fail", "failCode": "500"},
        }
    )
    records = await asyncio.gather(
        *(resolve_seedance_status("kie-accepted", primary) for _ in range(5))
    )
    assert all(r["state"] == "generating" for r in records)
    assert client.submit.await_count == 1
    body = client.submit.call_args.args[0]
    assert body["model"] == "seedance-2.5"
    assert body["duration"] == -1
    assert body["omni_reference_task_type"] == "edit"
    assert body["reference_images"] == [{"url": "https://example.org/person.png"}]
    assert body["reference_videos"] == [{"url": "https://example.org/source.mp4"}]
    assert "generate_audio" not in body
    assert "web_search" not in body
    assert "output_format" not in body


@pytest.mark.asyncio
async def test_completed_fallback_becomes_persistent_public_result(
    monkeypatch, tmp_path
):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "nr-result"}
    client.get_status.return_value = {"status": "done"}
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic-video")
    client.download_to_temp.return_value = str(source)
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.chdir(tmp_path)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 429})
    )
    record = await resolve_seedance_status(result["task_id"], AsyncMock())
    assert record["state"] == "success"
    name = "seedance-fallback-" + hashlib.sha256(b"nr-result").hexdigest() + ".mp4"
    assert json.loads(record["resultJson"])["resultUrls"][0].endswith(
        "/uploads/seedance_fallback/" + name
    )
    assert (
        tmp_path / "static/uploads/seedance_fallback" / name
    ).read_bytes() == b"synthetic-video"
    client.reset_mock()
    assert await resolve_seedance_status(result["task_id"], AsyncMock()) == record
    client.get_status.assert_not_awaited()
    client.download_to_temp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["bytedance/seedance-2", "bytedance/seedance-2-5"])
async def test_public_seedance_adapters_use_shared_fallback(monkeypatch, model):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.kling_service import KlingService
    from bot.services.seedance_25_service import Seedance25Service
    from bot.services.seedance_service import SeedanceService

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "public-nr"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.setattr(
        KlingService,
        "_kie_post",
        AsyncMock(return_value={"error": "api_error", "status_code": 402}),
    )
    service = (
        SeedanceService(kie_key="synthetic")
        if model.endswith("-2")
        else Seedance25Service(kie_key="synthetic")
    )
    result = await service.generate_video(
        prompt="boat", duration=4, resolution="480p", aspect_ratio="16:9"
    )
    assert result["provider"] == "neironych"
    assert result["task_id"].startswith("seedance_nr_")


@pytest.mark.asyncio
async def test_uncertain_fallback_retries_same_idempotency_key_after_lease(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.side_effect = [TimeoutError(), {"request_id": "recovered"}]
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    assert await fallback.has_unresolved_fallback(result["task_id"])
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "generating"
    assert client.submit.await_count == 1
    monkeypatch.setattr(fallback.time, "time", lambda: 9999999999)
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "generating"
    assert client.submit.await_count == 2
    assert client.submit.call_args_list[0] == client.submit.call_args_list[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control",
    [
        {"generate_audio": False},
        {"return_last_frame": True},
        {"output_format": "mov"},
        {"web_search": True},
    ],
)
async def test_unsupported_controls_do_not_silently_change_generation(
    monkeypatch, control
):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2-5",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
            **control,
        },
    }
    rejection = {"error": "api_error", "status_code": 402}
    assert (
        await submit_seedance(payload, AsyncMock(return_value=rejection)) == rejection
    )
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_poller_reads_fallback_without_calling_kie(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.kie_market_service import KieMarketService

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "market-result"}
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    market = KieMarketService(api_key="synthetic")
    monkeypatch.setattr(
        market, "_get_json", AsyncMock(side_effect=AssertionError("must not poll KIE"))
    )
    record = await market.get_task_status(result["task_id"])
    assert record["taskId"] == result["task_id"]
    assert record["state"] == "generating"


@pytest.mark.asyncio
async def test_watchdog_does_not_refund_unresolved_fallback(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services import task_watchdog

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.side_effect = TimeoutError()
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", db.DATABASE_PATH)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    assert await task_watchdog.force_fail_task(1, 42, 10) is False
    async with db.connect() as conn:
        row = await (
            await conn.execute("SELECT status FROM generation_tasks WHERE id = 1")
        ).fetchone()
    assert row[0] == "pending"


@pytest.mark.asyncio
async def test_unowned_fallback_receipt_never_submits_paid_work(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    async with db.connect() as conn:
        await conn.execute(
            "DELETE FROM generation_tasks WHERE task_id = ?", (result["task_id"],)
        )
        await conn.commit()
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "generating"
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_refunded_primary_task_never_starts_paid_fallback(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    await _submit_and_attach(payload, AsyncMock(return_value={"task_id": "old-kie"}))
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE generation_tasks SET status = 'failed' WHERE task_id = 'old-kie'"
        )
        await conn.commit()
    data = {"taskId": "old-kie", "state": "fail", "failCode": "500"}
    assert (
        await resolve_seedance_status(
            "old-kie", AsyncMock(return_value={"code": 200, "data": data})
        )
        == data
    )
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_recognizes_terminal_fallback_failure_immediately(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services import task_watchdog

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "failed-fallback"}
    client.get_status.return_value = {"status": "failed"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", db.DATABASE_PATH)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    assert (
        await task_watchdog.check_task_with_provider(result["task_id"], "seedance_2")
        == "failed"
    )
    assert await task_watchdog.force_fail_task(1, 42, 0) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 502])
async def test_fallback_poll_outage_is_unresolved_and_does_not_abort_other_rows(
    monkeypatch, status
):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.kie_market_service import KieMarketService

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "poll-outage"}
    client.get_status.side_effect = fallback.NeironychAPIError(
        "synthetic status error", status=status
    )
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2-5",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    market = KieMarketService(api_key="synthetic")
    monkeypatch.setattr(
        market,
        "_get_json",
        AsyncMock(
            return_value={
                "code": 200,
                "data": {"taskId": "later-kie", "state": "success"},
            }
        ),
    )
    assert (await market.get_task_status(result["task_id"]))["state"] == "generating"
    assert (await market.get_task_status("later-kie"))["state"] == "success"


@pytest.mark.asyncio
async def test_failed_primary_poll_does_not_repeat_http_get(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.kie_market_service import KieMarketService

    client = AsyncMock()
    client.enabled = True
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    await _submit_and_attach(
        payload, AsyncMock(return_value={"task_id": "rate-limited-kie"})
    )
    market = KieMarketService(api_key="synthetic")
    request = AsyncMock(return_value={"code": 429, "msg": "rate limited"})
    monkeypatch.setattr(market, "_get_json", request)
    assert await market.get_task_status("rate-limited-kie") is None
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_successful_primary_retires_private_fallback_payload(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "private boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    await _submit_and_attach(payload, AsyncMock(return_value={"task_id": "done-kie"}))
    record = {
        "taskId": "done-kie",
        "state": "success",
        "resultJson": '{"resultUrls":["https://example.org/video.mp4"]}',
    }
    assert (
        await resolve_seedance_status(
            "done-kie", AsyncMock(return_value={"code": 200, "data": record})
        )
        == record
    )
    async with db.connect() as conn:
        row = await (
            await conn.execute(
                "SELECT COUNT(*) FROM seedance_provider_routes WHERE task_id = 'done-kie'"
            )
        ).fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_private_fallback_video_survives_real_upload_cleanup(
    monkeypatch, tmp_path
):
    import ast
    import logging
    import time

    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "durable-private-video"}
    client.get_status.return_value = {"status": "done"}
    source = tmp_path / "provider.mp4"
    source.write_bytes(b"synthetic-private-video")
    client.download_to_temp.return_value = str(source)
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.chdir(tmp_path)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    record = await resolve_seedance_status(result["task_id"], AsyncMock())
    url = json.loads(record["resultJson"])["resultUrls"][0]
    local = Path("static/uploads") / url.split("/uploads/", 1)[1]
    os.utime(local, (0, 0))
    tree = ast.parse((Path(__file__).resolve().parents[1] / "bot/main.py").read_text())
    cleanup = next(
        n for n in tree.body if getattr(n, "name", "") == "_remove_old_files"
    )
    loop = next(n for n in tree.body if getattr(n, "name", "") == "_cleanup_loop")
    call = next(
        n
        for n in ast.walk(loop)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "_remove_old_files"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "static/uploads"
    )
    excluded = ast.literal_eval(
        next(k.value for k in call.keywords if k.arg == "skip_dirnames")
    )
    namespace = {"os": os, "time": time, "logger": logging.getLogger("test-cleanup")}
    exec(  # noqa: S102 - execute the checked-in cleanup body in isolation
        compile(
            ast.Module(body=[cleanup], type_ignores=[]), "<real-upload-cleanup>", "exec"
        ),
        namespace,
    )
    await namespace["_remove_old_files"]("static/uploads", 1, skip_dirnames=excluded)
    assert local.read_bytes() == b"synthetic-private-video"


@pytest.mark.asyncio
async def test_missing_credentials_does_not_starve_later_status_rows(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "existing-request"}
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "private",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    await resolve_seedance_status(result["task_id"], AsyncMock())
    client.get_status.side_effect = RuntimeError("NEIRONYCH_API_KEY is not configured")
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "generating"


@pytest.mark.asyncio
async def test_permanently_unavailable_content_is_bounded_and_refundable(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.CONTENT_DOWNLOAD_ATTEMPTS = 3
    client.submit.return_value = {"request_id": "lost-content"}
    client.get_status.return_value = {"status": "done"}
    client.download_to_temp.side_effect = fallback.NeironychAPIError("gone", status=404)
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    monkeypatch.setenv("SEEDANCE_FALLBACK_CONTENT_ATTEMPTS", "2")
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "private boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "generating"
    assert (await resolve_seedance_status(result["task_id"], AsyncMock()))[
        "state"
    ] == "fail"
    assert not await fallback.has_unresolved_fallback(result["task_id"])
    async with db.connect() as conn:
        row = await (
            await conn.execute(
                "SELECT payload,fallback_payload FROM seedance_provider_routes WHERE task_id=?",
                (result["task_id"],),
            )
        ).fetchone()
    assert json.loads(row[0]) == {"model": "bytedance/seedance-2"}
    assert row[1] is None


@pytest.mark.asyncio
async def test_stale_unattached_route_is_pruned_but_active_route_is_kept(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback

    client = AsyncMock()
    client.enabled = True
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    payload = {
        "model": "bytedance/seedance-2",
        "input": {
            "prompt": "private boat",
            "duration": 4,
            "resolution": "480p",
            "aspect_ratio": "16:9",
        },
    }
    result = await _submit_and_attach(
        payload, AsyncMock(return_value={"error": "api_error", "status_code": 402})
    )
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE seedance_provider_routes SET created_at='2000-01-01' WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    assert await fallback.cleanup_seedance_routes() == 0
    async with db.connect() as conn:
        await conn.execute(
            "DELETE FROM generation_tasks WHERE task_id=?", (result["task_id"],)
        )
        await conn.commit()
    assert await fallback.cleanup_seedance_routes() == 1
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_seedance25_request_is_eligible_for_fallback(monkeypatch):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.seedance_25_service import Seedance25Service

    client = AsyncMock()
    client.enabled = True
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    service = Seedance25Service(kie_key="synthetic")
    monkeypatch.setattr(
        service,
        "_kie_post",
        AsyncMock(return_value={"error": "api_error", "status_code": 402}),
    )
    result = await service.generate_video(prompt="boat")
    assert result["provider"] == "neironych"
    assert service._kie_post.call_args.args[1]["input"]["aspect_ratio"] == "16:9"


@pytest.mark.asyncio
@pytest.mark.parametrize("ratio", ["16:9", "adaptive"])
@pytest.mark.parametrize("accepted", [False, True])
async def test_ordinary_auto_reference_never_turns_into_edit(
    monkeypatch, ratio, accepted
):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.seedance_25_service import Seedance25Service

    client = AsyncMock()
    client.enabled = True
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    service = Seedance25Service(kie_key="synthetic")
    primary_result = (
        {"task_id": "ordinary-auto-primary"}
        if accepted
        else {"error": "api_error", "status_code": 402}
    )
    monkeypatch.setattr(service, "_kie_post", AsyncMock(return_value=primary_result))
    result = await service.generate_video(
        prompt="Create a new scene inspired by @Video1",
        duration=-1,
        aspect_ratio=ratio,
        reference_video_urls=["https://example.org/reference.mp4"],
        video_editing=False,
    )
    if accepted:
        await _attach(result["task_id"], "seedance_2_5")
        terminal = {"taskId": result["task_id"], "state": "fail", "failCode": "500"}
        assert (
            await resolve_seedance_status(
                result["task_id"],
                AsyncMock(return_value={"code": 200, "data": terminal}),
            )
            == terminal
        )
    else:
        assert result.get("error") == "api_error"
        assert result.get("provider") != "neironych"
    client.submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_explicit_video_edit_intent_reaches_fallback_without_changing_kie_wire(
    monkeypatch, accepted
):
    from bot.services import seedance_provider_fallback as fallback
    from bot.services.seedance_25_service import Seedance25Service

    client = AsyncMock()
    client.enabled = True
    client.timeout_seconds = 120
    client.submit.return_value = {"request_id": "explicit-edit"}
    client.get_status.return_value = {"status": "pending"}
    monkeypatch.setattr(fallback, "neironych_seedance_admin_service", client)
    service = Seedance25Service(kie_key="synthetic")
    primary_result = (
        {"task_id": "explicit-edit-primary"}
        if accepted
        else {"error": "api_error", "status_code": 402}
    )
    primary = AsyncMock(return_value=primary_result)
    monkeypatch.setattr(service, "_kie_post", primary)
    result = await service.generate_video(
        prompt="Edit @Video1",
        duration=4,
        aspect_ratio="16:9",
        reference_video_urls=["https://example.org/source.mp4"],
        video_editing=True,
    )
    if not accepted:
        assert result["provider"] == "neironych"
    assert "_seedance_edit_intent" not in primary.call_args.args[1]
    await _attach(result["task_id"], "seedance_2_5")
    get_primary = AsyncMock(
        return_value={
            "code": 200,
            "data": {"taskId": result["task_id"], "state": "fail"},
        }
    )
    assert (await resolve_seedance_status(result["task_id"], get_primary))[
        "state"
    ] == "generating"
    body = client.submit.call_args.args[0]
    assert body["duration"] == -1
    assert body["aspect_ratio"] == "adaptive"
    assert body["omni_reference_task_type"] == "edit"
