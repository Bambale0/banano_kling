# ruff: noqa: I001
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot.handlers.seedance_25_public_release as public_release
import bot.miniapp as miniapp_module
from bot.handlers import seedance_25_fullstack as fullstack_module

from bot.handlers.seedance_25_fullstack import (
    MAX_VIDEO_PIXELS,
    MIN_VIDEO_PIXELS,
    _classify_results,
    _float_fraction,
    _seedance25_model_meta,
    _validate_dimensions,
)
from bot.handlers.seedance_25_public_release import _clean_other_new_markers
from bot.services.seedance_25_service import Seedance25Service, get_seedance25_callback_url
from bot.video_reference_policy import apply_video_reference_cost


def test_seedance25_model_meta_exposes_public_new_contract():
    meta = _seedance25_model_meta()

    assert meta["id"] == "seedance_2_5"
    assert meta["admin_only"] is False
    assert meta["is_new"] is True
    assert "NEW" in meta["label"]
    assert meta["seedance25_resolutions"] == ["480p", "720p"]
    assert meta["seedance25_output_formats"] == ["mp4", "mov"]
    assert meta["seedance25_scenarios"] == [
        "text",
        "first_frame",
        "first_last",
        "multimodal",
    ]
    assert meta["durations"][0] == -1
    assert meta["durations"][1:] == list(range(4, 31))
    assert meta["max_image_references"] == 30
    assert meta["max_video_references"] == 10
    assert meta["max_audio_references"] == 10
    assert meta["supports_generate_audio"] is True
    assert meta["supports_return_last_frame"] is True
    assert meta["supports_web_search"] is True
    assert meta["supports_nsfw_checker"] is True
    assert meta["camera_control_via_prompt"] is True


def test_seedance25_release_removes_new_markers_from_other_models():
    assert _clean_other_new_markers("Grok Imagine 1.5 NEW🔥🔥🔥") == "Grok Imagine 1.5"
    assert _clean_other_new_markers("Seedream 5 Pro 🔥 НОВИНКА") == "Seedream 5 Pro"
    assert _clean_other_new_markers("Nano Banana 2 Lite НОВИНКА") == "Nano Banana 2 Lite"


def test_seedance25_video_reference_doubles_price_once():
    assert apply_video_reference_cost("seedance_2_5", 20, []) == 20
    assert apply_video_reference_cost("seedance_2_5", 20, ["https://example.com/ref.mp4"]) == 40
    assert apply_video_reference_cost(
        "seedance_2_5",
        20,
        ["https://example.com/a.mp4", "https://example.com/b.mp4"],
    ) == 40


def test_seedance25_classifies_video_and_returned_last_frame():
    request_data = {"return_last_frame": True, "output_format": "mov"}
    video, frame = _classify_results(
        [
            "https://cdn.example/result.mov",
            "https://cdn.example/last-frame.png",
        ],
        request_data,
    )
    assert video == "https://cdn.example/result.mov"
    assert frame == "https://cdn.example/last-frame.png"


def test_seedance25_fraction_parser_handles_ffprobe_rates():
    assert _float_fraction("30/1") == 30.0
    assert _float_fraction("60000/1001") == pytest.approx(59.94005994)
    assert _float_fraction("0/0") == 0.0


def test_seedance25_video_geometry_enforces_spec_pixel_range():
    _validate_dimensions(640, 640, video=True)

    with pytest.raises(ValueError):
        _validate_dimensions(639, 640, video=True)

    # Still inside side/ratio limits but over the Kie per-frame pixel ceiling.
    assert 1000 * 1000 > MAX_VIDEO_PIXELS
    with pytest.raises(ValueError):
        _validate_dimensions(1000, 1000, video=True)

    assert 640 * 640 == MIN_VIDEO_PIXELS


