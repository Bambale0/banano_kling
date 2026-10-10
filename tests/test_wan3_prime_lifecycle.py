from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import (
    Wan3PrimeActor,
    Wan3PrimeLifecycle,
    Wan3PrimeLifecycleError,
)
from bot.services.wan3_prime_media import MediaInfo


class Probe:
    def __init__(self, *, url_durations: dict[str, float] | None = None, file_duration: float | None = 6):
        self.url_durations = url_durations or {}
        self.file_duration = file_duration

    async def probe_url(self, url: str, *, kind: str) -> MediaInfo:
        ext = "." + url.rsplit(".", 1)[-1].lower()
        if kind == "video":
            return MediaInfo(kind=kind, url=url, extension=ext, width=1280, height=720, size_bytes=1024, duration_seconds=self.url_durations.get(url, 5))
        if kind == "audio":
            return MediaInfo(kind=kind, url=url, extension=ext, size_bytes=1024, duration_seconds=self.url_durations.get(url, 3))
        return MediaInfo(kind=kind, url=url, extension=ext, width=1024, height=768, size_bytes=1024)

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        return MediaInfo(kind=kind, path=path, extension=".mp4", duration_seconds=self.file_duration)


class Prices:
    def __init__(self, rates=None):
        self.rates = rates if rates is not None else {"720p": 2, "1080p": 3}

    def get_video_quality_costs(self, model: str):
        assert model == "wan_3_prime"
        return dict(self.rates)


class Provider:
    def __init__(self):
        self.creates = 0
        self.create_result = {"success": True, "task_id": "provider_1"}
        self.statuses = {}

    async def create_task(self, recipe, *, callback_url):
        self.creates += 1
        self.callback_url = callback_url
        self.recipe = recipe
        return self.create_result

    async def get_task_status(self, provider_task_id: str):
        return self.statuses.get(provider_task_id)

    async def close(self):
        pass


class Downloader:
    def __init__(self, path):
        self.path = path

    async def download(self, url: str, *, task_id: str) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self.path.write_bytes, b"video")
        return str(self.path)


class MissingDownloader:
    def __init__(self, path):
        self.path = path

    async def download(self, url: str, *, task_id: str) -> str:
        return str(self.path)


async def user_actor(credits: float = 100, telegram_id: int = 111) -> Wan3PrimeActor:
    user = await database.get_or_create_user(telegram_id)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET credits = ? WHERE id = ?", (credits, user.id))
        await db.commit()
    return Wan3PrimeActor(user_id=user.id, telegram_id=telegram_id, is_admin=False)


async def balance(user_id: int) -> float:
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        row = await (await db.execute("SELECT credits FROM users WHERE id = ?", (user_id,))).fetchone()
    return float(row[0])


def body(**overrides):
    base = {"scenario": "text", "prompt": "make a calm video", "duration": 5, "resolution": "720P"}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "result",
    [
        {"error": "network_error", "message": "Provider request failed", "success": False},
        {"error": "invalid_json", "message": "Malformed response", "success": False},
        {"error": "no_task_id", "message": "Task missing", "success": False},
        {"code": 200, "data": {}, "success": False},
    ],
)
def test_unknown_acceptance_is_not_a_confirmed_rejection(result):
    outcome, task_id, _ = Wan3PrimeLifecycle._classify_create_result(None, result)
    assert outcome not in {"accepted", "api_error"}
    assert task_id is None


@pytest.mark.parametrize(
    "result",
    [
        {"error": "api_error", "status_code": 422, "success": False},
        {"code": 402, "msg": "Insufficient supplier credits", "success": False},
    ],
)
def test_documented_rejection_can_be_refunded(result):
    outcome, task_id, _ = Wan3PrimeLifecycle._classify_create_result(None, result)
    assert outcome == "api_error"
    assert task_id is None


def test_provider_acknowledgement_preserves_task_id():
    outcome, task_id, _ = Wan3PrimeLifecycle._classify_create_result(
        None, {"task_id": "synthetic-task", "success": True}
    )
    assert outcome == "accepted"
    assert task_id == "synthetic-task"


