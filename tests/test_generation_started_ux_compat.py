from __future__ import annotations

import importlib

import pytest

from bot.handlers.generation_started_ux_compat import (
    _FriendlyMessageProxy,
    build_generation_started_text,
    sanitize_generation_started_text,
)

miniapp_module = importlib.import_module("bot.miniapp")


class _FakeMessage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs):
        self.calls.append((text, kwargs))
        return text


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return kwargs


def test_public_generation_started_text_keeps_trace_ids() -> None:
    text = build_generation_started_text(
        model_label="Nano Banana Pro",
        aspect_ratio="9:16",
        launched_count=1,
        unit_cost=2.5,
        reference_count=2,
        local_task_id="img_a642ba273747",
        provider_task_id="b73caaef54145e94e221414a09d76b04",
    )

    assert "🚀 <b>Генерация запущена</b>" in text
    assert "Nano Banana Pro" in text
    assert "9:16" in text
    assert "Референсов: <code>2</code>" in text
    assert "Запущено задач: <code>1</code>" in text
    assert "Списано: <code>2.5</code>🍌" in text
    assert "ID задачи: <code>img_a642ba273747</code>" in text
    assert "ID провайдера: <code>b73caaef54145e94e221414a09d76b04</code>" in text
    assert "Я пришлю его сюда сразу после готовности." in text


def test_legacy_telegram_summary_is_normalized_without_losing_trace_ids() -> None:
    legacy = (
        "🚀 <b>Генерация запущена</b>\n"
        "• Модель: <code>Nano Banana Pro</code>\n"
        "• Формат: <code>9:16</code>\n"
        "• Запущено задач: <code>1</code>\n"
        "• Списано: <code>2.5</code>🍌\n\n"
        "• <code>img_a642ba273747</code>\n"
        "  • ID провайдера: <code>b73caaef54145e94e221414a09d76b04</code>\n\n"
        "Обычно результат приходит в течение 1-3 минут."
    )

    text = sanitize_generation_started_text(legacy, reference_count=1)

    assert "Nano Banana Pro" in text
    assert "Формат: <code>9:16</code>" in text
    assert "Референсов: <code>1</code>" in text
    assert "Запущено задач: <code>1</code>" in text
    assert "Списано: <code>2.5</code>🍌" in text
    assert "ID задачи: <code>img_a642ba273747</code>" in text
    assert "ID провайдера: <code>b73caaef54145e94e221414a09d76b04</code>" in text
    assert "1–3 минут" in text
    assert text.endswith("Я пришлю его сюда сразу после готовности.")


def test_non_generation_message_is_unchanged() -> None:
    text = "Обычное сообщение"
    assert sanitize_generation_started_text(text, reference_count=4) == text


@pytest.mark.asyncio
async def test_message_proxy_preserves_trace_ids_and_adds_task_label() -> None:
    message = _FakeMessage()
    proxy = _FriendlyMessageProxy(message, reference_count=3)

    await proxy.answer(
        "🚀 <b>Генерация запущена</b>\n"
        "• Модель: <code>Nano Banana Pro</code>\n"
        "• Формат: <code>9:16</code>\n"
        "• Запущено задач: <code>1</code>\n\n"
        "• <code>img_internal</code>\n"
        "• ID провайдера: <code>provider_internal</code>"
    )

    assert len(message.calls) == 1
    sent_text = message.calls[0][0]
    assert "Референсов: <code>3</code>" in sent_text
    assert "ID задачи: <code>img_internal</code>" in sent_text
    assert "ID провайдера: <code>provider_internal</code>" in sent_text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "done"])
async def test_miniapp_and_pinterest_success_always_send_started_confirmation(status: str) -> None:
    bot = _FakeBot()

    await miniapp_module._notify_miniapp_image_task_queued(
        {"bot": bot},
        123,
        {
            "status": status,
            "task_id": "provider-trace-id",
            "local_task_id": "img-trace-id",
        },
        img_service="banana_pro",
        img_ratio="9:16",
        unit_cost=2.5,
    )

    assert len(bot.messages) == 1
    sent = bot.messages[0]
    assert sent["chat_id"] == 123
    assert sent["parse_mode"] == "HTML"
    assert "🚀 <b>Генерация запущена</b>" in sent["text"]
    assert "Nano Banana Pro" in sent["text"]
    assert "ID задачи: <code>img-trace-id</code>" in sent["text"]
    assert "ID провайдера: <code>provider-trace-id</code>" in sent["text"]
    assert "Я пришлю его сюда сразу после готовности." in sent["text"]


@pytest.mark.asyncio
async def test_failed_miniapp_launch_does_not_claim_generation_started() -> None:
    bot = _FakeBot()

    await miniapp_module._notify_miniapp_image_task_queued(
        {"bot": bot},
        123,
        {"status": "failed", "task_id": "failed-task"},
        img_service="banana_pro",
        img_ratio="9:16",
        unit_cost=2.5,
    )

    assert bot.messages == []
