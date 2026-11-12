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
async def test_bootstrap_fails_closed_on_wallet_mismatch_or_non_vk_actor():
    async def state(_): return {"registered": True, "is_blocked": False, "balance": 10, "tasks": []}
    async def models(_): return {"ok": True, "photo_models": [], "video_models": []}
    async def commerce(_): return {"ok": True, "registered": True, "balance": 9,
        "payment_packages": [], "payments": [], "referrals": {}}
    service = VkNativeBootstrapService(state_reader=state, model_reader=models, commerce_reader=commerce)
    with pytest.raises(RuntimeError, match="wallet"):
        await service.bootstrap(ACTOR)
    with pytest.raises(PermissionError):
        await service.bootstrap(PlatformActor("telegram", 2001, "b" * 32, ("telegram",), 2001))


def test_incremental_adapter_does_not_claim_full_vk_readiness():
    assert VkNativeAppAdapter.ready_operations == frozenset({"bootstrap", "tasks"})
