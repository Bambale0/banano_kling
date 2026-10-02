from unittest.mock import AsyncMock

import pytest

import bot.services.ai_assistant_service as assistant_module
from bot.services.ai_assistant_service import AIAssistantService


@pytest.mark.asyncio
async def test_text_assistant_uses_openrouter_qwen38(monkeypatch):
    qwen = assistant_module.openrouter_qwen38_service
    monkeypatch.setattr(qwen, "enabled", True)
    monkeypatch.setattr(qwen, "model", "qwen/qwen3.8-max-0902")
    analyze = AsyncMock(return_value="Готовый ответ")
    monkeypatch.setattr(qwen, "analyze_text", analyze)

    service = AIAssistantService()
    monkeypatch.setattr(service, "_get_system_prompt", lambda **_kwargs: "system")
    monkeypatch.setattr(service, "_format_context", lambda _context: "context")
    monkeypatch.setattr(service, "get_pricing_info", lambda: "prices")

    result = await service.get_assistant_response(
        "Какую модель выбрать?",
        {"is_admin": False},
    )

    assert result == "Готовый ответ"
    analyze.assert_awaited_once()
    kwargs = analyze.await_args.kwargs
    assert kwargs["system_prompt"] == "system"
    assert "context" in kwargs["user_instruction"]
    assert "prices" in kwargs["user_instruction"]
    assert "Какую модель выбрать?" in kwargs["user_instruction"]
    assert kwargs["json_response"] is False
    assert kwargs["reasoning_effort"] == "medium"


@pytest.mark.asyncio
async def test_text_assistant_returns_none_when_qwen_unavailable(monkeypatch):
    qwen = assistant_module.openrouter_qwen38_service
    monkeypatch.setattr(qwen, "enabled", False)

    result = await AIAssistantService().get_assistant_response("hello")

    assert result is None
