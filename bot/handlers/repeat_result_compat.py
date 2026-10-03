from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.database import get_or_create_user, get_task_by_id
from bot.handlers.generation import (
    _can_inherit_repeat_source_references,
    _repeat_source_prompt_hidden,
    _restore_image_task_to_state,
    _show_repeat_image_screen,
)

router = Router()


@router.callback_query(F.data.startswith("repeat_result_"))
async def repeat_result_compat(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Keep completed-image keyboards created with the old callback working.

    The safe repeat flow now listens on ``repeat_image_*``. Some completed
    result messages were still created with ``repeat_result_*`` and therefore
    appeared to have a dead/missing repeat action. Route both callback versions
    through the same state restoration and confirmation screen.
    """

    task_id = (callback.data or "").replace("repeat_result_", "", 1)
    task = await get_task_by_id(task_id)
    user = await get_or_create_user(callback.from_user.id)

    hide_prompt = _repeat_source_prompt_hidden(task, user.id)
    restored, error_message = await _restore_image_task_to_state(
        task,
        state,
        include_references=_can_inherit_repeat_source_references(task, user.id),
        repeat_source_task_id=task_id,
        hide_prompt=hide_prompt,
    )
    if not restored:
        await callback.answer(
            error_message or "Не удалось открыть повтор.",
            show_alert=True,
        )
        return

    await _show_repeat_image_screen(callback, state)
    await callback.answer("Сначала можно добавить своё фото")