@pytest.mark.asyncio
async def test_quote_uses_configured_rate_no_default_and_admin_free():
    actor = await user_actor()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({}), transport=Provider())

    with pytest.raises(Wan3PrimeLifecycleError, match="rate"):
        await lifecycle.quote(actor, body())

    admin = Wan3PrimeActor(user_id=actor.user_id, telegram_id=actor.telegram_id, is_admin=True)
    quote = await lifecycle.quote(admin, body())
    assert quote.reserve_credits == 0
    assert quote.price_configured is False


@pytest.mark.asyncio
async def test_launch_reserves_once_and_duplicate_idempotency_returns_same_task():
    actor = await user_actor(credits=50)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({"720p": 2}), transport=provider)

    quote = await lifecycle.quote(actor, body(duration=5, resolution="720P"))
    first = await lifecycle.launch(actor, body(duration=5, resolution="720P"), quote, "same-key")
    second = await lifecycle.launch(actor, body(duration=5, resolution="720P"), quote, "same-key")

    assert provider.creates == 1
    assert first["task_id"] == second["task_id"]
    assert first["reserve_amount"] == 10
    assert await balance(actor.user_id) == 40


@pytest.mark.asyncio
async def test_same_idempotency_key_with_different_body_conflicts():
    actor = await user_actor(credits=50)
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({"720p": 2}), transport=Provider())
    quote = await lifecycle.quote(actor, body(duration=5))
    await lifecycle.launch(actor, body(duration=5), quote, "same-key")

    with pytest.raises(Wan3PrimeLifecycleError) as exc:
        await lifecycle.launch(actor, body(duration=6), None, "same-key")

    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_provider_timeout_unknown_keeps_reserve_and_does_not_retry_on_duplicate():
    class TimeoutProvider(Provider):
        async def create_task(self, recipe, *, callback_url):
            self.creates += 1
            raise TimeoutError()

    actor = await user_actor(credits=50)
    provider = TimeoutProvider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({"720p": 2}), transport=provider)
    quote = await lifecycle.quote(actor, body(duration=5))

    first = await lifecycle.launch(actor, body(duration=5), quote, "timeout-key")
    second = await lifecycle.launch(actor, body(duration=5), quote, "timeout-key")

    assert first["status"] == "unknown"
    assert second["status"] == "unknown"
    assert provider.creates == 1
    assert await balance(actor.user_id) == 40


@pytest.mark.asyncio
async def test_success_settlement_refunds_auto_reserve_once(tmp_path):
    actor = await user_actor(credits=100)
    provider = Provider()
    output = Path("static/uploads/wan3_prime/results/test-result.mp4")
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=6),
        preset_manager=Prices({"720p": 2}),
        transport=provider,
        downloader=Downloader(output),
    )
    q = await lifecycle.quote(actor, body(duration=-1))
    launched = await lifecycle.launch(actor, body(duration=-1), q, "auto-key")
    provider.statuses["provider_1"] = {
        "taskId": "provider_1",
        "model": "wan/3-0-video-prime",
        "state": "success",
        "response": {"resultUrls": ["https://kie.example.com/out.mp4"]},
    }

    assert q.reserve_credits == 60
    assert await lifecycle.reconcile_once(provider_task_id="provider_1") == 1
    assert await lifecycle.reconcile_once(provider_task_id="provider_1") == 0
    result = await lifecycle.status(actor, launched["task_id"])
    assert result["status"] == "completed"
    assert result["charged_credits"] == 12
    assert result["refunded_credits"] == 48
    assert await balance(actor.user_id) == 88
    output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_terminal_fail_refunds_once():
    actor = await user_actor(credits=40)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({"720p": 2}), transport=provider)
    quote = await lifecycle.quote(actor, body(duration=5))
    launched = await lifecycle.launch(actor, body(duration=5), quote, "fail-key")
    provider.statuses["provider_1"] = {"taskId": "provider_1", "state": "fail", "failCode": "bad", "failMsg": "nope"}

    await lifecycle.reconcile_once(provider_task_id="provider_1")
    await lifecycle.reconcile_once(provider_task_id="provider_1")

    result = await lifecycle.status(actor, launched["task_id"])
    assert result["status"] == "failed"
    assert await balance(actor.user_id) == 40


