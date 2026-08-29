from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from bot.services.prompt_fragment_coalescer import PromptFragmentCoalescingMiddleware
from bot.states import GenerationStates


@dataclass
class _FakeMessage:
    text: str
    user_id: int = 101
    chat_id: int = 202
    answers: list[str] = field(default_factory=list)

    @property
    def from_user(self) -> Any:
        return SimpleNamespace(id=self.user_id)

    @property
    def chat(self) -> Any:
        return SimpleNamespace(id=self.chat_id)

    def model_copy(self, *, update: dict[str, Any]) -> "_FakeMessage":
        return _FakeMessage(
            text=str(update.get("text", self.text)),
            user_id=self.user_id,
            chat_id=self.chat_id,
            answers=self.answers,
        )

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class _FakeFSM:
    def __init__(self) -> None:
        self.state = GenerationStates.waiting_for_input.state
        self.data: dict[str, Any] = {"generation_type": "image"}

    async def get_state(self) -> str | None:
        return self.state

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def update_data(self, data: dict[str, Any]) -> dict[str, Any]:
        self.data.update(data)
        return dict(self.data)

    async def clear(self) -> None:
        self.state = None
        self.data.clear()

    async def set_state(self, state: str | None) -> None:
        self.state = state

    async def start_new_image_generation(self) -> None:
        self.state = GenerationStates.waiting_for_input.state
        self.data = {"generation_type": "image"}


@pytest.mark.asyncio
async def test_new_prompt_is_accepted_after_fsm_release_while_old_provider_waits() -> None:
    """A completed submit boundary must not lock prompts until provider completion."""

    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.01,
        long_quiet_seconds=0.01,
    )
    fsm = _FakeFSM()
    first_provider_release = asyncio.Event()
    first_started = asyncio.Event()
    first_finished = asyncio.Event()
    second_started = asyncio.Event()
    calls: list[str] = []

    async def generation_handler(event: _FakeMessage, data: dict[str, Any]) -> None:
        calls.append(event.text)
        if event.text == "first prompt":
            # PR #128 releases the real FSM after the local img_* task is persisted,
            # while RenderGrid may still be waiting for the final image.
            await fsm.clear()
            first_started.set()
            try:
                await first_provider_release.wait()
            finally:
                first_finished.set()
        elif event.text == "second prompt":
            second_started.set()

    data = {"state": fsm}
    await middleware(generation_handler, _FakeMessage("first prompt"), data)
    await asyncio.wait_for(first_started.wait(), timeout=1.0)

    # The user immediately starts another image flow before the first provider
    # request finishes. It enters the same FSM state/key but is a new session.
    await fsm.start_new_image_generation()
    await middleware(generation_handler, _FakeMessage("second prompt"), data)

    # Finish the old provider before the second quiet window expires. This also
    # proves the old flush cannot delete the newer pending prompt by accident.
    first_provider_release.set()
    await asyncio.wait_for(first_finished.wait(), timeout=1.0)
    await asyncio.wait_for(second_started.wait(), timeout=1.0)

    assert calls == ["first prompt", "second prompt"]


@pytest.mark.asyncio
async def test_same_submit_duplicate_stays_blocked_until_submit_boundary() -> None:
    """Keep the original protection against duplicate prompt submits."""

    middleware = PromptFragmentCoalescingMiddleware(
        quiet_seconds=0.01,
        long_quiet_seconds=0.01,
    )
    fsm = _FakeFSM()
    provider_release = asyncio.Event()
    first_started = asyncio.Event()
    first_finished = asyncio.Event()
    calls: list[str] = []

    async def generation_handler(event: _FakeMessage, data: dict[str, Any]) -> None:
        calls.append(event.text)
        first_started.set()
        try:
            await provider_release.wait()
        finally:
            first_finished.set()

    data = {"state": fsm}
    await middleware(generation_handler, _FakeMessage("first prompt"), data)
    await asyncio.wait_for(first_started.wait(), timeout=1.0)

    # No FSM release happened, so this is still the same submit session and must
    # retain the existing duplicate-protection behavior.
    await middleware(generation_handler, _FakeMessage("duplicate prompt"), data)
    await asyncio.sleep(0.05)
    assert calls == ["first prompt"]

    provider_release.set()
    await asyncio.wait_for(first_finished.wait(), timeout=1.0)
