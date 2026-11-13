import pytest

from bot.shared_accounts.actor import PlatformActor
from bot.shared_accounts.native_bootstrap import (
    VkNativeAppAdapter,
    VkNativeBootstrapService,
)

ACTOR = PlatformActor(
    platform="vk", external_id=2001, shared_account_id="a" * 32,
    linked_platforms=("vk",), linked_telegram_id=None,
)


@pytest.mark.asyncio
async def test_bootstrap_uses_native_wallet_models_tasks_and_packages(monkeypatch):
    async def state(owner):
        assert owner == 2001
        return {"registered": True, "is_blocked": False, "balance": 12.5,
                "tasks": [{"task_id": 7, "task_type": "photo", "model": "nano_banana_pro",
                           "status": "completed", "cost": 2.5, "result_url": "https://example.test/a.jpg",
                           "created_at": "2026-11-12 00:00:00"}]}
    async def models(owner):
        return {"ok": True, "photo_models": [{"id": "nano_banana_pro", "label": "Nano",
            "ratios": ["1:1"], "resolutions": ["2K"], "max_references": 4,
            "cost": 2.5, "quality_costs": {"2K": 2.5}}],
            "video_models": [{"id": "v3_pro", "label": "Kling", "ratios": ["16:9"],
            "duration_min": 5, "duration_max": 6, "durations": [5, 6],
            "scenarios": ["text", "imgtxt"], "max_image_references": 4,
            "costs": {"5": 15, "6": 18}}]}
    async def commerce(owner):
        return {"ok": True, "registered": True, "balance": 12.5, "payments_enabled": False,
                "payment_packages": [{"id": "250", "price_rub": 250, "credits": 25,
                                      "lava_offer_id": None, "methods": []}],
                "payments": [], "referrals": {"first_level_count": 0,
                "second_level_count": 0, "earned_rub": 0}}
    service = VkNativeBootstrapService(state_reader=state, model_reader=models, commerce_reader=commerce)
    data = await service.bootstrap(ACTOR)
    assert data["ok"] is True and data["credits"] == 12.5
    assert data["telegram_chat_available"] is False
    assert data["image_models"][0]["quality_costs"] == {"2K": 2.5}
    assert data["video_models"][0]["costs"] == {"5": 15.0, "6": 18.0}
    assert data["recent_tasks"][0]["task_id"] == "vk:7"
    assert data["payment_packages"][0]["price_rub"] == 250
    assert "telegram_id" not in data


@pytest.mark.asyncio
async def test_bootstrap_fails_closed_on_invalid_wallet_or_non_vk_actor():
    async def state(_): return {"registered": True, "is_blocked": False, "balance": 10, "tasks": []}
    async def models(_): return {"ok": True, "photo_models": [], "video_models": []}
    async def commerce(_): return {"ok": True, "registered": True, "balance": float("nan"),
        "payment_packages": [], "payments": [], "referrals": {}}
    service = VkNativeBootstrapService(state_reader=state, model_reader=models, commerce_reader=commerce)
    with pytest.raises(RuntimeError, match="price"):
        await service.bootstrap(ACTOR)
    with pytest.raises(PermissionError):
        await service.bootstrap(PlatformActor("telegram", 2001, "b" * 32, ("telegram",), 2001))


def test_incremental_adapter_does_not_claim_full_vk_readiness():
    assert VkNativeAppAdapter.ready_operations == frozenset({"bootstrap", "tasks"})


@pytest.mark.asyncio
async def test_blocked_bootstrap_stops_before_catalogue_or_commerce():
    from unittest.mock import AsyncMock

    state = AsyncMock(return_value={"registered": True, "is_blocked": True, "balance": 10, "tasks": []})
    downstream = AsyncMock()
    service = VkNativeBootstrapService(state_reader=state, model_reader=downstream, commerce_reader=downstream)
    with pytest.raises(PermissionError):
        await service.bootstrap(ACTOR)
    downstream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("state", None), ("models", []), ("commerce", None)])
async def test_bootstrap_rejects_malformed_upstream_with_stable_error(field, value):
    from unittest.mock import AsyncMock

    responses = {
        "state": {"registered": True, "is_blocked": False, "balance": 10, "tasks": []},
        "models": {"ok": True, "photo_models": [], "video_models": []},
        "commerce": {"ok": True, "registered": True, "balance": 10, "payment_packages": []},
    }
    responses[field] = value
    service = VkNativeBootstrapService(**{
        name: AsyncMock(return_value=responses[key])
        for name, key in (("state_reader", "state"), ("model_reader", "models"), ("commerce_reader", "commerce"))
    })
    with pytest.raises(RuntimeError, match="Invalid native VK"):
        await service.bootstrap(ACTOR)


@pytest.mark.asyncio
async def test_bootstrap_uses_latest_native_commerce_balance_during_concurrent_debit():
    from unittest.mock import AsyncMock

    service = VkNativeBootstrapService(
        state_reader=AsyncMock(return_value={"registered": True, "is_blocked": False, "balance": 10, "tasks": []}),
        model_reader=AsyncMock(return_value={"ok": True, "photo_models": [], "video_models": []}),
        commerce_reader=AsyncMock(return_value={"ok": True, "registered": True, "balance": 9, "payment_packages": []}),
    )
    assert (await service.bootstrap(ACTOR))["credits"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("collection", ["photo_models", "video_models", "payment_packages"])
async def test_bootstrap_rejects_incomplete_catalogue_items(collection):
    from unittest.mock import AsyncMock

    models = {"ok": True, "photo_models": [], "video_models": []}
    commerce = {"ok": True, "registered": True, "balance": 10, "payment_packages": []}
    (commerce if collection == "payment_packages" else models)[collection] = [{}]
    service = VkNativeBootstrapService(
        state_reader=AsyncMock(return_value={"registered": True, "is_blocked": False, "balance": 10, "tasks": []}),
        model_reader=AsyncMock(return_value=models), commerce_reader=AsyncMock(return_value=commerce),
    )
    with pytest.raises(RuntimeError, match="Invalid native VK"):
        await service.bootstrap(ACTOR)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("private upstream endpoint"), RuntimeError("private payload")])
async def test_gateway_redacts_bootstrap_upstream_failures(monkeypatch, failure):
    from unittest.mock import AsyncMock

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot.shared_accounts import gateway

    monkeypatch.setenv("VK_FULL_APP_PARITY_ENABLED", "1")
    monkeypatch.setattr(gateway, "resolve_platform_actor", AsyncMock(return_value=ACTOR))
    service = VkNativeBootstrapService(state_reader=AsyncMock(side_effect=failure))
    adapter = VkNativeAppAdapter(bootstrap=service)
    # Test the gateway's error boundary in isolation, without advertising the
    # incomplete production adapter as fully ready.
    monkeypatch.setattr(gateway, "full_vk_adapter", lambda app: adapter)
    app = web.Application(middlewares=[gateway.vk_miniapp_gateway()])
    legacy = AsyncMock()
    app.router.add_post('/mini-app/api/bootstrap', legacy)
    async with TestClient(TestServer(app)) as client:
        result = await client.post('/mini-app/api/bootstrap', json={"init_data": "vk_session:test"})
        assert result.status == 503
        assert await result.json() == {"ok": False, "error": "Service temporarily unavailable"}
    legacy.assert_not_awaited()