@pytest.mark.asyncio
async def test_seedance25_rejects_reference_overflow_instead_of_truncating(monkeypatch):
    service = Seedance25Service(kie_key="test-key")

    async def unexpected_post(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("provider call must not happen")

    monkeypatch.setattr(service, "_kie_post", unexpected_post)
    result = await service.generate_video(
        prompt="test",
        reference_image_urls=[f"https://example.com/{idx}.png" for idx in range(31)],
    )
    assert result["success"] is False
    assert "at most 30" in result["error"]


def test_seedance25_dedicated_callback_path_when_host_available(monkeypatch):
    # The helper reuses the public Kie callback host and switches only the path.
    import bot.services.seedance_25_service as module

    monkeypatch.setattr(module.config, "WEBHOOK_HOST", "https://example.com")
    monkeypatch.setattr(module.config, "KIE_AI_WEBHOOK_PATH", "/webhook/kie_ai")
    monkeypatch.setattr(module.config, "KIE_AI_WEBHOOK_SECRET", "")
    assert get_seedance25_callback_url() == "https://example.com/webhook/kie_seedance25"


@pytest.mark.asyncio
async def test_seedance25_miniapp_repeat_keeps_source_lineage_and_rewards_author(monkeypatch):
    user = SimpleNamespace(id=501)
    monkeypatch.setattr(
        miniapp_module,
        '_get_user_context',
        AsyncMock(return_value=(700001, {'user': user})),
    )
    monkeypatch.setattr(public_release.config, 'is_admin', lambda _telegram_id: False)
    monkeypatch.setattr(
        miniapp_module,
        '_get_repeat_source_card',
        AsyncMock(return_value={'gen_type': 'video', 'model': 'seedance_2_5', 'source_feed_gen_id': 7}),
    )
    monkeypatch.setattr(miniapp_module, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp_module, 'deduct_credits', AsyncMock(return_value=True))
    monkeypatch.setattr(
        miniapp_module,
        'get_or_create_user',
        AsyncMock(return_value=SimpleNamespace(credits=88)),
    )
    repeat_credit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp_module, 'credit_feed_prompt_repeat', repeat_credit)
    add_task = AsyncMock(return_value=True)
    monkeypatch.setattr(public_release.generation_module, 'add_generation_task', add_task)
    monkeypatch.setattr(public_release, '_validate_public_payload', AsyncMock(return_value=None))
    monkeypatch.setattr(public_release.preview_module, '_price_quote', lambda _data: 12.0)
    monkeypatch.setattr(
        public_release,
        '_launch_provider',
        AsyncMock(return_value={'task_id': 'seedance-repeat-task'}),
    )

    response = await public_release._public_miniapp_generate(
        SimpleNamespace(app={}),
        {
            'init_data': 'signed',
            'v_model': 'seedance_2_5',
            'source_feed_gen_id': 42,
            'seedance25_scenario': 'text',
            'prompt': 'same prompt',
            'v_duration': 10,
            'v_ratio': '9:16',
            'seedance25_resolution': '720p',
        },
    )

    assert response.status == 200
    payload = json.loads(response.body.decode('utf-8'))
    assert payload['task_type'] == 'video'
    assert payload['model'] == 'seedance_2_5'
    assert payload['aspect_ratio'] == '9:16'
    assert payload['duration'] == 10
    assert payload['scenario'] == 'text'
    assert payload['prompt_hidden'] is True
    assert payload['prompt_actions_allowed'] is False
    assert payload['source_feed_gen_id'] == 7
    kwargs = add_task.await_args.kwargs
    assert kwargs['source_feed_gen_id'] == 7
    assert kwargs['parent_generation_id'] == 42
    assert kwargs['action_type'] == 'repeat'
    assert kwargs['request_data']['source'] == 'miniapp'
    assert kwargs['request_data']['source_feed_gen_id'] == 7
    assert kwargs['request_data']['parent_generation_id'] == 42
    assert kwargs['request_data']['action_type'] == 'repeat'
    repeat_credit.assert_awaited_once_with(
        42,
        501,
        repeat_task_id='seedance-repeat-task',
        credits_spent=12.0,
    )


@pytest.mark.asyncio
async def test_seedance25_admin_repeat_is_free_and_does_not_reward_author(monkeypatch):
    user = SimpleNamespace(id=502)
    monkeypatch.setattr(
        miniapp_module,
        "_get_user_context",
        AsyncMock(return_value=(700002, {"user": user})),
    )
    monkeypatch.setattr(public_release.config, "is_admin", lambda _telegram_id: True)
    monkeypatch.setattr(
        miniapp_module,
        "_get_repeat_source_card",
        AsyncMock(return_value={"gen_type": "video", "model": "seedance_2_5", "source_feed_gen_id": 8}),
    )
    monkeypatch.setattr(
        miniapp_module,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=100)),
    )
    repeat_credit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp_module, "credit_feed_prompt_repeat", repeat_credit)
    add_task = AsyncMock(return_value=True)
    monkeypatch.setattr(public_release.generation_module, "add_generation_task", add_task)
    monkeypatch.setattr(public_release, "_validate_public_payload", AsyncMock(return_value=None))
    monkeypatch.setattr(public_release.preview_module, "_price_quote", lambda _data: 12.0)
    monkeypatch.setattr(
        public_release,
        "_launch_provider",
        AsyncMock(return_value={"task_id": "seedance-admin-repeat"}),
    )

    response = await public_release._public_miniapp_generate(
        SimpleNamespace(app={}),
        {
            "init_data": "signed",
            "source_feed_gen_id": 42,
            "seedance25_scenario": "text",
            "prompt": "same prompt",
            "v_duration": 10,
            "v_ratio": "9:16",
            "seedance25_resolution": "720p",
        },
    )

    assert response.status == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["cost"] == 12.0
    assert payload["admin_free"] is True
    stored = add_task.await_args.kwargs
    assert stored["cost"] == 0
    assert stored["request_data"]["charged"] is False
    assert stored["request_data"]["charged_cost"] == 0
    assert stored["request_data"]["price_quote"] == 12.0
    repeat_credit.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_public_result_message_has_feed_keyboard(monkeypatch):
    class FakeBot:
        def __init__(self):
            self.video_kwargs = None

        async def send_video(self, _telegram_id, **kwargs):
            self.video_kwargs = kwargs

    sentinel_markup = object()
    monkeypatch.setattr(
        public_release.fullstack,
        "_extension_from_url",
        lambda _url: "mp4",
    )

    import bot.keyboards as keyboard_module

    keyboard_call = {}

    def fake_keyboard(video_url, *, task_id, model, is_public_feed):
        keyboard_call.update(
            {
                "video_url": video_url,
                "task_id": task_id,
                "model": model,
                "is_public_feed": is_public_feed,
            }
        )
        return sentinel_markup

    monkeypatch.setattr(keyboard_module, "get_video_result_keyboard", fake_keyboard)
    bot = FakeBot()

    await public_release._public_send_results(
        {"bot": bot},
        612441694,
        "seedance-task-123",
        "https://cdn.example/result.mp4",
        None,
        {"duration": 12, "charged_cost": 72, "seedance25_scenario": "multimodal"},
    )

    assert bot.video_kwargs is not None
    assert bot.video_kwargs["reply_markup"] is sentinel_markup
    assert keyboard_call == {
        "video_url": "https://cdn.example/result.mp4",
        "task_id": "seedance-task-123",
        "model": "seedance_2_5",
        "is_public_feed": False,
    }