@pytest.mark.asyncio
async def test_late_opposite_terminal_events_do_not_mutate_money(tmp_path):
    actor = await user_actor(credits=100)
    provider = Provider()
    output = Path("static/uploads/wan3_prime/results/test-order.mp4")
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=5),
        preset_manager=Prices({"720p": 2}),
        transport=provider,
        downloader=Downloader(output),
    )
    q = await lifecycle.quote(actor, body(duration=5))
    launched = await lifecycle.launch(actor, body(duration=5), q, "order-key")
    provider.statuses["provider_1"] = {"taskId": "provider_1", "state": "fail", "failMsg": "nope"}
    await lifecycle.reconcile_once(provider_task_id="provider_1")
    assert await balance(actor.user_id) == 100
    provider.statuses["provider_1"] = {
        "taskId": "provider_1",
        "state": "success",
        "response": {"resultUrls": ["https://kie.example.com/out.mp4"]},
    }
    assert await lifecycle.reconcile_once(provider_task_id="provider_1") == 0
    assert (await lifecycle.status(actor, launched["task_id"]))["status"] == "failed"
    assert await balance(actor.user_id) == 100
    output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_launch_requires_client_quote_hash_and_auto_fraction_reserves_total_30():
    actor = await user_actor(credits=100)
    probe = Probe(url_durations={"https://cdn.example.com/source.mp4": 2.5})
    lifecycle = Wan3PrimeLifecycle(probe=probe, preset_manager=Prices({"720p": 2}), transport=Provider())
    request = body(
        scenario="reference",
        prompt="",
        duration=-1,
        reference_video_urls=["https://cdn.example.com/source.mp4"],
    )
    quote = await lifecycle.quote(actor, request)
    assert quote.billable_seconds_reserved == 30
    assert quote.reserved_output_seconds == 27.5
    with pytest.raises(Wan3PrimeLifecycleError) as exc:
        await lifecycle.launch(actor, request, None, "missing-quote")
    assert exc.value.code == "missing_quote"


@pytest.mark.asyncio
async def test_delivery_unavailable_preserves_result_without_regeneration():
    actor = await user_actor(credits=50)
    provider = Provider()
    output = Path("static/uploads/wan3_prime/results/test-delivery.mp4")
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=5),
        preset_manager=Prices({"720p": 2}),
        transport=provider,
        downloader=Downloader(output),
    )
    q = await lifecycle.quote(actor, body(duration=5))
    launched = await lifecycle.launch(actor, body(duration=5), q, "delivery-key")
    provider.statuses["provider_1"] = {
        "taskId": "provider_1",
        "state": "success",
        "response": {"resultUrls": ["https://kie.example.com/out.mp4"]},
    }
    await lifecycle.reconcile_once(provider_task_id="provider_1")

    class BlockedBot:
        async def send_video(self, *_args, **_kwargs):
            raise RuntimeError("bot was blocked by the user")

        send_message = send_video

    assert await lifecycle.deliver_ready_once(BlockedBot()) == 0
    status = await lifecycle.status(actor, launched["task_id"])
    assert status["delivery_status"] == "unavailable"
    assert status["result_url"]
    assert provider.creates == 1
    output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_callback_spoof_rejected_and_nonce_can_bind_after_accept_crash(monkeypatch):
    monkeypatch.setenv('WAN3_CALLBACK_QUERY_LOGS_REDACTED', '1')
    actor = await user_actor(credits=40)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices({"720p": 2}), transport=provider)
    q = await lifecycle.quote(actor, body(duration=5))
    launched = await lifecycle.launch(actor, body(duration=5), q, "cb-key")

    # Spoofed task id does not match the stored provider id.
    payload = {"data": {"taskId": "evil", "model": "wan/3-0-video-prime"}}
    result, status = await lifecycle.handle_callback(payload, internal_task_id=launched["task_id"], nonce="wrong")
    assert status == 403
    assert result is None

    # Simulate post-accept binding loss: nonce alone is not enough to bind an
    # arbitrary callback task id without canonical lineage proof.
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        row = await (await db.execute("SELECT callback_nonce FROM wan3_prime_intents WHERE internal_task_id = ?", (launched["task_id"],))).fetchone()
        await db.execute("UPDATE wan3_prime_intents SET provider_task_id = NULL WHERE internal_task_id = ?", (launched["task_id"],))
        await db.commit()

    provider.statuses["provider_1"] = {"taskId": "provider_1", "state": "waiting"}
    result, status = await lifecycle.handle_callback(
        {"data": {"taskId": "provider_1", "model": "wan/3-0-video-prime"}},
        internal_task_id=launched["task_id"],
        nonce=row[0],
    )
    assert status == 200
    assert result is None
    assert (await lifecycle.status(actor, launched["task_id"]))["status"] == "unknown"


