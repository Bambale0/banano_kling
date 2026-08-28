from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.dispatcher.event.bases import SkipHandler

from bot.handlers.image_generation_fsm_compat import (
    _ACTIVE_IMAGE_PROMPT_STATE,
    _ImagePromptStateProxy,
    _wrap_image_prompt_handler,
    _wrap_start_image_generation_task,
)
from bot.states import GenerationStates


class _FakeState:
    def __init__(self) -> None:
        self.state = GenerationStates.waiting_for_input.state
        self.data = {"generation_type": "image", "reference_images": []}
        self.clear_count = 0

    async def clear(self) -> None:
        self.clear_count += 1
        self.state = None
        self.data = {}

    async def get_state(self):
        return self.state

    async def set_state(self, value) -> None:
        self.state = value.state if hasattr(value, "state") else value

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)


@pytest.mark.asyncio
async def test_slash_command_is_not_consumed_as_image_prompt() -> None:
    state = _FakeState()
    called = False

    async def original_handler(message, handler_state):
        nonlocal called
        called = True

    wrapped = _wrap_image_prompt_handler(original_handler)

    with pytest.raises(SkipHandler):
        await wrapped(SimpleNamespace(text="/admin"), state)

    assert called is False
    assert state.clear_count == 1
    assert state.state is None


@pytest.mark.asyncio
async def test_fsm_is_released_at_local_task_creation_and_old_clear_cannot_wipe_new_flow() -> None:
    real_state = _FakeState()
    proxy = _ImagePromptStateProxy(real_state)
    events: list[str] = []

    async def original_notify(local_task_id: str) -> None:
        events.append(f"notified:{local_task_id}")

    async def original_start(*, on_task_created=None):
        events.append("task-persisted")
        await on_task_created("img_123")
        assert real_state.state is None

        # Simulate the user starting a new independent flow while the old
        # synchronous provider call is still waiting for its result.
        real_state.state = GenerationStates.uploading_reference_images.state
        real_state.data = {"generation_type": "image", "reference_images": ["new-ref"]}
        events.append("new-flow-started")
        return {"status": "done", "task_id": "img_123"}

    wrapped_start = _wrap_start_image_generation_task(original_start)
    token = _ACTIVE_IMAGE_PROMPT_STATE.set(proxy)
    try:
        result = await wrapped_start(on_task_created=original_notify)
    finally:
        _ACTIVE_IMAGE_PROMPT_STATE.reset(token)

    # This mirrors generation.py's final `await state.clear()` on the old
    # request. It must be a no-op after release().
    await proxy.clear()

    assert result["status"] == "done"
    assert events == ["task-persisted", "notified:img_123", "new-flow-started"]
    assert real_state.clear_count == 1
    assert real_state.state == GenerationStates.uploading_reference_images.state
    assert real_state.data["reference_images"] == ["new-ref"]


@pytest.mark.asyncio
async def test_provider_validation_before_task_creation_does_not_release_fsm() -> None:
    real_state = _FakeState()
    proxy = _ImagePromptStateProxy(real_state)

    async def original_start(*, on_task_created=None):
        # Simulate policy/reference validation returning before local task
        # creation. The callback is intentionally never called.
        return {"status": "failed", "task_id": None}

    wrapped_start = _wrap_start_image_generation_task(original_start)
    token = _ACTIVE_IMAGE_PROMPT_STATE.set(proxy)
    try:
        result = await wrapped_start()
    finally:
        _ACTIVE_IMAGE_PROMPT_STATE.reset(token)

    assert result["status"] == "failed"
    assert proxy.released is False
    assert real_state.clear_count == 0
    assert real_state.state == GenerationStates.waiting_for_input.state


def test_priority_router_accepts_second_reference_while_waiting_for_prompt() -> None:
    source = Path("bot/handlers/image_generation_fsm_compat.py").read_text(encoding="utf-8")

    assert "GenerationStates.waiting_for_input" in source
    assert "add_reference_while_waiting_for_prompt" in source
    assert "start_image_creation_from_idle_reference" in source
    assert 'data.get("generation_type") != "image"' in source


def test_prompt_fragment_coalescer_keeps_commands_out_of_prompts() -> None:
    source = Path("bot/services/prompt_fragment_coalescer.py").read_text(encoding="utf-8")

    assert 'text.lstrip().startswith("/")' in source
    assert "return await handler(event, data)" in source
