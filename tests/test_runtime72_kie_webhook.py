"""Provider-authenticated status, rather than callback bytes, controls effects."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, main
from bot.handlers import seedance_25_fullstack as seedance
from bot.services import task_watchdog
from bot.services.kie_market_service import kie_market_service
from bot.services.veo_service import veo_service


class Request(dict):
    def __init__(self, payload, bot):
        super().__init__()
        self.payload = payload
        self.headers = {"X-Webhook-Signature": "broken-signature"}
        self.query = {}
        self.app = {"bot": bot}

    async def read(self):
        return json.dumps(self.payload).encode()

    async def json(self):
        return self.payload


@pytest.fixture
def setup_webhook(monkeypatch):
    task = database.GenerationTask(
        id=1,
        user_id=1,
        telegram_id=101,
        task_id="provider-task",
        type="image",
        preset_id="new",
        model="nano-banana-2-lite",
        cost=5,
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        send_photo=AsyncMock(),
        send_document=AsyncMock(),
        send_video=AsyncMock(),
    )
    lookup = AsyncMock(return_value=task)
    refund = AsyncMock()
    complete = AsyncMock()
    claim = AsyncMock(return_value=False)
    monkeypatch.setattr(task_watchdog, "force_fail_task", claim)
    process = AsyncMock()
    monkeypatch.setattr(database, "get_task_by_id", lookup)
    monkeypatch.setattr(database, "add_credits", refund)
    monkeypatch.setattr(database, "complete_video_task", complete)
    monkeypatch.setattr(seedance, "_process_seedance25_payload", process)
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=101))
    monkeypatch.setattr(main.config, "KIE_AI_WEBHOOK_SECRET", "")
    provider = AsyncMock(return_value={"taskId": task.task_id, "state": "generating"})
    monkeypatch.setattr(kie_market_service, "get_task_status", provider)
    return SimpleNamespace(
        task=task,
        bot=bot,
        lookup=lookup,
        refund=refund,
        complete=complete,
        process=process,
        provider=provider,
        claim=claim,
    )


def payload(state="fail", **fields):
    return {
        "code": 200,
        "data": {
            "taskId": "provider-task",
            "state": state,
            "model": "nano-banana-2-lite",
            "failCode": "400",
            "failMsg": "test failure",
            **fields,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        main.handle_kie_ai_webhook,
        main.handle_kie_market_webhook,
        seedance.seedance25_webhook,
    ],
)
async def test_forged_failure_cannot_fail_pending_provider_task(setup_webhook, handler):
    env = setup_webhook
    response = await handler(Request(payload(), env.bot))
    assert response.status == 200
    env.provider.assert_awaited_once_with("provider-task")
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()
    env.complete.assert_not_awaited()
    env.bot.send_message.assert_not_awaited()
    env.process.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        main.handle_kie_ai_webhook,
        main.handle_kie_market_webhook,
        seedance.seedance25_webhook,
    ],
)
@pytest.mark.parametrize(
    "canonical",
    [
        None,
        {"taskId": "other-task", "state": "fail"},
        {"taskId": "provider-task"},
        TimeoutError(),
    ],
)
async def test_provider_lookup_failure_is_retryable_without_effects(
    setup_webhook, handler, canonical
):
    env = setup_webhook
    if isinstance(canonical, Exception):
        env.provider.side_effect = canonical
    else:
        env.provider.return_value = canonical
    response = await handler(Request(payload(), env.bot))
    assert response.status == 503
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()
    env.complete.assert_not_awaited()
    env.bot.send_message.assert_not_awaited()
    env.process.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unknown", "stale_alias", "failed", "completed"])
async def test_unknown_stale_or_terminal_task_has_no_effects(setup_webhook, kind):
    env = setup_webhook
    if kind == "unknown":
        env.lookup.return_value = None
    elif kind == "stale_alias":
        env.task.task_id = "new-provider-task"
    else:
        env.task.status = kind
    response = await main.handle_kie_ai_webhook(Request(payload(), env.bot))
    assert response.status == 200
    env.provider.assert_not_awaited()
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()
    env.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance_passes_only_authoritative_result_without_hmac_dependency(
    setup_webhook, monkeypatch
):
    env = setup_webhook
    monkeypatch.setattr(
        kie_market_service, "webhook_hmac_key", "configured-but-unreliable"
    )
    canonical = {
        "taskId": "provider-task",
        "state": "success",
        "model": "bytedance/seedance-2.5",
        "resultJson": json.dumps(
            {"resultUrls": ["https://provider.example/result.mp4"]}
        ),
    }
    env.provider.return_value = canonical
    response = await seedance.seedance25_webhook(
        Request(
            payload(
                "success",
                resultJson=json.dumps({"resultUrls": ["https://attacker.invalid/x"]}),
            ),
            env.bot,
        )
    )
    assert response.status == 200
    assert env.process.await_args.args[1]["data"] == canonical


@pytest.mark.asyncio
async def test_generic_failure_refund_uses_atomic_claim_once(
    setup_webhook, monkeypatch
):
    env = setup_webhook
    env.provider.return_value = {
        "taskId": "provider-task",
        "state": "fail",
        "failCode": "400",
        "failMsg": "test failure",
    }
    claim = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(task_watchdog, "force_fail_task", claim)
    responses = await asyncio.gather(
        *(main.handle_kie_ai_webhook(Request(payload(), env.bot)) for _ in range(2))
    )
    assert [x.status for x in responses] == [200, 200]
    assert claim.await_count == 2
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()
    env.complete.assert_not_awaited()
    env.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler", [main.handle_kie_ai_webhook, main.handle_kie_market_webhook]
)
async def test_generic_success_uses_only_canonical_url(
    setup_webhook, monkeypatch, handler
):
    env = setup_webhook
    canonical_url = "https://provider.example/result.png"
    env.provider.return_value = {
        "taskId": "provider-task",
        "state": "success",
        "model": "nano-banana-2-lite",
        "resultJson": json.dumps({"resultUrls": [canonical_url]}),
    }
    persist = AsyncMock(side_effect=lambda url, **kw: url)
    monkeypatch.setattr(main, "_persist_result_url_if_needed", persist)
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_send_original_file", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "mark_task_delivery_status", AsyncMock())
    monkeypatch.setattr(
        kie_market_service, "webhook_hmac_key", "configured-but-unreliable"
    )
    response = await handler(
        Request(
            payload(
                "success",
                resultJson=json.dumps({"resultUrls": ["https://attacker.invalid/x"]}),
            ),
            env.bot,
        )
    )
    assert response.status == 200
    assert persist.await_args.args[0] == canonical_url
    assert env.bot.send_photo.await_args.kwargs["photo"] == canonical_url
    assert env.complete.await_args.args == ("provider-task", canonical_url)
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_veo_uses_stored_model_and_authenticated_veo_record(
    setup_webhook, monkeypatch
):
    env = setup_webhook
    env.task.model = "veo3_fast"
    env.task.type = "video"
    canonical_url = "https://provider.example/result.mp4"
    details = AsyncMock(
        return_value={
            "code": 200,
            "data": {
                "taskId": "provider-task",
                "successFlag": 1,
                "response": {"resultUrls": [canonical_url]},
            },
        }
    )
    monkeypatch.setattr(veo_service, "get_video_details", details)
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(side_effect=lambda url, **kw: url),
    )
    monkeypatch.setattr(database, "mark_task_delivery_status", AsyncMock())
    response = await main.handle_kie_ai_webhook(
        Request(payload("fail", model="attacker-selected-model"), env.bot)
    )
    assert response.status == 200
    details.assert_awaited_once_with("provider-task")
    env.provider.assert_not_awaited()
    assert env.bot.send_video.await_args.kwargs["video"] == canonical_url
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_during_provider_lookup_discards_old_task_result(setup_webhook):
    env = setup_webhook

    async def lookup(_task_id):
        env.task.task_id = "new-provider-task"
        return {"taskId": "provider-task", "state": "fail"}

    env.provider.side_effect = lookup
    response = await main.handle_kie_ai_webhook(Request(payload(), env.bot))
    assert response.status == 200
    env.refund.assert_not_awaited()
    env.claim.assert_not_awaited()
    env.complete.assert_not_awaited()
    env.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_database_concurrent_failed_callbacks_credit_once(monkeypatch):
    user = await database.get_or_create_user(101)
    await database.add_generation_task(
        user.id,
        101,
        "provider-task",
        "image",
        "new",
        model="nano-banana-2-lite",
        cost=5,
    )
    before = (await database.get_or_create_user(101)).credits
    monkeypatch.setattr(main.config, "KIE_AI_WEBHOOK_SECRET", "")
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(
        kie_market_service,
        "get_task_status",
        AsyncMock(
            return_value={
                "taskId": "provider-task",
                "state": "fail",
                "failCode": "400",
                "failMsg": "test failure",
            }
        ),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    responses = await asyncio.gather(
        *(main.handle_kie_ai_webhook(Request(payload(), bot)) for _ in range(4))
    )
    assert [response.status for response in responses] == [200] * 4
    assert (await database.get_or_create_user(101)).credits == before + 5
    failed = await database.get_task_by_id("provider-task")
    assert failed.status == "failed"
    assert json.loads(failed.request_data)["refund_state"] == "refunded"
    bot.send_message.assert_awaited_once()
    await main.handle_kie_ai_webhook(Request(payload(), bot))
    assert (await database.get_or_create_user(101)).credits == before + 5


@pytest.mark.asyncio
async def test_atomic_failed_claim_cannot_refund_superseded_external_id(monkeypatch):
    user = await database.get_or_create_user(101)
    await database.add_generation_task(
        user.id,
        101,
        "new-provider-task",
        "image",
        "new",
        model="nano-banana-2-lite",
        cost=5,
    )
    task = await database.get_task_by_id("new-provider-task")
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    before = (await database.get_or_create_user(101)).credits
    claimed = await task_watchdog.force_fail_task(
        task.id, task.user_id, task.cost, expected_provider_task_id="old-provider-task"
    )
    assert claimed is False
    assert (await database.get_task_by_id("new-provider-task")).status == "pending"
    assert (await database.get_or_create_user(101)).credits == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_handler",
    [
        main.handle_kie_ai_webhook,
        main.handle_kie_market_webhook,
        seedance.seedance25_webhook,
    ],
)
async def test_concurrent_callbacks_start_only_one_paid_retry(
    setup_webhook, monkeypatch, second_handler
):
    env = setup_webhook
    env.provider.return_value = {
        "taskId": "provider-task",
        "state": "fail",
        "failCode": "422",
        "failMsg": "task id is blank",
    }
    monkeypatch.setattr(main, "_is_retryable_kie_blank_task_failure", lambda *_: True)

    async def retry(task, _task_id):
        await asyncio.sleep(0)
        task.task_id = "new-provider-task"
        return task.task_id

    create = AsyncMock(side_effect=retry)
    monkeypatch.setattr(main, "_retry_transient_kie_image_failure", create)
    responses = await asyncio.gather(
        main.handle_kie_ai_webhook(Request(payload(), env.bot)),
        second_handler(Request(payload(), env.bot)),
    )
    assert [x.status for x in responses] == [200, 200]
    create.assert_awaited_once()
    env.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_success_callbacks_deliver_once(setup_webhook, monkeypatch):
    env = setup_webhook
    canonical_url = "https://provider.example/result.png"
    env.provider.return_value = {
        "taskId": "provider-task",
        "state": "success",
        "resultJson": json.dumps({"resultUrls": [canonical_url]}),
    }

    async def delivered(*_args, **_kwargs):
        await asyncio.sleep(0)

    async def complete(*_args, **_kwargs):
        env.task.status = "completed"

    env.bot.send_photo.side_effect = delivered
    env.complete.side_effect = complete
    monkeypatch.setattr(
        main,
        "_persist_result_url_if_needed",
        AsyncMock(side_effect=lambda url, **kw: url),
    )
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "_send_original_file", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "mark_task_delivery_status", AsyncMock())
    responses = await asyncio.gather(
        *(
            main.handle_kie_market_webhook(Request(payload("success"), env.bot))
            for _ in range(3)
        )
    )
    assert [response.status for response in responses] == [200] * 3
    env.bot.send_photo.assert_awaited_once()
    env.complete.assert_awaited_once()
    env.claim.assert_not_awaited()
