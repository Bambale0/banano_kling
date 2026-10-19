"""Legacy result callbacks share the native image repeat entry point."""
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot.handlers import generation

router = Router()


@router.callback_query(F.data.startswith("repeat_result_"))
async def repeat_result_compat(callback: types.CallbackQuery, state: FSMContext) -> None:
    await generation.quick_repeat_image_result(callback, state)