@pytest.mark.asyncio
async def test_seedance25_fullstack_result_message_has_feed_keyboard(monkeypatch):
    class FakeBot:
        def __init__(self):
            self.video_kwargs = None

        async def send_video(self, _telegram_id, **kwargs):
            self.video_kwargs = kwargs

    sentinel_markup = object()
    monkeypatch.setattr(fullstack_module, "_extension_from_url", lambda _url: "mp4")

    import bot.keyboards as keyboard_module

    monkeypatch.setattr(
        keyboard_module,
        "get_video_result_keyboard",
        lambda *_args, **_kwargs: sentinel_markup,
    )
    bot = FakeBot()

    await fullstack_module._send_seedance25_results(
        {"bot": bot},
        612441694,
        "seedance-task-123",
        "https://cdn.example/result.mp4",
        None,
        {"duration": 12, "v_duration": 12, "seedance25_scenario": "multimodal"},
    )

    assert bot.video_kwargs is not None
    assert bot.video_kwargs["reply_markup"] is sentinel_markup


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [5001, 30000, 30001])
async def test_public_payload_prompt_limit_matches_provider(monkeypatch, length):
    validate_sources = AsyncMock()
    monkeypatch.setattr(fullstack_module, "_validate_seedance_sources", validate_sources)
    payload = public_release._scenario_payload({}, "я" * (length - 1) + "🎬")
    if length > 30000:
        with pytest.raises(ValueError, match="30000"):
            await public_release._validate_public_payload(payload, is_admin=False)
        validate_sources.assert_not_awaited()
    else:
        await public_release._validate_public_payload(payload, is_admin=False)
        validate_sources.assert_awaited_once()


@pytest.mark.asyncio
async def test_seedance25_result_download_retries_after_timeout(monkeypatch):
    calls = {"count": 0}

    class FakeContent:
        async def iter_chunked(self, _size):
            yield b"video"

    class FakeResponse:
        status = 200
        content_length = 5
        content = FakeContent()

    class FakeRequestContext:
        async def __aenter__(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("slow CDN")
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, *_args, **_kwargs):
            return FakeRequestContext()

    monkeypatch.setattr(
        fullstack_module.aiohttp,
        "ClientSession",
        lambda *args, **kwargs: FakeSession(),
    )
    monkeypatch.setattr(
        fullstack_module,
        "SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS",
        0,
    )

    path = await fullstack_module._download_to_temp(
        "https://cdn.example/result.mp4",
        ".mp4",
    )

    try:
        assert path is not None
        assert calls["count"] == 2
        assert Path(path).read_bytes() == b"video"
    finally:
        if path:
            Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_seedance25_public_delivery_returns_false_when_all_channels_fail(monkeypatch):
    class FakeBot:
        async def send_video(self, *_args, **_kwargs):
            raise RuntimeError("telegram url send failed")

        async def send_message(self, *_args, **_kwargs):
            raise RuntimeError("telegram text send failed")

    monkeypatch.setattr(fullstack_module, "_download_to_temp", AsyncMock(return_value=None))

    delivered = await public_release._public_send_results(
        {"bot": FakeBot()},
        612441694,
        "seedance-task-undelivered",
        "https://cdn.example/result.mp4",
        None,
        {
            "duration": 12,
            "charged_cost": 72,
            "seedance25_scenario": "multimodal",
        },
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_seedance25_completed_undelivered_result_is_retried(monkeypatch):
    row = {
        "task_id": "seedance-retry-1",
        "model": "seedance_2_5",
        "status": "completed",
        "telegram_id": 612441694,
        "result_url": "https://cdn.example/result.mp4",
        "result_urls": json.dumps(["https://cdn.example/result.mp4"]),
        "duration": 12,
        "request_data": json.dumps(
            {
                "duration": 12,
                "seedance25_scenario": "multimodal",
                "delivery_status": "pending",
            }
        ),
    }
    send_result = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module, "_load_task_row", AsyncMock(return_value=row))
    monkeypatch.setattr(fullstack_module, "_claim_seedance25_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(fullstack_module, "_send_seedance25_results", send_result)

    handled = await fullstack_module._process_seedance25_payload(
        {"bot": object()},
        {"code": 200, "data": {"taskId": "seedance-retry-1"}},
    )

    assert handled is True
    send_result.assert_awaited_once()


def test_seedance25_copyright_failure_is_classified():
    assert fullstack_module._is_seedance25_copyright_failure(
        400,
        "input image may be related to copyright restrictions",
    )
    assert not fullstack_module._is_seedance25_copyright_failure(
        500,
        "upstream timeout",
    )


@pytest.mark.asyncio
async def test_seedance25_failcode_400_triggers_public_refund(monkeypatch):
    refund = AsyncMock(return_value=(612441694, 72.0))
    original = AsyncMock(return_value=True)
    monkeypatch.setattr(public_release, "_claim_async_refund", refund)
    monkeypatch.setattr(
        fullstack_module,
        "_process_seedance25_payload_original",
        original,
        raising=False,
    )

    handled = await public_release._public_process_payload(
        {"bot": object()},
        {
            "code": 200,
            "data": {
                "taskId": "seedance-copyright-400",
                "failCode": 400,
                "failMsg": "input image may be related to copyright restrictions",
            },
        },
    )

    assert handled is True
    refund.assert_awaited_once_with("seedance-copyright-400")
    original.assert_awaited_once()

@pytest.mark.asyncio
async def test_refund_database_error_keeps_failure_retryable(monkeypatch):
    original = AsyncMock()
    monkeypatch.setattr(public_release, '_claim_async_refund', AsyncMock(side_effect=RuntimeError('db unavailable')))
    monkeypatch.setattr(fullstack_module, '_process_seedance25_payload_original', original)
    handled = await public_release._public_process_payload({}, {'data': {'taskId': 'retry-refund', 'state': 'fail'}})
    assert handled is False
    original.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_only_delivery_remains_retryable_without_repeated_notifications(monkeypatch):
    bot = SimpleNamespace(send_video=AsyncMock(side_effect=RuntimeError('CDN unavailable')), send_message=AsyncMock())
    monkeypatch.setattr(fullstack_module, '_download_to_temp', AsyncMock(return_value=None))
    mark = AsyncMock()
    monkeypatch.setattr(fullstack_module, '_mark_seedance25_delivery', mark)
    args = ({'bot': bot}, 123, 'link-only', 'https://example.com/video.mp4', None)
    assert await public_release._public_send_results(*args, {}) is False
    bot.send_message.assert_awaited_once()
    mark.assert_awaited_once_with('link-only', 'link_sent')
    assert await public_release._public_send_results(*args, {'delivery_link_sent': True}) is False
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_replay_cannot_reset_delivery_lease():
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'success-race', 'video', 'no_preset_video', model='seedance_2_5', request_data='{}')
    await fullstack_module._store_task_result('success-race', 'https://example.com/video.mp4', [], success=True)
    assert await database.claim_task_delivery('success-race')
    await fullstack_module._store_task_result('success-race', 'https://example.com/video.mp4', [], success=True)
    assert not await database.claim_task_delivery('success-race')
    task = await database.get_task_by_id('success-race')
    assert json.loads(task.request_data)['delivery_status'] == 'delivering'


