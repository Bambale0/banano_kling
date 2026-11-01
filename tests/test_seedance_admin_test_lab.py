import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from aiohttp import web

from bot.handlers import admin_seedance_test_lab
from bot.services.neironych_seedance_admin_service import (
    NeironychAPIError,
    NeironychSeedanceAdminService,
)

ROOT = Path(__file__).resolve().parents[1]


def test_seedance_admin_test_is_exposed_from_existing_test_lab():
    source = (ROOT / "bot/handlers/admin_test_lab.py").read_text(encoding="utf-8")
    assert 'callback_data="admin_seedance_lab"' in source
    assert "Seedance API" in source


def test_seedance_admin_router_is_wired_into_admin_router():
    source = (ROOT / "bot/handlers/__init__.py").read_text(encoding="utf-8")
    assert "admin_seedance_test_lab_router" in source
    assert "admin_router.include_router(admin_seedance_test_lab_router)" in source


def test_seedance_admin_test_has_full_documented_model_surface_and_no_rox_billing():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    service = (
        ROOT / "bot/services/neironych_seedance_admin_service.py"
    ).read_text(encoding="utf-8")

    for model in (
        "seedance-2.5",
        "seedance-2.0",
        "seedance-2.0-mini",
        "seedance-2.0-fast",
    ):
        assert model in source
        assert model in service

    assert "admin_seedance_generate" in source
    assert "admin_seedance_check" in source
    assert "list_enabled_seedance_models" in source
    assert "download_to_temp" in source
    assert "Idempotency-Key" in service
    assert "deduct" not in source.lower()
    assert "update_user_credits" not in source
    assert "credits" not in service.lower()


def test_access_guard_allows_seedance_admin_fsm_states():
    source = (ROOT / "bot/main.py").read_text(encoding="utf-8")
    assert '"SeedanceAdminTestStates:prompt"' in source
    assert '"SeedanceAdminTestStates:references"' in source
    assert '"SeedanceAdminTestStates:frames"' in source


def test_edit_mode_allows_supporting_media_after_source_video():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    assert "has_edit_source" in source
    assert 'kind != "video"' in source
    assert 'reference_images=images if mode in {"reference", "edit"} else None' in source
    assert 'reference_audios=audios if mode in {"reference", "edit"} else None' in source
    assert 'edit_only_video=mode == "edit"' not in source


def test_paid_submit_and_result_delivery_are_serialized():
    source = (ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text(encoding="utf-8")
    assert "_SUBMIT_LOCKS" in source
    assert "async with _submit_lock(callback.from_user.id)" in source
    assert "seedance_admin_last_payload_hash" in source
    assert 'F.data == "admin_seedance_new_request"' in source
    assert "_DELIVERY_LOCKS" in source
    assert "async with _delivery_lock(request_id)" in source


@pytest.mark.asyncio
async def test_three_prompt_parts_and_references_reach_seedance_payload(monkeypatch):
    """Telegram-split instructions and their reference bindings stay together."""

    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    data = admin_seedance_test_lab._defaults()
    data.update(
        seedance_admin_model="seedance-2.5",
        seedance_admin_mode="reference",
        seedance_admin_references=[
            {"kind": "image", "url": "https://example.test/identity.png"},
            {"kind": "image", "url": "https://example.test/scene.png"},
        ],
    )

    async def get_data():
        return dict(data)

    async def update_data(**updates):
        data.update(updates)

    state = SimpleNamespace(get_data=get_data, update_data=update_data)
    parts = (
        "Keep the identity from @Image 1.",
        "Use the environment from @Image 2.",
        "Preserve both bindings in the final shot.",
    )
    for part in parts:
        await admin_seedance_test_lab.receive_prompt(
            SimpleNamespace(
                from_user=SimpleNamespace(id=880011),
                text=part,
                caption=None,
                answer=AsyncMock(),
            ),
            state,
        )

    payload = admin_seedance_test_lab._payload_from_state(data)

    assert payload["prompt"] == "\n".join(parts)
    assert payload["reference_images"] == [
        {"url": "https://example.test/identity.png"},
        {"url": "https://example.test/scene.png"},
    ]


@pytest.mark.asyncio
async def test_seedance_polling_recovers_after_transient_provider_502():
    service = NeironychSeedanceAdminService(api_key="test-key")
    service.get_status = AsyncMock(
        side_effect=[
            NeironychAPIError("temporary upstream", status=502),
            {"status": "pending"},
            {"status": "done", "request_id": "req-transient-502"},
        ]
    )

    result = await service.wait_for_result(
        "req-transient-502",
        poll_seconds=0,
        timeout_seconds=1,
    )

    assert result["status"] == "done"
    assert service.get_status.await_count == 3


@pytest.mark.asyncio
async def test_transient_provider_502_still_reaches_telegram_delivery(monkeypatch):
    service = NeironychSeedanceAdminService(api_key="test-key")
    service.poll_interval_seconds = 0
    service.poll_timeout_seconds = 1
    service.get_status = AsyncMock(
        side_effect=[
            NeironychAPIError("temporary upstream", status=502),
            {"status": "done", "request_id": "req-delivery-after-502"},
        ]
    )
    deliver = AsyncMock()
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "neironych_seedance_admin_service",
        service,
    )
    monkeypatch.setattr(admin_seedance_test_lab, "_send_result", deliver)

    await admin_seedance_test_lab._poll_and_deliver(
        SimpleNamespace(send_message=AsyncMock()),
        880011,
        "req-delivery-after-502",
        "seedance-2.5",
    )

    deliver.assert_awaited_once_with(
        ANY,
        880011,
        request_id="req-delivery-after-502",
        model="seedance-2.5",
    )


