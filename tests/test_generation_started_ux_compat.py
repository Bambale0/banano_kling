from __future__ import annotations

import pytest

from bot import miniapp as miniapp_module
from bot.handlers.generation_started_ux_compat import (
    _FriendlyMessageProxy,
    build_generation_started_text,
    sanitize_generation_started_text,
)


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


def test_public_generation_started_text_has_no_technical_ids() -> None:
    text = build_generation_started_text(
        model_label="Nano Banana Pro",
        aspect_ratio="9:16",
        launched_count=1,
        unit_cost=2.5,
        reference_count=2,
    )

    assert "🚀 <b>Генерация запущена</b>" in text
    assert "Nano Banana Pro" in text
    assert "9:16" in text
    assert "Референсов: <code>2</code>" in text
    assert "Запущено задач: <code>1</code>" in text
    assert "Списано: <code>2.5</code>🍌" in text
    assert "Я пришлю его сюда сразу после готовности." in text
    assert "ID провайдера" not in text
    assert "task_id" not in text


def test_legacy_telegram_summary_is_sanitized_without_losing_useful_fields() -> None:
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
    assert "img_a642ba273747" not in text
    assert "b73caaef54145e94e221414a09d76b04" not in text
    assert "ID провайдера" not in text
    assert "1–3 минут" in text
    assert text.endswith("Я пришлю его сюда сразу после готовности.")


def test_non_generation_message_is_unchanged() -> None:
    text = "Обычное сообщение"
    assert sanitize_generation_started_text(text, reference_count=4) == text


@pytest.mark.asyncio
async def test_message_proxy_sanitizes_real_handler_answer() -> None:
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
    assert "img_internal" not in sent_text
    assert "provider_internal" not in sent_text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "done"])
async def test_miniapp_and_pinterest_success_always_send_started_confirmation(status: str) -> None:
    bot = _FakeBot()

    await miniapp_module._notify_miniapp_image_task_queued(
        {"bot": bot},
        123,
        {
            "status": status,
            "task_id": "provider-secret-id",
            "local_task_id": "img-secret-id",
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
    assert "provider-secret-id" not in sent["text"]
    assert "img-secret-id" not in sent["text"]
    assert "ID провайдера" not in sent["text"]
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