@pytest.mark.asyncio
async def test_completion_atomically_persists_recovery_marker(monkeypatch):
    import asyncio
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'crash-after-store', 'video', 'no_preset_video', model='seedance_2_5', request_data='{}')
    await fullstack_module._store_task_result('crash-after-store', 'https://example.com/video.mp4', [], success=True)
    task = await database.get_task_by_id('crash-after-store')
    assert json.loads(task.request_data)['delivery_status'] == 'result_ready'
    process = AsyncMock()
    monkeypatch.setattr(fullstack_module, '_process_seedance25_payload', process)
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(fullstack_module.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await fullstack_module._seedance25_reconcile_loop({})
    process.assert_awaited_once_with({}, {'code': 200, 'data': {'taskId': 'crash-after-store'}})

@pytest.mark.asyncio
async def test_refund_and_watchdog_credit_only_once(monkeypatch):
    from bot import database
    from bot.services import task_watchdog
    from bot.services.task_watchdog import force_fail_task
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    user = await database.get_or_create_user(123456)
    before = user.credits
    await database.add_generation_task(user.id, 123456, 'refund-once', 'video', 'no_preset_video', model='seedance_2_5', cost=10, request_data={'refund_on_failure': True, 'charged_cost': 10})
    assert await public_release._claim_async_refund('refund-once') == (123456, 10)
    task = await database.get_task_by_id('refund-once')
    assert await force_fail_task(task.id, user.id, 10)
    assert await public_release._claim_async_refund('refund-once') is None
    assert not await force_fail_task(task.id, user.id, 10)
    assert (await database.get_or_create_user(123456)).credits == before + 10


@pytest.mark.asyncio
async def test_success_callbacks_share_one_delivery_claim(monkeypatch):
    import asyncio
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'concurrent-success', 'video', 'no_preset_video', model='seedance_2_5', request_data='{}')
    original_load = fullstack_module._load_task_row
    pending_reads = 0
    barrier = asyncio.Event()

    async def load(task_id):
        nonlocal pending_reads
        row = await original_load(task_id)
        if row['status'] == 'pending':
            pending_reads += 1
            if pending_reads == 2:
                barrier.set()
            await barrier.wait()
        return row

    send = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module, '_load_task_row', load)
    monkeypatch.setattr(fullstack_module, '_send_seedance25_results', send)
    payload = {'data': {'taskId': 'concurrent-success', 'state': 'success', 'resultJson': json.dumps({'resultUrls': ['https://example.com/video.mp4']})}}
    await asyncio.wait_for(asyncio.gather(*(fullstack_module._process_seedance25_payload({}, payload) for _ in range(2))), 5)
    send.assert_awaited_once()
    task = await database.get_task_by_id('concurrent-success')
    assert json.loads(task.request_data)['delivery_status'] == 'delivered'


