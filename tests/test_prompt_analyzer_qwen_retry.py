"""Regression tests for malformed Qwen prompt responses."""
from unittest.mock import AsyncMock

import pytest

from bot.services import prompt_analyzer_v2_service as module


@pytest.mark.asyncio
async def test_qwen_retries_empty_prompt_and_returns_valid_result(monkeypatch):
    client = module.openrouter_qwen38_service
    monkeypatch.setattr(client, "enabled", True)
    monkeypatch.setattr(client, "model", "qwen-test")
    analyze = AsyncMock(side_effect=[
        '{"prompt_ru":"","prompt_en":"An image"}',
        '{"prompt_ru":"Красивый пейзаж","prompt_en":"Beautiful landscape"}',
    ])
    monkeypatch.setattr(client, "analyze_text", analyze)
    result = await module.PromptAnalyzerV2Service()._analyze_with_qwen38(
        image_url="", user_instruction="Landscape",
    )
    assert result["prompt_ru"] == "Красивый пейзаж"
    assert analyze.await_count == 2


@pytest.mark.asyncio
async def test_qwen_invalid_twice_fails_without_fabricating_prompt(monkeypatch):
    client = module.openrouter_qwen38_service
    monkeypatch.setattr(client, "enabled", True)
    monkeypatch.setattr(client, "model", "qwen-test")
    analyze = AsyncMock(return_value='{"prompt_ru":"","prompt_en":"Image"}')
    monkeypatch.setattr(client, "analyze_text", analyze)
    with pytest.raises(RuntimeError, match="prompt_ru пустой"):
        await module.PromptAnalyzerV2Service()._analyze_with_qwen38(
            image_url="", user_instruction="Landscape",
        )
    assert analyze.await_count == 2


@pytest.mark.asyncio
async def test_qwen_transport_error_not_retried(monkeypatch):
    client = module.openrouter_qwen38_service
    monkeypatch.setattr(client, "enabled", True)
    monkeypatch.setattr(client, "model", "qwen-test")
    analyze = AsyncMock(side_effect=TimeoutError("upstream timeout"))
    monkeypatch.setattr(client, "analyze_text", analyze)
    with pytest.raises(TimeoutError):
        await module.PromptAnalyzerV2Service()._analyze_with_qwen38(
            image_url="", user_instruction="Landscape",
        )
    assert analyze.await_count == 1