@pytest.mark.asyncio
async def test_content_download_retries_transient_502_before_telegram_send():
    attempts = 0
    expected = b"synthetic-seedance-video"

    async def content(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.Response(status=502, text="temporary upstream")
        return web.Response(status=200, body=expected, content_type="video/mp4")

    app = web.Application()
    app.router.add_get("/v1/videos/{request_id}/content", content)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    service = NeironychSeedanceAdminService(
        api_key="test-key",
        base_url=f"http://127.0.0.1:{port}",
        timeout_seconds=15,
    )
    path = None
    try:
        path = await service.download_to_temp("req-content-502")
        assert Path(path).read_bytes() == expected
        assert attempts == 2
    finally:
        if path:
            Path(path).unlink(missing_ok=True)
        await runner.cleanup()


@pytest.mark.asyncio
async def test_concurrent_prompt_parts_are_serialized(monkeypatch):
    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    data = admin_seedance_test_lab._defaults()
    reads = 0
    read_barrier = asyncio.Event()

    async def get_data():
        nonlocal reads
        snapshot = dict(data)
        reads += 1
        if reads >= 3:
            read_barrier.set()
        try:
            await asyncio.wait_for(read_barrier.wait(), timeout=0.05)
        except TimeoutError:
            pass
        return snapshot

    async def update_data(**updates):
        data.update(updates)

    state = SimpleNamespace(get_data=get_data, update_data=update_data)
    parts = ("first", "second", "third")
    await asyncio.gather(
        *(
            admin_seedance_test_lab.receive_prompt(
                SimpleNamespace(
                    from_user=SimpleNamespace(id=880012),
                    text=part,
                    caption=None,
                    answer=AsyncMock(),
                ),
                state,
            )
            for part in parts
        )
    )

    assert data["seedance_admin_prompt"] == "\n".join(parts)


@pytest.mark.asyncio
async def test_clear_prompt_waits_for_append_and_remains_last(monkeypatch):
    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    data = admin_seedance_test_lab._defaults()
    append_started = asyncio.Event()
    release_append = asyncio.Event()

    async def get_data():
        append_started.set()
        await release_append.wait()
        return dict(data)

    async def update_data(**updates):
        data.update(updates)

    state = SimpleNamespace(
        get_data=get_data,
        update_data=update_data,
        set_state=AsyncMock(),
    )
    actor = SimpleNamespace(id=880017)
    append = asyncio.create_task(
        admin_seedance_test_lab.receive_prompt(
            SimpleNamespace(
                from_user=actor,
                text="late prompt part",
                caption=None,
                answer=AsyncMock(),
            ),
            state,
        )
    )
    await append_started.wait()
    clear = asyncio.create_task(
        admin_seedance_test_lab.clear_prompt(
            SimpleNamespace(
                from_user=actor,
                answer=AsyncMock(),
                message=SimpleNamespace(edit_text=AsyncMock()),
            ),
            state,
        )
    )
    await asyncio.sleep(0)
    release_append.set()
    await asyncio.gather(append, clear)

    assert data["seedance_admin_prompt"] == ""


@pytest.mark.asyncio
async def test_concurrent_references_are_serialized(monkeypatch):
    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "_extract_media",
        lambda _message: ("image", object(), "image/png", "png"),
    )
    data = admin_seedance_test_lab._defaults()
    data["seedance_admin_mode"] = "reference"
    saves = 0
    save_barrier = asyncio.Event()

    async def save_reference(message, *, model):
        nonlocal saves
        assert model == "seedance-2.5"
        saves += 1
        if saves >= 2:
            save_barrier.set()
        try:
            await asyncio.wait_for(save_barrier.wait(), timeout=0.05)
        except TimeoutError:
            pass
        return {"kind": "image", "url": message.synthetic_url, "duration": 0}, None

    monkeypatch.setattr(
        admin_seedance_test_lab,
        "_save_media_reference",
        save_reference,
    )

    async def get_data():
        return dict(data)

    async def update_data(**updates):
        data.update(updates)

    state = SimpleNamespace(get_data=get_data, update_data=update_data)
    messages = [
        SimpleNamespace(
            from_user=SimpleNamespace(id=880013),
            synthetic_url=f"https://example.test/reference-{index}.png",
            answer=AsyncMock(),
        )
        for index in (1, 2)
    ]

    await asyncio.gather(
        *(admin_seedance_test_lab.receive_reference(message, state) for message in messages)
    )

    assert [item["url"] for item in data["seedance_admin_references"]] == [
        "https://example.test/reference-1.png",
        "https://example.test/reference-2.png",
    ]