@pytest.mark.asyncio
async def test_legacy_completed_task_is_not_automatically_redelivered(monkeypatch):
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'legacy-complete', 'video', 'no_preset_video', model='seedance_2_5', request_data='{}')
    async with fullstack_module.db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET status='completed',result_url='https://example.com/video.mp4' WHERE task_id='legacy-complete'")
        await db.commit()
    send = AsyncMock()
    monkeypatch.setattr(fullstack_module, '_send_seedance25_results', send)
    await fullstack_module._process_seedance25_payload({}, {'data': {'taskId': 'legacy-complete', 'state': 'success'}})
    send.assert_not_awaited()

@pytest.mark.asyncio
async def test_completion_marker_failure_rolls_back_result():
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'atomic-result', 'video', 'no_preset_video', model='seedance_2_5', request_data='{}')
    async with fullstack_module.db_backend.connect() as db:
        await db.execute("CREATE TRIGGER reject_marker BEFORE UPDATE OF request_data ON generation_tasks BEGIN SELECT RAISE(ABORT, 'marker unavailable'); END")
        await db.commit()
    with pytest.raises(fullstack_module.db_backend.IntegrityError, match='marker unavailable'):
        await fullstack_module._store_task_result('atomic-result', 'https://example.com/video.mp4', [], success=True)
    task = await database.get_task_by_id('atomic-result')
    assert task.status == 'pending'
    assert task.result_url is None


@pytest.mark.asyncio
async def test_refund_credit_failure_rolls_back_marker():
    from bot import database
    user = await database.get_or_create_user(123456)
    await database.add_generation_task(user.id, 123456, 'atomic-refund', 'video', 'no_preset_video', model='seedance_2_5', cost=10, request_data={'refund_on_failure': True, 'charged_cost': 10})
    async with fullstack_module.db_backend.connect() as db:
        await db.execute("CREATE TRIGGER reject_credit BEFORE UPDATE OF credits ON users BEGIN SELECT RAISE(ABORT, 'credit unavailable'); END")
        await db.commit()
    with pytest.raises(fullstack_module.db_backend.IntegrityError, match='credit unavailable'):
        await public_release._claim_async_refund('atomic-refund')
    task = await database.get_task_by_id('atomic-refund')
    assert task.status == 'pending'
    assert not json.loads(task.request_data).get('refund_claimed')
    assert (await database.get_or_create_user(123456)).credits == user.credits


_EDIT_PARAMETER_FAILURE = (
    "The parameters `ratio` and `duration` specified in the request are not valid. "
    "Seedance identified your task as video editing based on your prompt. "
    "Issues: [0] `ratio` must be `adaptive`. [1] `duration` must be -1."
)


def _edit_failure_payload(task_id: str, message: str = _EDIT_PARAMETER_FAILURE) -> dict:
    return {
        "code": 200,
        "data": {
            "taskId": task_id,
            "state": "fail",
            "failCode": "400",
            "failMsg": message,
        },
    }


def _edit_request_data(*, admin_free: object = True, **overrides) -> dict:
    paid = admin_free is False
    data = {
        "source": "miniapp",
        "release": "seedance_2_5_public",
        "v_model": "seedance_2_5",
        "v_type": "video",
        "seedance25_scenario": "multimodal",
        "seedance25_video_editing": False,
        "duration": 12,
        "aspect_ratio": "9:16",
        "reference_images": ["https://example.test/person.png"],
        "v_reference_videos": ["https://example.test/source.mp4"],
        "reference_audios": [],
        "resolution": "480p",
        "generate_audio": True,
        "return_last_frame": False,
        "output_format": "mp4",
        "web_search": False,
        "nsfw_checker": False,
        "charged": paid,
        "charged_cost": 72.0 if paid else 0.0,
        "admin_free": admin_free,
        "refund_on_failure": paid,
        "refund_claimed": False,
    }
    data.update(overrides)
    return data


async def _add_edit_task(
    task_id: str,
    telegram_id: int,
    *,
    request_data: dict | None = None,
    duration: int = 12,
    aspect_ratio: str = "9:16",
    prompt: str = "Replace the person in @Video1 with @Image1",
    cost: float = 0.0,
    model: str = "seedance_2_5",
    task_type: str = "video",
):
    from bot import database

    user = await database.get_or_create_user(telegram_id)
    await database.add_generation_task(
        user.id,
        telegram_id,
        task_id,
        task_type,
        "no_preset_video",
        model=model,
        duration=duration,
        aspect_ratio=aspect_ratio,
        prompt=prompt,
        cost=cost,
        request_data=request_data or _edit_request_data(),
    )
    return user


