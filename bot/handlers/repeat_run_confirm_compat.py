"""Priority router for repeat confirmation callbacks.

The legacy safe-repeat router has a broad ``repeat_run_`` handler. It also
matches ``repeat_run_confirm_`` / ``repeat_run_cancel_`` callback data if it is
registered before the exact quick-repeat handlers. This module installs exact
handlers on a router that is included before ``generation_module.router``.
"""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

router = Router()
_INSTALLED = False


def install_repeat_run_confirm_compat(generation_module) -> None:
    """Forward exact repeat confirmation callbacks before the broad handler."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

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