@pytest.mark.asyncio
async def test_clear_references_waits_for_upload_and_remains_last(monkeypatch):
    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "_extract_media",
        lambda _message: ("image", object(), "image/png", "png"),
    )
    data = admin_seedance_test_lab._defaults()
    data["seedance_admin_mode"] = "reference"
    upload_started = asyncio.Event()
    release_upload = asyncio.Event()

    async def save_reference(_message, *, model):
        assert model == "seedance-2.5"
        upload_started.set()
        await release_upload.wait()
        return {
            "kind": "image",
            "url": "https://example.test/late-reference.png",
            "duration": 0,
        }, None

    monkeypatch.setattr(
        admin_seedance_test_lab,
        "_save_media_reference",
        save_reference,
    )

    async def get_data():
        return dict(data)

    async def update_data(**updates):
        data.update(updates)

    state = SimpleNamespace(
        get_data=get_data,
        update_data=update_data,
        set_state=AsyncMock(),
    )
    actor = SimpleNamespace(id=880016)
    upload = asyncio.create_task(
        admin_seedance_test_lab.receive_reference(
            SimpleNamespace(from_user=actor, answer=AsyncMock()),
            state,
        )
    )
    await upload_started.wait()
    clear = asyncio.create_task(
        admin_seedance_test_lab.clear_refs(
            SimpleNamespace(
                from_user=actor,
                answer=AsyncMock(),
                message=SimpleNamespace(edit_text=AsyncMock()),
            ),
            state,
        )
    )
    await asyncio.sleep(0)
    release_upload.set()
    await asyncio.gather(upload, clear)

    assert data["seedance_admin_references"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delivery_error",
    [
        NeironychAPIError("content retries exhausted", status=502),
        RuntimeError("telegram video and document sends failed"),
    ],
    ids=("content-download", "telegram-send"),
)
async def test_done_result_delivery_failure_keeps_same_request_for_retry(
    monkeypatch,
    delivery_error,
):
    service = SimpleNamespace(
        wait_for_result=AsyncMock(return_value={"status": "done"})
    )
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "neironych_seedance_admin_service",
        service,
    )
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "_send_result",
        AsyncMock(side_effect=delivery_error),
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    await admin_seedance_test_lab._poll_and_deliver(
        bot,
        880014,
        "req-existing-result",
        "seedance-2.5",
    )

    notice = bot.send_message.await_args.args[1]
    assert "req-existing-result" in notice
    assert "Проверить" in notice