@pytest.mark.asyncio
async def test_provider_classified_video_editing_retries_before_refund(monkeypatch):
    """A legacy admin task is atomically requeued with the provider-required settings."""
    from bot import database
    from bot.services.kie_webhook_verification import canonical_kie_callback

    telegram_id = 612441694
    old_task_id = "seedance-edit-fallback-old"
    new_task_id = "seedance-edit-fallback-new"
    request_data = _edit_request_data()
    request_data.pop("seedance25_video_editing")  # Legacy task 703fa... shape.
    await _add_edit_task(old_task_id, telegram_id, request_data=request_data)

    relaunch = AsyncMock(return_value={"task_id": new_task_id})
    source_probe = AsyncMock(return_value=13.087)
    refund = AsyncMock(return_value=None)
    original_failure = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module, "_validate_local_source", source_probe)
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", relaunch)
    monkeypatch.setattr(public_release, "_claim_async_refund", refund)
    monkeypatch.setattr(
        fullstack_module,
        "_process_seedance25_payload_original",
        original_failure,
    )

    handled = await public_release._public_process_payload(
        {"bot": SimpleNamespace(send_message=AsyncMock())},
        _edit_failure_payload(old_task_id),
    )

    assert handled is True
    refund.assert_not_awaited()
    original_failure.assert_not_awaited()
    source_probe.assert_awaited_once_with("https://example.test/source.mp4", "video")
    relaunch.assert_awaited_once()
    kwargs = relaunch.await_args.kwargs
    assert kwargs["video_editing"] is True
    assert kwargs["duration"] == -1
    assert kwargs["aspect_ratio"] == "adaptive"
    assert kwargs["reference_image_urls"] == ["https://example.test/person.png"]
    assert kwargs["reference_video_urls"] == ["https://example.test/source.mp4"]

    task = await database.get_task_by_id(old_task_id)
    assert task is not None
    assert task.task_id == new_task_id
    assert task.status == "pending"
    assert task.duration == -1
    assert task.aspect_ratio == "adaptive"
    stored = json.loads(task.request_data)
    assert stored["seedance25_video_editing"] is True
    assert stored["seedance25_edit_source_duration"] == 13.087
    assert stored["seedance25_edit_auto_retry_attempt"] == 1
    assert stored["seedance25_edit_auto_retry_from_task_id"] == old_task_id
    assert stored["provider_task_id"] == new_task_id
    assert stored["task_id_aliases"] == [old_task_id, new_task_id]

    # A delayed callback for the replaced provider task must not fail the retry.
    canonical, status = await canonical_kie_callback(_edit_failure_payload(old_task_id))
    assert canonical is None
    assert status == 200


