"""Wan 3 production routing regression: native Neironych with safe KIE compatibility."""
from unittest.mock import AsyncMock

import pytest

from bot.services.wan3_neironych_runtime import (
    NEIRONYCH_TASK_PREFIX,
    Wan3NeironychRuntimeTransport,
    NeironychWan3RuntimeService,
    native_payload_for_recipe,
)
from bot.services.wan3_prime_media import Wan3PrimeRecipe


def recipe(*, model="wan_3", scenario="text", **overrides):
    data = {
        "model": model,
        "scenario": scenario,
        "prompt": "A small red tram moves through the city",
        "duration": 5,
        "resolution": "720P",
        "aspect_ratio": "16:9",
        "audio": True,
        "provider_submission_id": "wan3_1234567890abcdef",
        "prepared_input": {
            "prompt": "A small red tram moves through the city",
            "duration": 5,
            "resolution": "720P",
            "aspect_ratio": "16:9",
            "audio": True,
            "nsfw_checker": False,
        },
    }
    data.update(overrides)
    return Wan3PrimeRecipe(**data)


def test_native_text_payload_is_not_kie_wire_format():
    assert native_payload_for_recipe(recipe()) == {
        "model": "wan-3",
        "prompt": "A small red tram moves through the city",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
    }
    assert native_payload_for_recipe(recipe(model="wan_3_prime"))["model"] == "wan-3-prime"


def test_native_frames_and_reference_mapping():
    url = "https://media.example.org/start.jpg"
    first = recipe(
        scenario="first_frame",
        first_frame_url=url,
        prepared_input={
            "prompt": "A small red tram moves through the city",
            "duration": 5, "resolution": "720P", "aspect_ratio": "16:9",
            "first_frame_url": url, "audio": True, "nsfw_checker": False,
        },
    )
    assert native_payload_for_recipe(first)["start_image"] == {"url": url}

    references = recipe(
        scenario="reference",
        reference_image_urls=[url],
        prepared_input={
            "prompt": "Show the tram from @Image 1",
            "duration": 5, "resolution": "720P", "aspect_ratio": "16:9",
            "reference_image_urls": [url], "audio": True, "nsfw_checker": False,
        },
    )
    assert native_payload_for_recipe(references)["reference_images"] == [{"url": url}]


@pytest.mark.parametrize("changes", [
    {"model": "wan_3_prime", "scenario": "first_frame"},
    {"model": "wan_3_prime", "scenario": "edit"},
    {"model": "wan_3_prime", "aspect_ratio": "adaptive"},
    {"model": "wan_3_prime", "audio": False},
    {"model": "wan_3_prime", "seed": 12},
    {"scenario": "edit", "duration": 20, "aspect_ratio": "9:16"},
    {"scenario": "edit", "duration": 5, "aspect_ratio": "16:9"},
    {"duration": -1},
    {"reference_file_urls": ["https://media.example.org/a.pdf"]},
    {"nsfw_checker": True},
])
def test_unsupported_native_contract_is_not_silently_degraded(changes):
    original = recipe(**changes)
    assert native_payload_for_recipe(original) is None


@pytest.mark.asyncio
async def test_native_acceptance_is_idempotent_and_status_is_persistently_routable():
    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3", "wan-3-prime"}
    native.submit.return_value = {"request_id": "req123abc", "status": "pending"}
    native.get_status.return_value = {"request_id": "req123abc", "model": "wan-3", "status": "done"}
    kie = AsyncMock()
    transport = Wan3NeironychRuntimeTransport(
        kie=kie, neironych=native, primary_provider=lambda: "neironych",
        record_attempt=AsyncMock(),
    )
    result = await transport.create_task(recipe(), callback_url="https://example.org/callback")
    assert result["task_id"] == NEIRONYCH_TASK_PREFIX + "req123abc"
    assert native.submit.await_args.kwargs["idempotency_key"] == "wan3_1234567890abcdef"
    assert native.submit.await_args.args[0]["model"] == "wan-3"
    kie.create_task.assert_not_awaited()
    status = await transport.get_task_status(result["task_id"])
    assert status["taskId"] == result["task_id"]
    assert status["state"] == "success"
    assert status["model"] == "wan/3-0-video"
    kie.get_task_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_transport_preserves_old_kie_tasks_and_unsupported_prime():
    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3", "wan-3-prime"}
    kie = AsyncMock()
    kie.create_task.return_value = {"task_id": "legacy123"}
    kie.get_task_status.return_value = {"taskId": "legacy123", "state": "success"}
    transport = Wan3NeironychRuntimeTransport(
        kie=kie, neironych=native, primary_provider=lambda: "neironych",
        record_attempt=AsyncMock(),
    )
    old = await transport.get_task_status("legacy123")
    assert old["taskId"] == "legacy123"
    result = await transport.create_task(recipe(model="wan_3_prime", aspect_ratio="adaptive"), callback_url=None)
    assert result["task_id"] == "legacy123"
    native.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_native_submit_never_starts_second_paid_kie_task():
    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3", "wan-3-prime"}
    native.submit.side_effect = TimeoutError("request may have been accepted")
    kie = AsyncMock()
    transport = Wan3NeironychRuntimeTransport(
        kie=kie, neironych=native, primary_provider=lambda: "neironych",
        record_attempt=AsyncMock(),
    )
    with pytest.raises(TimeoutError):
        await transport.create_task(recipe(), callback_url=None)
    kie.create_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 402, 403, 404, 422])
