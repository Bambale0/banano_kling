from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.services.prompt_fragment_coalescer import PromptFragmentCoalescingMiddleware
from bot.states import GenerationStates


class FakeState:
    def __init__(self, state_name: str):
        self.state_name = state_name
        self.data: dict[str, object] = {}

    async def get_state(self) -> str:
        return self.state_name

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, data: dict[str, object]) -> dict[str, object]:
        self.data.update(data)
        return dict(self.data)


class FakeMessage:
    def __init__(self, text: str, *, user_id: int = 101, chat_id: int = 202):
        self.text = text
        self.entities = []
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=chat_id)
        self.answers: list[str] = []

    def model_copy(self, *, update: dict):
        cloned = FakeMessage(
            update.get("text", self.text),
            user_id=self.from_user.id,
            chat_id=self.chat.id,
        )
        cloned.answers = self.answers
        return cloned

    async def answer(self, text: str, **_kwargs):
        self.answers.append(text)


@pytest.mark.asyncio
async def test_two_prompt_messages_are_submitted_once_as_combined_text():
    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.02,
        long_quiet_seconds=0.03,
    )
    state = FakeState(GenerationStates.waiting_for_video_prompt.state)
    calls: list[str] = []

    async def handler(event, _data):
        calls.append(event.text)

    await middleware(handler, FakeMessage("начало промпта"), {"state": state})
    await asyncio.sleep(0.005)
    await middleware(handler, FakeMessage("конец промпта"), {"state": state})
    await asyncio.sleep(0.06)

    assert calls == ["начало промпта\nконец промпта"]


@pytest.mark.asyncio
async def test_telegram_sized_first_fragment_waits_for_continuation():
    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.01,
        long_quiet_seconds=0.04,
    )
    state = FakeState(GenerationStates.waiting_for_input.state)
    calls: list[str] = []

    async def handler(event, _data):
        calls.append(event.text)

    first = "A" * 4096
    second = "B" * 500
    await middleware(handler, FakeMessage(first), {"state": state})
    await asyncio.sleep(0.015)
    assert calls == []

    await middleware(handler, FakeMessage(second), {"state": state})
    await asyncio.sleep(0.07)

    assert len(calls) == 1
    assert calls[0] == first + "\n" + second


@pytest.mark.asyncio
async def test_pending_prompt_is_not_launched_after_fsm_state_changes():
    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.02,
        long_quiet_seconds=0.02,
    )
    state = FakeState(GenerationStates.waiting_for_input.state)
    calls: list[str] = []

    async def handler(event, _data):
        calls.append(event.text)

    await middleware(handler, FakeMessage("длинный запрос"), {"state": state})
    state.state_name = GenerationStates.confirming_generation.state
    await asyncio.sleep(0.05)

    assert calls == []


@pytest.mark.asyncio
async def test_command_is_never_joined_to_pending_prompt():
    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.04,
        long_quiet_seconds=0.04,
    )
    state = FakeState(GenerationStates.waiting_for_input.state)
    calls: list[str] = []

    async def handler(event, _data):
        calls.append(event.text)

    await middleware(handler, FakeMessage("первая часть"), {"state": state})
    await middleware(handler, FakeMessage("/cancel"), {"state": state})
    await asyncio.sleep(0.07)

    assert calls == ["/cancel"]