@pytest.mark.asyncio
async def test_durable_file_missing_cannot_complete_and_startup_marks_stuck_submitting_unknown(tmp_path):
    actor = await user_actor(credits=80)
    provider = Provider()
    missing_path = tmp_path / "missing.mp4"
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=6),
        preset_manager=Prices({"720p": 2}),
        transport=provider,
        downloader=MissingDownloader(missing_path),
    )
    q = await lifecycle.quote(actor, body(duration=5))
    launched = await lifecycle.launch(actor, body(duration=5), q, "missing-key")
    provider.statuses["provider_1"] = {
        "taskId": "provider_1",
        "state": "success",
        "response": {"resultUrls": ["https://kie.example.com/out.mp4"]},
    }

    assert await lifecycle.reconcile_once(provider_task_id="provider_1") == 0
    assert (await lifecycle.status(actor, launched["task_id"]))["status"] == "settlement_pending"
    assert await balance(actor.user_id) == 70  # Reserved, not charged twice or falsely refunded.

    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE wan3_prime_intents SET status = 'submitting', lease_until = '2000-01-01 00:00:00' WHERE internal_task_id = ?",
            (launched["task_id"],),
        )
        await db.commit()
    await lifecycle.startup()
    assert (await lifecycle.status(actor, launched["task_id"]))["status"] == "unknown"


@pytest.mark.asyncio
async def test_delivery_sends_a_video_not_only_a_link_and_syncs_history():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock


    actor = await user_actor(credits=50)
    provider = Provider()
    output = Path('static/uploads/wan3_prime/results/test-media-delivery.mp4')
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5),
        preset_manager=Prices({'720p': 2}), transport=provider, downloader=Downloader(output))
    quote = await lifecycle.quote(actor, body())
    launched = await lifecycle.launch(actor, body(), quote, 'media-delivery-key')
    provider.statuses['provider_1'] = {'taskId': 'provider_1', 'state': 'success',
        'response': {'resultUrls': ['https://kie.example.com/out.mp4']}}
    await lifecycle.reconcile_once(provider_task_id='provider_1')
    bot = SimpleNamespace(send_video=AsyncMock(return_value=SimpleNamespace(message_id=91)),
                          send_message=AsyncMock(return_value=SimpleNamespace(message_id=92)))
    try:
        assert await lifecycle.deliver_ready_once(bot) == 1
        assert bot.send_video.await_count == 1
        assert bot.send_message.await_count == 0
        assert await lifecycle.deliver_ready_once(bot) == 0
        row = await database.get_task_by_id(launched['task_id'])
        import json
        assert json.loads(row.request_data)['delivery_status'] == 'delivered'
        assert provider.creates == 1
    finally:
        output.unlink(missing_ok=True)