async def test_definitive_native_rejection_reports_failure_for_exactly_once_refund(code):
    from bot.services.neironych_seedance_admin_service import NeironychAPIError

    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3"}
    native.submit.side_effect = NeironychAPIError("definitive validation rejection", status=code)
    kie = AsyncMock()
    transport = Wan3NeironychRuntimeTransport(
        kie=kie, neironych=native, primary_provider=lambda: "neironych",
        record_attempt=AsyncMock(),
    )
    result = await transport.create_task(recipe(), callback_url=None)
    assert result["success"] is False
    assert result["error"] == "api_error"
    assert result["status_code"] == code
    kie.create_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [429, 500, 503])
async def test_uncertain_native_response_does_not_switch_provider_or_refund(code):
    from bot.services.neironych_seedance_admin_service import NeironychAPIError

    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3"}
    native.submit.side_effect = NeironychAPIError("ambiguous upstream response", status=code)
    kie = AsyncMock()
    transport = Wan3NeironychRuntimeTransport(
        kie=kie, neironych=native, primary_provider=lambda: "neironych",
        record_attempt=AsyncMock(),
    )
    with pytest.raises(NeironychAPIError):
        await transport.create_task(recipe(), callback_url=None)
    kie.create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_admission_sets_stable_client_lineage_and_idempotency():
    client = NeironychWan3RuntimeService(api_key="test-only")
    client._request_json = AsyncMock(return_value=(202, {
        "request_id": "req_123", "client_request_id": "wan3_1234567890abcdef",
    }))
    await client.submit(
        {"model": "wan-3", "prompt": "Scene"},
        idempotency_key="wan3_1234567890abcdef",
    )
    data = client._request_json.await_args.kwargs
    assert data["headers"]["Idempotency-Key"] == "wan3_1234567890abcdef"
    assert data["headers"]["X-Client-Request-Id"] == "wan3_1234567890abcdef"
    assert data["headers"]["X-Submission-Receipt"] == "v1"


@pytest.mark.asyncio
async def test_native_lookup_returns_authenticated_lineage_and_404_is_ambiguous():
    from bot.services.neironych_seedance_admin_service import NeironychAPIError

    client = NeironychWan3RuntimeService(api_key="test-only")
    client._request_json = AsyncMock(return_value=(200, {
        "id": "req_123", "client_request_id": "wan3_test",
        "idempotency_key": "wan3_test", "model_slug": "wan-3",
    }))
    record = await client.lookup_by_client_id("wan3_test")
    assert record["id"] == "req_123"
    assert client._request_json.await_args.kwargs["path"] == (
        "/api/v1/generations/by-client-request-id/wan3_test"
    )
    client._request_json.side_effect = NeironychAPIError("not found", status=404)
    assert await client.lookup_by_client_id("wan3_test") is None


def test_native_recovery_requires_proven_same_partner_model_and_client_id():
    from bot.services.wan3_prime_recovery import matches_submission, verified_native_candidate

    row = {"internal_task_id": "wan3_test", "provider_model": "wan/3-0-video"}
    returned = {"id": "req_123", "client_request_id": "wan3_test",
                "idempotency_key": "wan3_test", "model_slug": "wan-3"}
    assert verified_native_candidate(row, returned) == "neironych:req_123"
    assert verified_native_candidate(row, {**returned, "client_request_id": "someone_else"}) is None
    assert verified_native_candidate(row, {**returned, "model_slug": "wan-3-prime"}) is None
    assert verified_native_candidate(row, {**returned, "idempotency_key": "wrong"}) is None
    canonical = {"taskId": "neironych:req_123", "source": "neironych",
                 "model": "wan/3-0-video", "client_request_id": "wan3_test"}
    assert matches_submission(row, canonical) is True
    assert matches_submission(row, {**canonical, "client_request_id": "other"}) is False


@pytest.mark.asyncio
async def test_native_never_posts_or_reserves_on_failed_route_persistence():
    native = AsyncMock()
    native.enabled = True
    native.list_enabled_wan_models.return_value = {"wan-3"}
    attempted = AsyncMock(side_effect=RuntimeError("database temporarily unavailable"))
    kie = AsyncMock()
    transport = Wan3NeironychRuntimeTransport(
        kie=kie,
        neironych=native,
        primary_provider=lambda: "neironych",
        record_attempt=attempted,
    )
    result = await transport.create_task(recipe(), callback_url=None)
    assert result["error"] == "api_error"
    assert result["success"] is False
    native.submit.assert_not_awaited()
    kie.create_task.assert_not_awaited()