@pytest.mark.asyncio
async def test_manual_check_reports_delivery_failure_without_new_submit(monkeypatch):
    monkeypatch.setattr(admin_seedance_test_lab, "_is_admin", lambda _user_id: True)
    service = SimpleNamespace(get_status=AsyncMock(return_value={"status": "done"}))
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "neironych_seedance_admin_service",
        service,
    )
    send_result = AsyncMock(side_effect=RuntimeError("telegram send failed"))
    monkeypatch.setattr(admin_seedance_test_lab, "_send_result", send_result)
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=880015),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
        bot=bot,
    )
    state = SimpleNamespace(
        get_data=AsyncMock(
            return_value={
                "seedance_admin_last_request_id": "req-manual-delivery",
                "seedance_admin_last_model": "seedance-2.5",
                "seedance_admin_model": "seedance-2.5",
            }
        ),
        update_data=AsyncMock(),
    )

    await admin_seedance_test_lab.check_seedance(callback, state)

    send_result.assert_awaited_once()
    assert "req-manual-delivery" in bot.send_message.await_args.args[1]

@pytest.mark.asyncio
async def test_seedance_admin_video_preview_uses_source_portrait_dimensions(
    monkeypatch, tmp_path
):
    """Telegram must show the original 9:16 result, not a square preview."""
    import subprocess

    request_id = "req-portrait-video-preview"
    video = tmp_path / "original.mp4"
    video.write_bytes(b"synthetic-video")
    service = SimpleNamespace(download_to_temp=AsyncMock(return_value=str(video)))
    monkeypatch.setattr(
        admin_seedance_test_lab, "neironych_seedance_admin_service", service
    )

    def probe(command, **_kwargs):
        assert command[0] == "ffprobe"
        return SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"width":720,"height":1280,'
            '"sample_aspect_ratio":"1:1"}]}',
        )

    monkeypatch.setattr(subprocess, "run", probe)
    bot = SimpleNamespace(send_video=AsyncMock(), send_document=AsyncMock())
    admin_seedance_test_lab._DELIVERED_REQUEST_IDS.discard(request_id)
    try:
        await admin_seedance_test_lab._send_result(
            bot, 880017, request_id=request_id, model="seedance-2.5"
        )
        assert bot.send_video.await_count == 1
        send_kwargs = bot.send_video.await_args.kwargs
        assert (send_kwargs.get("width"), send_kwargs.get("height")) == (720, 1280)
        bot.send_document.assert_not_awaited()
        assert not video.exists()
    finally:
        admin_seedance_test_lab._DELIVERED_REQUEST_IDS.discard(request_id)

@pytest.mark.parametrize(
    ("stream", "dimensions"),
    [
        ({"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}, (1080, 1920)),
        ({"width": 720, "height": 576, "sample_aspect_ratio": "16:11"}, (1047, 576)),
        ({"width": 0, "height": 1080}, None),
        ({"width": 720, "height": 1280, "sample_aspect_ratio": "1:1"}, (720, 1280)),
    ],
)
def test_seedance_admin_video_preview_uses_display_geometry(monkeypatch, stream, dimensions):
    import json
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps({"streams": [stream]})
        ),
    )
    assert admin_seedance_test_lab._video_preview_dimensions("source.mp4") == dimensions


@pytest.mark.asyncio
async def test_seedance_admin_video_still_delivers_without_ffprobe(monkeypatch, tmp_path):
    import subprocess

    request_id = "req-preview-probe-unavailable"
    video = tmp_path / "original.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        admin_seedance_test_lab,
        "neironych_seedance_admin_service",
        SimpleNamespace(download_to_temp=AsyncMock(return_value=str(video))),
    )

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("ffprobe unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    bot = SimpleNamespace(send_video=AsyncMock(), send_document=AsyncMock())
    admin_seedance_test_lab._DELIVERED_REQUEST_IDS.discard(request_id)
    try:
        await admin_seedance_test_lab._send_result(
            bot, 880017, request_id=request_id, model="seedance-2.5"
        )
        assert bot.send_video.await_count == 1
        assert "width" not in bot.send_video.await_args.kwargs
        assert "height" not in bot.send_video.await_args.kwargs
        bot.send_document.assert_not_awaited()
        assert not video.exists()
    finally:
        admin_seedance_test_lab._DELIVERED_REQUEST_IDS.discard(request_id)
