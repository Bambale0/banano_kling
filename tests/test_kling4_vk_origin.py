"""Kling4 destinations survive retries and worker restarts."""
import json

import pytest

from bot import database
from tests.test_kling4 import engine_context as engine_context  # noqa: PLC0414

pytestmark = pytest.mark.asyncio


async def test_launch_freezes_verified_vk_origin_across_idempotent_replay(engine_context):
    engine, actor, provider = engine_context
    actor.miniapp_context = {
        "platform": "vk",
        "platform_external_id": 2001,
        "shared_account_id": "a" * 32,
        "vk_chat_delivery_requested": True,
    }
    request = {"mode": "reference", "input": {"prompt": "VK launch", "duration": 3}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(actor, request, quote["quote_hash"], "vk-origin-launch")
    actor.miniapp_context = {"platform": "telegram"}
    replay = await engine.launch(actor, request, quote["quote_hash"], "vk-origin-launch")
    assert replay["task_id"] == result["task_id"] and provider.calls == 1
    task = await database.get_task_by_id(result["task_id"])
    metadata = json.loads(task.request_data)
    assert metadata["origin_platform"] == "vk"
    assert metadata["origin_vk_user_id"] == 2001
    assert metadata["origin_account_id"] == "a" * 32
    assert metadata["vk_chat_delivery_requested"] is True
    assert task.user_id == actor.user_id


@pytest.mark.parametrize("platform", ["vk", "telegram"])
@pytest.mark.parametrize("state", ["success", "fail"])
async def test_terminal_delivery_uses_persisted_origin_after_restart(
    engine_context, monkeypatch, tmp_path, platform, state
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.config import config
    from bot.services import kling4_lifecycle as module
    from bot.services.wan3_prime_media import MediaInfo

    engine, actor, provider = engine_context
    actor.miniapp_context = {
        "platform": platform,
        "platform_external_id": 2001,
        "shared_account_id": "a" * 32,
        "vk_chat_delivery_requested": True,
    }
    request = {"mode": "reference", "input": {"prompt": "Saved origin", "duration": 3}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(actor, request, quote["quote_hash"], "vk-terminal-launch")
    task_id = result["task_id"]
    provider.payload.update(
        state=state, resultJson=json.dumps({"resultUrls": ["https://provider.test/video.mp4"]})
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://media.test")

    async def download(_url, *, destination, **_kwargs):
        destination.write_bytes(b"synthetic-video")

    monkeypatch.setattr(module, "fetch_public_asset", download)
    monkeypatch.setattr(
        module.ActualWan3PrimeProbe, "probe_file",
        AsyncMock(return_value=MediaInfo(kind="video", duration_seconds=3, size_bytes=15)),
    )
    await engine.reconcile(task_id)
    bot = SimpleNamespace(send_video=AsyncMock(), send_message=AsyncMock())
    # The background worker has no actor or Mini App context at all.
    restart = module.Kling4Lifecycle(transport=provider)
    restart.telegram_bot = bot
    await restart.deliver(task_id)
    await restart.deliver(task_id)
    terminal = await restart.status(actor, task_id)
    assert terminal["delivery_status"] == ("available_in_app" if platform == "vk" else "delivered")
    task = await database.get_task_by_id(task_id)
    assert task.status == ("completed" if state == "success" else "failed")
    if platform == "vk":
        bot.send_video.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        if state == "success":
            assert json.loads(task.request_data)["delivery_status"] == "available_in_app"
    elif state == "success":
        bot.send_video.assert_awaited_once()
        bot.send_message.assert_not_awaited()
    else:
        bot.send_message.assert_awaited_once()
        bot.send_video.assert_not_awaited()
    assert provider.calls == 1


async def test_vk_outbox_retry_without_telegram_bot_preserves_recipient(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot import db
    from bot.services.kling4_lifecycle import Kling4Lifecycle
    from bot.services.vk_result_delivery import VKDeliveryQueue
    from tests.test_kling4 import Probe
    from tests.test_vk_result_delivery import actor as linked_vk_actor
    from tests.test_vk_result_delivery import transport

    async with linked_vk_actor(monkeypatch) as (_client, _headers, user, account):
        monkeypatch.chdir(tmp_path)
        provider = SimpleNamespace(
            create=AsyncMock(return_value=(200, {"code": 200, "data": {"taskId": "kie-vk"}}))
        )
        engine = Kling4Lifecycle(transport=provider, probe=Probe())
        await engine.init_schema()
        actor = SimpleNamespace(
            user_id=user.id, telegram_id=user.telegram_id, is_admin=True,
            miniapp_context={
                "platform": "vk", "platform_external_id": 2001,
                "shared_account_id": account, "vk_chat_delivery_requested": True,
            },
        )
        request = {"mode": "reference", "input": {"prompt": "VK outbox", "duration": 3}}
        quote = await engine.quote(actor, request)
        result = await engine.launch(actor, request, quote["quote_hash"], "vk-outbox-launch")
        task_id = result["task_id"]
        # Seed the durable terminal state at the delivery worker's public seam.
        async with db.connect(database.DATABASE_PATH) as conn:
            await conn.execute(
                "UPDATE kling4_intents SET status='done',result_url=? WHERE task_id=?",
                ("https://media.test/video.mp4", task_id),
            )
            await conn.commit()

        restart = Kling4Lifecycle()
        complete = database.complete_task_in_app
        monkeypatch.setattr(database, "complete_task_in_app", AsyncMock(return_value=False))
        with pytest.raises(RuntimeError, match="completion deferred"):
            await restart.deliver(task_id)
        assert (await restart.status(actor, task_id))["delivery_status"] == "retry"
        monkeypatch.setattr(database, "complete_task_in_app", complete)
        await restart.deliver(task_id)
        await restart.deliver(task_id)
        assert (await restart.status(actor, task_id))["delivery_status"] == "available_in_app"
        sender = transport()
        queue = VKDeliveryQueue(sender)
        await queue.reconcile()
        await queue.tick()
        await queue.tick()
        sender.send.assert_awaited_once()
        accepted = sender.send.await_args.args[0]
        assert accepted["vk_user_id"] == 2001
        assert accepted["account_id"] == account
        assert accepted["result_url"] == "https://media.test/video.mp4"
        provider.create.assert_awaited_once()
        task = await database.get_task_by_id(task_id)
        assert task.user_id == user.id
        assert json.loads(task.request_data)["origin_vk_user_id"] == 2001


async def test_invalid_vk_origin_never_submits_or_charges(engine_context):
    engine, actor, provider = engine_context
    actor.miniapp_context = {"platform": "vk", "platform_external_id": 2001}
    before = (await database.get_or_create_user(actor.telegram_id)).credits
    request = {"mode": "reference", "input": {"prompt": "Invalid origin", "duration": 3}}
    quote = await engine.quote(actor, request)
    with pytest.raises(ValueError, match="invalid_vk_account"):
        await engine.launch(actor, request, quote["quote_hash"], "vk-invalid-origin")
    assert provider.calls == 0
    assert (await database.get_or_create_user(actor.telegram_id)).credits == before
    # A rejected origin must leave no idempotency record that masks a valid retry.
    actor.miniapp_context = {"platform": "telegram"}
    result = await engine.launch(actor, request, quote["quote_hash"], "vk-invalid-origin")
    assert result["status"] == "pending" and provider.calls == 1
