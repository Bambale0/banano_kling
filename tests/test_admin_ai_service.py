import pytest

from bot.services.admin_ai_service import AdminAIService


@pytest.mark.asyncio
async def test_admin_ai_fallback_plans_add_credits(monkeypatch):
    monkeypatch.setattr("bot.services.admin_ai_service.config.KIE_AI_API_KEY", "")
    service = AdminAIService()

    plan = await service.plan_action("начисли 50 BoomCoin пользователю 123456789")

    assert plan["action"] == "add_credits"
    assert plan["params"] == {"telegram_id": 123456789, "amount": 50}
    assert plan["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_admin_ai_fallback_plans_maintenance_status(monkeypatch):
    monkeypatch.setattr("bot.services.admin_ai_service.config.KIE_AI_API_KEY", "")
    service = AdminAIService()

    plan = await service.plan_action("какой сейчас техрежим?")

    assert plan["action"] == "maintenance_status"
    assert plan["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_admin_ai_fallback_plans_promo_without_code_digits(monkeypatch):
    monkeypatch.setattr("bot.services.admin_ai_service.config.KIE_AI_API_KEY", "")
    service = AdminAIService()

    plan = await service.plan_action("создай промокод VIP20 скидка 25 лимит 100")

    assert plan["action"] == "create_promo"
    assert plan["params"]["code"] == "VIP20"
    assert plan["params"]["promo_type"] == "discount"
    assert plan["params"]["value"] == 25
    assert plan["params"]["max_uses"] == 100
    assert plan["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_admin_ai_fallback_plans_agent_report(monkeypatch):
    monkeypatch.setattr("bot.services.admin_ai_service.config.KIE_AI_API_KEY", "")
    service = AdminAIService()

    plan = await service.plan_action("сделай отчёт по боту и проверь логи")

    assert plan["action"] == "bot_report"
    assert [item["action"] for item in plan["actions"]] == [
        "stats",
        "maintenance_status",
        "list_promos",
        "analyze_logs",
    ]
    assert plan["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_admin_ai_fallback_plans_research(monkeypatch):
    monkeypatch.setattr("bot.services.admin_ai_service.config.KIE_AI_API_KEY", "")
    service = AdminAIService()

    plan = await service.plan_action("найди новые ИИ в сфере генерации контента")

    assert plan["action"] == "research_ai"
    assert plan["params"]["query"]
    assert plan["requires_confirmation"] is False
