"""Kling callback routing must use the persisted generation origin."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from tests.test_generation_origin_delivery import (
    main_module as main_module,  # noqa: PLC0414 - pytest fixture
)


def payload_for(shape, task_id, url="https://example.test/result.mp4", failed=False):
    if shape == "code200":
        return {"code": 200, "taskId": task_id, "data": {"result_video_url": url}}
    if shape == "legacy":
        return {
            "code": 200,
            "data": {
                "taskId": task_id,
                "state": "fail" if failed else "success",
                "failMsg": "Synthetic rejected input",
                "failCode": "422",
                "resultJson": json.dumps({"resultUrls": [] if failed else [url]}),
            },
        }
    return {
        "id": task_id,
        "status": "failed" if failed else "succeeded",
        "output": url if shape == "fallback_string" else {"video_url": url},
        "error": "Synthetic rejected input",
    }


def fake_bot():
    return SimpleNamespace(
        **{
            name: AsyncMock()
            for name in (
                "send_video",
                "send_document",
                "send_photo",
                "send_message",
                "get_chat",
            )
        }
    )


@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
@pytest.mark.parametrize("missed_first_reward", [False, True])
async def test_vk_kling_success_records_author_reward_once(
    monkeypatch, main_module, shape, missed_first_reward
):
    author = await database.get_or_create_user(885001)
    user = await database.get_or_create_user(885002)
    inviter = await database.get_or_create_user(885003)
    assert await database.process_referral(user.telegram_id, inviter.referral_code)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "source",
        "video",
        "no_preset",
        model="kling",
        cost=2,
    )
    await database.complete_video_task("source", "https://example.test/source.mp4")
    source = await database.share_to_feed("source", author.id)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-kling",
        "video",
        "no_preset",
        model="kling",
        cost=2,
        source_feed_gen_id=source["id"],
        request_data={"origin_platform": "vk"},
    )
    assert (await database.get_partner_overview(author.telegram_id))[
        "prompt_repeat_total_rub"
    ] == 0
    if missed_first_reward:
        credit = database.credit_feed_prompt_repeat
        calls = 0

        async def transient_credit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Synthetic transient reward failure")
            return await credit(*args, **kwargs)

        monkeypatch.setattr(database, "credit_feed_prompt_repeat", transient_credit)
    bot = fake_bot()
    persisted_url = "https://example.test/durable-result.mp4"
    persist = AsyncMock(return_value=persisted_url)
    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", persist)
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        for url in (
            "https://example.test/result.mp4",
            "https://example.test/duplicate.mp4",
        ):
            response = await client.post(
                "/callback", json=payload_for(shape, "vk-kling", url)
            )
            assert response.status == 200
    task = await database.get_task_by_id("vk-kling")
    assert task.status == "completed"
    assert task.result_url == persisted_url
    persist.assert_awaited_once_with(
        "https://example.test/result.mp4", task_type="video"
    )
    metadata = json.loads(task.request_data)
    assert metadata["delivery_status"] == "available_in_app"
    overview = await database.get_partner_overview(author.telegram_id)
    assert overview["prompt_repeat_total_rub"] == 5
    assert overview["prompt_repeat_balance_rub"] == 5
    assert (await database.get_or_create_user(inviter.telegram_id)).referral_earned == 3
    for mock in vars(bot).values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("shape", ["legacy", "fallback"])
async def test_vk_kling_failure_refunds_once_without_telegram(main_module, shape):
    user = await database.get_or_create_user(885002)
    initial = float(user.credits)
    assert await database.deduct_credits(user.telegram_id, 1)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-kling",
        "video",
        "no_preset",
        model="kling",
        cost=1,
        request_data={"origin_platform": "vk"},
    )
    bot = fake_bot()
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        for _ in range(2):
            response = await client.post(
                "/callback", json=payload_for(shape, "vk-kling", failed=True)
            )
            assert response.status == 200
    assert (await database.get_task_by_id("vk-kling")).status == "failed"
    assert (
        float((await database.get_or_create_user(user.telegram_id)).credits) == initial
    )
    for mock in vars(bot).values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
async def test_telegram_kling_success_still_delivers(monkeypatch, main_module, shape):
    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "tg-kling",
        "video",
        "no_preset",
        model="kling",
        cost=1,
        request_data={"origin_platform": "telegram"},
    )
    bot = fake_bot()
    monkeypatch.setattr(
        main_module,
        "_persist_result_url_if_needed",
        AsyncMock(side_effect=lambda url, **kwargs: url),
    )
    monkeypatch.setattr(
        database, "can_attempt_telegram_delivery", AsyncMock(return_value=True)
    )
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    payload = payload_for(shape, "tg-kling")
    payload["origin_platform"] = "vk"  # Provider content cannot override stored origin.
    async with TestClient(TestServer(app)) as client:
        for _ in range(2):
            assert (await client.post("/callback", json=payload)).status == 200
    assert (await database.get_task_by_id("tg-kling")).status == "completed"
    bot.send_video.assert_awaited_once()


@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
async def test_failed_vk_task_ignores_late_success(monkeypatch, main_module, shape):
    from bot.services import task_watchdog

    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-kling",
        "video",
        "no_preset",
        model="kling",
        cost=0,
        request_data={"origin_platform": "vk"},
    )
    task = await database.get_task_by_id("vk-kling")
    assert await task_watchdog.force_fail_task(
        task.id, user.id, 0, provider_confirmed_failed=True
    )
    bot = fake_bot()
    persist = AsyncMock()
    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", persist)
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        assert (
            await client.post("/callback", json=payload_for(shape, "vk-kling"))
        ).status == 200
    assert (await database.get_task_by_id("vk-kling")).status == "failed"
    persist.assert_not_awaited()
    for mock in vars(bot).values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
async def test_overlapping_vk_callbacks_download_only_once(
    monkeypatch, main_module, shape
):
    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-overlap",
        "video",
        "no_preset",
        model="kling",
        request_data={"origin_platform": "vk"},
    )
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def persist(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return url.replace("provider", "durable")

    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", persist)
    app = web.Application()
    app["bot"] = fake_bot()
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        first = asyncio.create_task(
            client.post(
                "/callback",
                json=payload_for(
                    shape, "vk-overlap", "https://example.test/provider-first.mp4"
                ),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            second = await client.post(
                "/callback",
                json=payload_for(
                    shape, "vk-overlap", "https://example.test/provider-second.mp4"
                ),
            )
            assert second.status == 503
            assert len(calls) == 1
        finally:
            release.set()
            assert (await first).status == 200
        assert (
            await client.post(
                "/callback",
                json=payload_for(
                    shape, "vk-overlap", "https://example.test/provider-second.mp4"
                ),
            )
        ).status == 200
    assert len(calls) == 1
    assert (
        await database.get_task_by_id("vk-overlap")
    ).result_url == "https://example.test/durable-first.mp4"


@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
@pytest.mark.parametrize("failure", [RuntimeError("download failed"), TimeoutError()])
async def test_vk_download_failure_releases_claim_for_retry(
    monkeypatch, main_module, shape, failure
):
    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-retry",
        "video",
        "no_preset",
        model="kling",
        request_data={"origin_platform": "vk"},
    )
    persist = AsyncMock(side_effect=[failure, "https://example.test/durable.mp4"])
    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", persist)
    app = web.Application()
    app["bot"] = fake_bot()
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        payload = payload_for(shape, "vk-retry")
        assert (await client.post("/callback", json=payload)).status == 503
        task = await database.get_task_by_id("vk-retry")
        assert task.status == "pending"
        assert "vk_result_persistence" not in json.loads(task.request_data)
        assert (await client.post("/callback", json=payload)).status == 200
    assert persist.await_count == 2
    assert (
        await database.get_task_by_id("vk-retry")
    ).result_url == "https://example.test/durable.mp4"


async def test_vk_expired_owner_cannot_commit_or_release_new_claim(monkeypatch):
    from datetime import datetime, timedelta

    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-lease",
        "video",
        "no_preset",
        model="kling",
        request_data={"origin_platform": "vk"},
    )
    first = await database.claim_vk_result_persistence("vk-lease", lease_seconds=30)
    assert first
    assert (
        await database.claim_vk_result_persistence("vk-lease", lease_seconds=30) is None
    )

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=31)

    monkeypatch.setattr(database, "datetime", Later)
    assert not await database.store_task_result_ready(
        "vk-lease", "https://example.test/stale.mp4", persistence_token=first
    )
    replacement = await database.claim_vk_result_persistence(
        "vk-lease", lease_seconds=30
    )
    assert replacement and replacement != first
    assert not await database.release_vk_result_persistence("vk-lease", first)
    assert not await database.store_task_result_ready(
        "vk-lease", "https://example.test/stale.mp4", persistence_token=first
    )
    assert await database.store_task_result_ready(
        "vk-lease", "https://example.test/canonical.mp4", persistence_token=replacement
    )
    assert not await database.release_vk_result_persistence("vk-lease", first)
    assert not await database.store_task_result_ready(
        "vk-lease", "https://example.test/stale.mp4", persistence_token=first
    )
    assert await database.store_task_result_ready(
        "vk-lease", "https://example.test/other.mp4"
    )
    assert (
        await database.get_task_by_id("vk-lease")
    ).result_url == "https://example.test/canonical.mp4"


async def test_vk_result_ready_is_first_writer_wins_before_delivery_terminal():
    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-ready",
        "video",
        "no_preset",
        model="kling",
        request_data={"origin_platform": "vk"},
    )
    assert await database.store_task_result_ready(
        "vk-ready", "https://example.test/first.mp4"
    )
    task = await database.get_task_by_id("vk-ready")
    assert json.loads(task.request_data)["delivery_status"] == "result_ready"
    assert await database.store_task_result_ready(
        "vk-ready", "https://example.test/second.mp4"
    )
    assert await database.complete_task_in_app(
        "vk-ready", "https://example.test/third.mp4"
    )
    assert (
        await database.get_task_by_id("vk-ready")
    ).result_url == "https://example.test/first.mp4"


async def test_vk_preparation_timeout_cancels_download_and_releases_lease(
    monkeypatch, main_module
):
    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-timeout",
        "video",
        "no_preset",
        model="kling",
        request_data={"origin_platform": "vk"},
    )
    cancelled = asyncio.Event()

    async def blocked_download(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", blocked_download)
    # A short synthetic budget exercises the real wait_for cancellation path.
    monkeypatch.setattr(main_module, "KIE_DELIVERY_LEASE_SECONDS", 10.2)
    app = web.Application()
    app["bot"] = fake_bot()
    app.router.add_post("/callback", main_module.handle_kling_webhook)
    async with TestClient(TestServer(app)) as client:
        assert (
            await client.post("/callback", json=payload_for("legacy", "vk-timeout"))
        ).status == 503
    assert cancelled.is_set()
    task = await database.get_task_by_id("vk-timeout")
    assert task.status == "pending"
    assert "vk_result_persistence" not in json.loads(task.request_data)
    assert await database.claim_vk_result_persistence("vk-timeout")


@pytest.mark.parametrize("model", ["v3_std", "v3_pro"])
@pytest.mark.parametrize("routes", [("kling", "kie"), ("kie", "kling")])
@pytest.mark.parametrize("shape", ["code200", "legacy", "fallback", "fallback_string"])
async def test_vk_kling_watchdog_cross_route_overlap(
    monkeypatch, main_module, model, routes, shape
):
    from bot.services import kie_webhook_verification

    user = await database.get_or_create_user(885002)
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        "vk-cross-route",
        "video",
        "no_preset",
        model=model,
        request_data={"origin_platform": "vk"},
    )
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def persist(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return url.replace("provider", "durable")

    monkeypatch.setattr(main_module, "_persist_result_url_if_needed", persist)
    monkeypatch.setattr(
        kie_webhook_verification,
        "canonical_kie_callback",
        AsyncMock(side_effect=lambda payload: (payload, 200)),
    )
    monkeypatch.setattr(main_module.config, "KIE_AI_WEBHOOK_SECRET", "synthetic")
    app = web.Application()
    bot = fake_bot()
    app["bot"] = bot
    app.router.add_post("/kling", main_module.handle_kling_webhook)
    app.router.add_post("/kie", main_module.handle_kie_ai_webhook)

    def payload(route, suffix):
        return payload_for(
            "legacy" if route == "kie" else shape,
            "vk-cross-route",
            f"https://example.test/provider-{suffix}.mp4",
        )

    async with TestClient(TestServer(app)) as client:
        first = asyncio.create_task(
            client.post(
                f"/{routes[0]}?secret=synthetic", json=payload(routes[0], "first")
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            second = await client.post(
                f"/{routes[1]}?secret=synthetic", json=payload(routes[1], "second")
            )
            assert second.status == 503
            assert len(calls) == 1
        finally:
            release.set()
            assert (await first).status == 200
    assert len(calls) == 1
    assert (
        await database.get_task_by_id("vk-cross-route")
    ).result_url == "https://example.test/durable-first.mp4"
    for mock in vars(bot).values():
        mock.assert_not_awaited()
