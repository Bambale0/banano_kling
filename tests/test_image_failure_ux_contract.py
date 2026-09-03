from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers.image_failure_ux_compat import install_image_failure_ux


class _FakeMessage:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def answer(self, text, **kwargs):
        call = {"text": text, **kwargs}
        self.sent.append(call)
        return call


class _FakeGenerationModule:
    def __init__(self) -> None:
        async def start_image_generation_task(**kwargs):
            provider_result = kwargs["provider_result"]
            status, _error = self._classify_image_generation_result(provider_result)
            assert status == "failed"
            return {
                "status": "failed",
                "task_id": "img_local_123",
                "runtime_img_service": kwargs["img_service"],
            }

        def classify_image_generation_result(result):
            return "failed", result.get("error")

        async def handle_image_prompt_text(message, state):
            launch_result = await self._start_image_generation_task(
                img_service="banana_pro",
                provider_result={
                    "error": "Provider rejected the image because moderation blocked it",
                    "provider": "rendergrid",
                    "provider_model": "nano-banana-pro",
                    "creation_id": "rg-creation-failed-123",
                    "provider_task_id": "rg-creation-failed-123",
                },
            )
            assert launch_result["status"] == "failed"
            assert launch_result["provider_task_id"] == "rg-creation-failed-123"
            await message.answer(
                "Часть вариантов не удалось запустить.\nВозвращено: <code>1.5</code>🍌",
                parse_mode="HTML",
            )
            await message.answer(
                "Не получилось запустить генерацию.\n"
                "Бананы за эту попытку уже вернулись на баланс."
            )

        self._classify_image_generation_result = classify_image_generation_result
        self._start_image_generation_task = start_image_generation_task
        self.handle_image_prompt_text = handle_image_prompt_text
        handler = SimpleNamespace(callback=self.handle_image_prompt_text)
        self.router = SimpleNamespace(message=SimpleNamespace(handlers=[handler]))


@pytest.mark.asyncio
async def test_sync_image_failure_shows_reason_ids_and_retry_once() -> None:
    generation_module = _FakeGenerationModule()
    install_image_failure_ux(generation_module)
    message = _FakeMessage()

    registered_handler = generation_module.router.message.handlers[0].callback
    await registered_handler(message, state=None)

    assert len(message.sent) == 1
    sent = message.sent[0]
    text = sent["text"]
    assert "Не удалось сгенерировать изображение" in text
    assert "Nano Banana Pro" in text
    assert "img_local_123" in text
    assert "rg-creation-failed-123" in text
    assert "moderation blocked it" in text
    assert "Бананы за эту попытку уже возвращены" in text

    buttons = [
        button
        for row in sent["reply_markup"].inline_keyboard
        for button in row
    ]
    repeat = next(button for button in buttons if button.text == "🔁 Повторить")
    assert repeat.callback_data == "repeat_result_img_local_123"