@pytest.mark.asyncio
async def test_paid_provider_classified_edit_refunds_without_unpriced_retry(monkeypatch):
    """Public users keep the quoted-duration contract; auto edit is admin-free only."""
    telegram_id = 612441695
    task_id = "seedance-paid-edit-classification"
    await _add_edit_task(
        task_id,
        telegram_id,
        request_data=_edit_request_data(admin_free=False),
        cost=72.0,
    )

    relaunch = AsyncMock(return_value={"task_id": "must-not-launch"})
    refund = AsyncMock(return_value=(telegram_id, 72.0))
    original_failure = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", relaunch)
    monkeypatch.setattr(public_release, "_claim_async_refund", refund)
    monkeypatch.setattr(
        fullstack_module,
        "_process_seedance25_payload_original",
        original_failure,
    )

    assert await public_release._public_process_payload(
        {"bot": object()}, _edit_failure_payload(task_id)
    )

    relaunch.assert_not_awaited()
    refund.assert_awaited_once_with(task_id)
    original_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_auto_retry_requires_strict_admin_free_marker(monkeypatch):
    provider = AsyncMock()
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", provider)

    for index, marker in enumerate((False, "false", 1, None), start=1):
        task_id = f"seedance-edit-admin-marker-{index}"
        await _add_edit_task(
            task_id,
            612441700 + index,
            request_data=_edit_request_data(admin_free=marker),
        )
        assert not await fullstack_module._auto_retry_seedance25_video_editing(
            task_id, _EDIT_PARAMETER_FAILURE
        )

    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "task_type"),
    [("seedance_2", "video"), ("seedance_2_5", "image")],
)
async def test_edit_auto_retry_only_handles_seedance25_video_tasks(
    monkeypatch, model, task_type
):
    provider = AsyncMock()
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", provider)
    task_id = f"seedance-edit-wrong-{model}-{task_type}"
    await _add_edit_task(
        task_id,
        612441720,
        model=model,
        task_type=task_type,
    )

    assert not await fullstack_module._auto_retry_seedance25_video_editing(
        task_id, _EDIT_PARAMETER_FAILURE
    )
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance_edit_auto_retry_is_claimed_once_under_concurrency(monkeypatch):
    from bot import database

    old_task_id = "seedance-edit-concurrent-old"
    new_task_id = "seedance-edit-concurrent-new"
    await _add_edit_task(old_task_id, 612441696)
    started = asyncio.Event()
    release = asyncio.Event()

    async def provider_launch(**_kwargs):
        started.set()
        await release.wait()
        return {"task_id": new_task_id}

    relaunch = AsyncMock(side_effect=provider_launch)
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", relaunch)

    first = asyncio.create_task(
        fullstack_module._auto_retry_seedance25_video_editing(
            old_task_id, _EDIT_PARAMETER_FAILURE
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    second = await fullstack_module._auto_retry_seedance25_video_editing(
        old_task_id, _EDIT_PARAMETER_FAILURE
    )
    release.set()

    assert second is True
    assert await asyncio.wait_for(first, timeout=5) is True
    relaunch.assert_awaited_once()
    task = await database.get_task_by_id(old_task_id)
    assert task is not None
    assert task.task_id == new_task_id
    assert task.status == "pending"


@pytest.mark.asyncio
async def test_seedance_edit_auto_retry_rejects_source_shorter_than_four_seconds(
    monkeypatch,
):
    task_id = "seedance-edit-source-too-short"
    await _add_edit_task(task_id, 612441697)
    provider = AsyncMock()
    monkeypatch.setattr(
        fullstack_module,
        "_validate_local_source",
        AsyncMock(return_value=3.999),
    )
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", provider)

    assert not await fullstack_module._auto_retry_seedance25_video_editing(
        task_id, _EDIT_PARAMETER_FAILURE
    )
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance_edit_auto_retry_launch_failure_falls_through_once(monkeypatch):
    task_id = "seedance-edit-retry-launch-failed"
    await _add_edit_task(task_id, 612441698)
    relaunch = AsyncMock(return_value={"success": False, "error": "provider unavailable"})
    original_failure = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", relaunch)
    monkeypatch.setattr(public_release, "_claim_async_refund", AsyncMock(return_value=None))
    monkeypatch.setattr(
        fullstack_module,
        "_process_seedance25_payload_original",
        original_failure,
    )

    assert await public_release._public_process_payload(
        {"bot": object()}, _edit_failure_payload(task_id)
    )

    relaunch.assert_awaited_once()
    original_failure.assert_awaited_once()
    row = await fullstack_module._load_task_row(task_id)
    stored = json.loads(row["request_data"])
    assert stored["seedance25_edit_auto_retry_attempt"] == 1
    assert stored["seedance25_edit_auto_retry_state"] == "create_failed"


@pytest.mark.asyncio
async def test_seedance_edit_auto_retry_does_not_loop_after_provider_retry(monkeypatch):
    task_id = "seedance-edit-retry-terminal"
    request_data = _edit_request_data(
        seedance25_video_editing=True,
        seedance25_edit_auto_retry_attempt=1,
        duration=-1,
        aspect_ratio="adaptive",
    )
    await _add_edit_task(
        task_id,
        612441699,
        request_data=request_data,
        duration=-1,
        aspect_ratio="adaptive",
    )

    relaunch = AsyncMock()
    original_failure = AsyncMock(return_value=True)
    monkeypatch.setattr(fullstack_module.seedance_25_service, "generate_video", relaunch)
    monkeypatch.setattr(public_release, "_claim_async_refund", AsyncMock(return_value=None))
    monkeypatch.setattr(
        fullstack_module,
        "_process_seedance25_payload_original",
        original_failure,
    )

    assert await public_release._public_process_payload(
        {"bot": object()}, _edit_failure_payload(task_id)
    )

    relaunch.assert_not_awaited()
    original_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_seedance25_terminal_chat_error_marks_delivery_unavailable(monkeypatch):
    row = {
        "task_id": "seedance-chat-unavailable",
        "telegram_id": 612441694,
        "result_url": "https://cdn.example/result.mp4",
        "result_urls": json.dumps(["https://cdn.example/result.mp4"]),
    }
    monkeypatch.setattr(
        fullstack_module,
        "_claim_seedance25_delivery",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        fullstack_module,
        "_send_seedance25_results",
        AsyncMock(side_effect=RuntimeError("Bad Request: chat not found")),
    )
    mark = AsyncMock()
    monkeypatch.setattr(fullstack_module, "_mark_seedance25_delivery", mark)

    handled = await fullstack_module._retry_seedance25_delivery(
        {"bot": object()},
        row,
        {"duration": 12, "seedance25_scenario": "multimodal"},
    )

    assert handled is True
    mark.assert_awaited_once_with(
        "seedance-chat-unavailable",
        "unavailable",
        error="chat_not_found",
    )


@pytest.mark.asyncio
async def test_seedance25_recovery_skips_known_chatless_user(monkeypatch):
    from bot import database

    monkeypatch.setattr(
        database,
        "can_attempt_telegram_delivery",
        AsyncMock(return_value=False),
    )
    claim = AsyncMock()
    mark = AsyncMock()
    monkeypatch.setattr(fullstack_module, "_claim_seedance25_delivery", claim)
    monkeypatch.setattr(fullstack_module, "_mark_seedance25_delivery", mark)

    handled = await fullstack_module._retry_seedance25_delivery(
        {"bot": SimpleNamespace(send_video=AsyncMock())},
        {
            "task_id": "seedance-chatless-recovery",
            "telegram_id": 612441697,
            "result_url": "https://cdn.example/result.mp4",
            "result_urls": json.dumps(["https://cdn.example/result.mp4"]),
        },
        {"duration": 12},
    )

    assert handled is True
    claim.assert_not_awaited()
    mark.assert_awaited_once_with(
        "seedance-chatless-recovery",
        "unavailable",
        error="chat_not_started",
    )


@pytest.mark.asyncio
async def test_seedance25_chatless_success_retains_result_without_telegram():
    from bot import database

    user = await database.get_or_create_user(
        612441695,
        initial_telegram_chat_state="unavailable",
    )
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "seedance-chatless-success",
        "video",
        "no_preset_video",
        model="seedance_2_5",
        request_data={"source": "miniapp", "duration": 12},
    )
    bot = SimpleNamespace(send_message=AsyncMock(), send_video=AsyncMock())
    process = fullstack_module._process_seedance25_payload_original

    handled = await process(
        {"bot": bot},
        {
            "code": 200,
            "data": {
                "taskId": "seedance-chatless-success",
                "state": "success",
                "resultJson": json.dumps(
                    {"resultUrls": ["https://cdn.example/result.mp4"]}
                ),
            },
        },
    )

    task = await database.get_task_by_id("seedance-chatless-success")
    metadata = json.loads(task.request_data or "{}")
    assert handled is True
    assert task.status == "completed"
    assert task.result_url == "https://cdn.example/result.mp4"
    assert metadata["delivery_status"] == "unavailable"
    assert metadata["delivery_error"] == "chat_not_started"
    bot.send_message.assert_not_awaited()
    bot.send_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_chatless_failure_does_not_call_telegram(monkeypatch):
    from bot import database

    user = await database.get_or_create_user(
        612441696,
        initial_telegram_chat_state="unavailable",
    )
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "seedance-chatless-failure",
        "video",
        "no_preset_video",
        model="seedance_2_5",
        request_data={"source": "miniapp", "duration": 12},
    )
    monkeypatch.setattr(
        fullstack_module,
        "_auto_retry_seedance25_video_editing",
        AsyncMock(return_value=False),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    process = fullstack_module._process_seedance25_payload_original

    handled = await process(
        {"bot": bot},
        {
            "code": 501,
            "data": {
                "taskId": "seedance-chatless-failure",
                "state": "fail",
                "failCode": 501,
                "failMsg": "provider rejected input",
            },
        },
    )

    task = await database.get_task_by_id("seedance-chatless-failure")
    metadata = json.loads(task.request_data or "{}")
    assert handled is True
    assert task.status == "failed"
    assert metadata["delivery_status"] == "unavailable"
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_completed_unavailable_result_is_not_retried(monkeypatch):
    row = {
        "task_id": "seedance-chat-unavailable",
        "model": "seedance_2_5",
        "status": "completed",
        "telegram_id": 612441694,
        "result_url": "https://cdn.example/result.mp4",
        "result_urls": json.dumps(["https://cdn.example/result.mp4"]),
        "duration": 12,
        "request_data": json.dumps(
            {
                "duration": 12,
                "seedance25_scenario": "multimodal",
                "delivery_status": "unavailable",
            }
        ),
    }
    retry = AsyncMock()
    monkeypatch.setattr(fullstack_module, "_load_task_row", AsyncMock(return_value=row))
    monkeypatch.setattr(fullstack_module, "_retry_seedance25_delivery", retry)

    assert await fullstack_module._process_seedance25_payload(
        {"bot": object()},
        {"code": 200, "data": {"taskId": "seedance-chat-unavailable"}},
    )
    retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_seedance_delivery_stops_after_terminal_chat_error(monkeypatch):
    class UnavailableBot:
        async def send_video(self, *_args, **_kwargs):
            raise RuntimeError("Bad Request: chat not found")

    download = AsyncMock(return_value=None)
    monkeypatch.setattr(fullstack_module, "_download_to_temp", download)

    with pytest.raises(RuntimeError, match="chat not found"):
        await public_release._public_send_results(
            {"bot": UnavailableBot()},
            612441694,
            "seedance-chat-unavailable",
            "https://cdn.example/result.mp4",
            None,
            {
                "duration": 12,
                "charged_cost": 72,
                "seedance25_scenario": "multimodal",
            },
        )

    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_terminal_last_frame_stops_fallback_and_marks_chat(monkeypatch):
    from bot import database

    bot = SimpleNamespace(
        send_video=AsyncMock(return_value=None),
        send_photo=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found")),
        send_message=AsyncMock(),
    )
    mark_chat = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "mark_telegram_chat_unavailable", mark_chat)

    delivered = await public_release._public_send_results(
        {"bot": bot},
        612441698,
        "seedance-terminal-last-frame",
        "https://cdn.example/result.mp4",
        "https://cdn.example/last-frame.png",
        {"duration": 12, "return_last_frame": True},
    )

    assert delivered is True
    mark_chat.assert_awaited_once_with(612441698)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_fullstack_seedance25_terminal_last_frame_marks_chat(monkeypatch):
    from bot import database

    bot = SimpleNamespace(
        send_video=AsyncMock(return_value=None),
        send_photo=AsyncMock(side_effect=RuntimeError("Bad Request: chat not found")),
        send_message=AsyncMock(),
    )
    mark_chat = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "mark_telegram_chat_unavailable", mark_chat)

    delivered = await fullstack_module._send_seedance25_results(
        {"bot": bot},
        612441699,
        "seedance-fullstack-terminal-last-frame",
        "https://cdn.example/result.mp4",
        "https://cdn.example/last-frame.png",
        {"duration": 12, "return_last_frame": True},
    )

    assert delivered is True
    mark_chat.assert_awaited_once_with(612441699)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_transient_delivery_error_remains_pending(monkeypatch):
    row = {
        "task_id": "seedance-transient-delivery",
        "telegram_id": 612441694,
        "result_url": "https://cdn.example/result.mp4",
        "result_urls": json.dumps(["https://cdn.example/result.mp4"]),
    }
    monkeypatch.setattr(
        fullstack_module,
        "_claim_seedance25_delivery",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        fullstack_module,
        "_send_seedance25_results",
        AsyncMock(side_effect=TimeoutError("request timeout")),
    )
    mark = AsyncMock()
    monkeypatch.setattr(fullstack_module, "_mark_seedance25_delivery", mark)

    handled = await fullstack_module._retry_seedance25_delivery(
        {"bot": object()},
        row,
        {"duration": 12, "seedance25_scenario": "multimodal"},
    )

    assert handled is False
    mark.assert_awaited_once_with(
        "seedance-transient-delivery",
        "pending",
        error="request timeout",
    )
