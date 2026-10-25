from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.services.neironych_wan3_service import (
    NeironychWan3Error,
    NeironychWan3Service,
    NeironychWan3Unsupported,
)
from bot.services.wan3_prime_lifecycle import LazyWan3PrimeTransport


def recipe(model="wan_3", scenario="reference", **prepared):
    defaults = {
        "prompt": "Animate @Image 1",
        "duration": 5,
        "resolution": "720P",
        "aspect_ratio": "16:9",
        "audio": True,
        "nsfw_checker": False,
    }
    defaults.update(prepared)
    return SimpleNamespace(
        model=model,
        scenario=scenario,
        prepared_input=defaults,
    )


def test_standard_payload_translates_every_supported_reference_type():
    payload = NeironychWan3Service.build_payload(
        recipe(
            reference_image_urls=["https://media/image.png"],
            reference_video_urls=["https://media/video.mp4"],
            reference_audio_urls=["https://media/audio.mp3"],
            audio=False,
            seed=42,
        )
    )
    assert payload == {
        "model": "wan-3",
        "prompt": "Animate @Image 1",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "generate_audio": False,
        "seed": 42,
        "reference_images": [{"url": "https://media/image.png"}],
        "reference_videos": [{"url": "https://media/video.mp4"}],
        "reference_audios": [{"url": "https://media/audio.mp3"}],
    }


def test_standard_frame_and_edit_payloads_follow_neironych_contract():
    frame = NeironychWan3Service.build_payload(
        recipe(
            scenario="first_last",
            first_frame_url="https://media/start.png",
            last_frame_url="https://media/end.png",
        )
    )
    assert "aspect_ratio" not in frame
    assert frame["start_image"] == {"url": "https://media/start.png"}
    assert frame["end_image"] == {"url": "https://media/end.png"}

    edit = NeironychWan3Service.build_payload(
        recipe(
            scenario="edit",
            duration=-1,
            aspect_ratio="adaptive",
            reference_video_urls=["https://media/source.mp4"],
        )
    )
    assert "duration" not in edit and "aspect_ratio" not in edit
    assert edit["omni_reference_task_type"] == "edit"


@pytest.mark.parametrize(
    "prepared",
    [
        {"reference_file_urls": ["https://media/file.pdf"]},
        {"reference_link_urls": ["https://example.com"]},
        {"nsfw_checker": True},
    ],
)
def test_incompatible_inputs_are_sent_to_fallback(prepared):
    with pytest.raises(NeironychWan3Unsupported):
        NeironychWan3Service.build_payload(recipe(**prepared))


@pytest.mark.parametrize(
    "scenario,prepared",
    [
        ("edit", {}),
        ("first_frame", {"first_frame_url": "https://media/start.png"}),
        ("text", {"duration": 3}),
        ("text", {"aspect_ratio": "4:3"}),
        ("text", {"seed": 42}),
        ("text", {"audio": False}),
    ],
)
def test_prime_contract_gaps_use_kie_fallback(scenario, prepared):
    with pytest.raises(NeironychWan3Unsupported):
        NeironychWan3Service.build_payload(
            recipe(model="wan_3_prime", scenario=scenario, **prepared)
        )


@pytest.mark.asyncio
async def test_status_is_normalized_for_shared_lifecycle():
    service = NeironychWan3Service(api_key="secret")
    service._request_json = AsyncMock(
        return_value=(
            200,
            {
                "request_id": "provider-id",
                "model": "wan-3",
                "status": "done",
                "video": {"url": "https://media/result.mp4"},
            },
        )
    )
    result = await service.get_task_status("neironych:provider-id")
    assert result == {
        "taskId": "neironych:provider-id",
        "model": "wan/3-0-video",
        "state": "success",
        "response": {"resultUrls": ["https://media/result.mp4"]},
    }


@pytest.mark.asyncio
async def test_submission_uses_stable_provider_and_client_ids():
    service = NeironychWan3Service(api_key="secret")
    service._request_json = AsyncMock(
        return_value=(202, {"request_id": "provider-id", "status": "pending"})
    )
    internal_id = "wan3_" + "d" * 32
    result = await service.create_task(recipe(), idempotency_key=internal_id)
    assert result["task_id"] == "neironych:provider-id"
    _method, _path = service._request_json.await_args.args
    headers = service._request_json.await_args.kwargs["headers"]
    assert headers["X-Client-Request-Id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert headers["Idempotency-Key"] == (
        "generation:dddddddd-dddd-dddd-dddd-dddddddddddd:provider:1"
    )


@pytest.mark.asyncio
async def test_malformed_ack_is_recovered_by_stable_client_id():
    service = NeironychWan3Service(api_key="secret")
    service._request_json = AsyncMock(
        side_effect=[
            NeironychWan3Error("non-object acknowledgement"),
            (200, {"request_id": "recovered-provider-id"}),
        ]
    )
    result = await service.create_task(
        recipe(), idempotency_key="wan3_" + "e" * 32
    )
    assert result["task_id"] == "neironych:recovered-provider-id"
    assert service._request_json.await_count == 2
    assert service._request_json.await_args_list[1].args[1] == (
        "/api/v1/generations/by-client-request-id/"
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )


@pytest.mark.asyncio
async def test_router_uses_neironych_for_all_shared_runtime_paths(monkeypatch):
    monkeypatch.setenv("WAN3_PRIMARY_PROVIDER", "neironych")
    primary = SimpleNamespace(
        enabled=True,
        create_task=AsyncMock(
            return_value={"success": True, "task_id": "neironych:provider-id"}
        ),
    )
    transport = LazyWan3PrimeTransport()
    transport._neironych = primary
    transport._create_kie = AsyncMock()
    result = await transport.create_task(
        recipe(), callback_url="https://callback", idempotency_key="wan3_" + "a" * 32
    )
    assert result["task_id"] == "neironych:provider-id"
    primary.create_task.assert_awaited_once()
    transport._create_kie.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_falls_back_only_after_definitive_primary_rejection(monkeypatch):
    monkeypatch.setenv("WAN3_PRIMARY_PROVIDER", "neironych")
    primary = SimpleNamespace(
        enabled=True,
        create_task=AsyncMock(side_effect=NeironychWan3Error("rejected", status=422)),
    )
    transport = LazyWan3PrimeTransport()
    transport._neironych = primary
    transport._create_kie = AsyncMock(
        return_value={"success": True, "task_id": "kie-id"}
    )
    result = await transport.create_task(
        recipe(), callback_url="https://callback", idempotency_key="wan3_" + "b" * 32
    )
    assert result["task_id"] == "kie-id"
    transport._create_kie.assert_awaited_once()

    primary.create_task.side_effect = TimeoutError("ambiguous")
    transport._create_kie.reset_mock()
    with pytest.raises(TimeoutError):
        await transport.create_task(
            recipe(),
            callback_url="https://callback",
            idempotency_key="wan3_" + "c" * 32,
        )
    transport._create_kie.assert_not_awaited()
