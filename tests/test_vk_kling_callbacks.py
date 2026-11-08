"""Kling callback routing must use the persisted generation origin."""

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
    monkeypatch.setattr(
        main_module,
        "_persist_result_url_if_needed",
        AsyncMock(side_effect=lambda url, **kwargs: url),
    )
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
    assert task.result_url == "https://example.test/result.mp4"
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
