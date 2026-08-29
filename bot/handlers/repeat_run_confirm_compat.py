"""Priority router for repeat confirmation callbacks.

The legacy safe-repeat router has a broad ``repeat_run_`` handler. It also
matches ``repeat_run_confirm_`` / ``repeat_run_cancel_`` callback data if it is
registered before the exact quick-repeat handlers. This module installs exact
handlers on a router that is included before ``generation_module.router``.
"""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from .generation_started_ux_compat import install_generation_started_ux
from .image_generation_fsm_compat import install_image_generation_fsm_compat
from .pinterest_prompt_softening_compat import install_pinterest_prompt_softening

router = Router()
_INSTALLED = False


def install_repeat_run_confirm_compat(generation_module) -> None:
    """Forward exact repeat confirmation callbacks before the broad handler."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # The repeat compatibility hook is initialized for every production bot
    # process before generation routing is exposed. Reuse it to install the
    # provider-agnostic public "generation started" UX without editing the
    # legacy generation monolith or the top-level handlers package contract.
    install_generation_started_ux(generation_module)

    # The same priority router can accept another reference while the image flow
    # is waiting for a prompt. The runtime patch also releases the real FSM as
    # soon as the local img_* task exists, before a synchronous provider wait.
    install_image_generation_fsm_compat(generation_module, router)

    # Pinterest still keeps its scene/identity reference roles, but the model
    # receives them as concise secondary guidance instead of a long pseudo-system
    # contract that can overpower the actual creative request.
    install_pinterest_prompt_softening()

    @router.callback_query(F.data.startswith("repeat_run_confirm_"))
    async def repeat_run_confirm_compat(
        callback: types.CallbackQuery,
        state: FSMContext,
    ) -> None:
        await generation_module.quick_repeat_image_confirm(callback, state)

    @router.callback_query(F.data.startswith("repeat_run_cancel_"))
    async def repeat_run_cancel_compat(
        callback: types.CallbackQuery,
        state: FSMContext,
    ) -> None:
        await generation_module.quick_repeat_image_cancel(callback, state)
