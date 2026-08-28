"""Keep Telegram image creation responsive while providers run in the background.

The legacy image prompt handler owns the FSM until ``_start_image_generation_task``
returns. That is harmless for queued providers, but a synchronous adapter (currently
RenderGrid) may wait for the final image for minutes. During that wait the user's FSM
remains ``waiting_for_input``: commands can be consumed as prompts, a second photo is
not routed to the reference uploader, and the handler's final ``state.clear()`` can
wipe a newer flow started while the old provider call is still running.

This compatibility layer deliberately does not change provider, billing or persistence
contracts. It releases the *real* FSM only after the local ``img_*`` task has been
persisted and ``on_task_created`` fires, then makes the old handler's final clear a
no-op. Provider work can finish normally while the user starts another independent
flow immediately.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import wraps
from typing import Any

from aiogram.dispatcher.event.bases import SkipHandler

from bot.states import GenerationStates

logger = logging.getLogger(__name__)

_ACTIVE_IMAGE_PROMPT_STATE: ContextVar[_ImagePromptStateProxy | None] = ContextVar(
    "active_image_prompt_state",
    default=None,
)


class _ImagePromptStateProxy:
    """Delegate to FSMContext, but never clear a newer session after release."""

    def __init__(self, state: Any) -> None:
        self._state = state
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    async def release(self) -> None:
        if self._released:
            return
        await self._state.clear()
        self._released = True
        logger.info("Released image generation FSM after local task creation")

    async def clear(self) -> None:
        # The legacy handler calls clear() after all provider work. Once release()
        # happened, that clear belongs to the old request and must not erase a new
        # flow that the user may already have started.
        if self._released:
            return
        await self._state.clear()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._state, name)


def _wrap_image_prompt_handler(original_handler):
    """Make slash commands navigational and bind a release-aware FSM proxy."""

    @wraps(original_handler)
    async def wrapped(message: Any, state: Any):
        text = str(getattr(message, "text", "") or "")
        if text.lstrip().startswith("/"):
            # generation_router is registered before admin/common routers. Clearing
            # the stale image state and raising SkipHandler lets /admin, /help, etc.
            # continue to their real command handler instead of becoming a prompt.
            await state.clear()
            raise SkipHandler

        data = await state.get_data()
        if data.get("generation_type") != "image":
            return await original_handler(message, state)

        proxy = _ImagePromptStateProxy(state)
        token = _ACTIVE_IMAGE_PROMPT_STATE.set(proxy)
        try:
            return await original_handler(message, proxy)
        finally:
            _ACTIVE_IMAGE_PROMPT_STATE.reset(token)

    return wrapped


def _wrap_start_image_generation_task(original_start):
    """Release the active prompt FSM at the persisted-local-task boundary."""

    @wraps(original_start)
    async def wrapped_start(*args: Any, **kwargs: Any):
        proxy = _ACTIVE_IMAGE_PROMPT_STATE.get()
        if proxy is None:
            return await original_start(*args, **kwargs)

        original_notify = kwargs.get("on_task_created")

        async def notify_and_release(local_task_id: str) -> None:
            try:
                if original_notify is not None:
                    await original_notify(local_task_id)
            finally:
                # In generation.py this callback runs only after add_generation_task
                # succeeds and immediately before the provider service is awaited.
                await proxy.release()

        kwargs["on_task_created"] = notify_and_release
        return await original_start(*args, **kwargs)

    return wrapped_start


def _replace_registered_image_prompt_handler(generation_module: Any) -> None:
    original = generation_module.handle_image_prompt_text
    wrapped = _wrap_image_prompt_handler(original)

    replaced = False
    for handler_object in generation_module.router.message.handlers:
        if handler_object.callback is original:
            handler_object.callback = wrapped
            replaced = True

    if not replaced:
        raise RuntimeError("handle_image_prompt_text is not registered on generation router")

    generation_module.handle_image_prompt_text = wrapped


def install_image_generation_fsm_compat(generation_module: Any, priority_router: Any) -> None:
    """Install command, multi-reference and provider-wait FSM compatibility once."""

    if getattr(generation_module, "_image_generation_fsm_compat_installed", False):
        return

    _replace_registered_image_prompt_handler(generation_module)
    generation_module._start_image_generation_task = _wrap_start_image_generation_task(
        generation_module._start_image_generation_task
    )

    @priority_router.message(
        GenerationStates.waiting_for_input,
        generation_module.F.photo
        | (
            generation_module.F.document
            & generation_module.F.document.mime_type.in_(
                generation_module.IMAGE_REFERENCE_DOCUMENT_MIME_TYPES
            )
        ),
    )
    async def add_reference_while_waiting_for_prompt(message: Any, state: Any) -> None:
        data = await state.get_data()
        if data.get("generation_type") != "image":
            raise SkipHandler

        # Call the established idle-reference function directly. Its internal logic
        # already knows how to append a reference when state=waiting_for_input, but
        # its legacy decorator accidentally excluded that state.
        await generation_module.start_image_creation_from_idle_reference(message, state)

    generation_module._image_generation_fsm_compat_installed = True
