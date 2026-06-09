from pathlib import Path

path = Path('/root/banano_kling/bot/handlers/admin.py')
text = path.read_text(encoding='utf-8')
start = text.index('@router.callback_query(F.data == "admin_broadcast_confirm")')
end = text.index('@router.callback_query(F.data == "admin_back")')
replacement = r'''@router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_execute_broadcast(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    """Выполняет рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")
    broadcast_media_type = data.get("broadcast_media_type")
    broadcast_media_file_id = data.get("broadcast_media_file_id")

    if not broadcast_text and not broadcast_media_file_id:
        await callback.message.edit_text(
            "❌ Не найден текст, фото или видео для рассылки.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

    await callback.message.edit_text(
        "📢 <b>Рассылка запущена...</b>", parse_mode="HTML"
    )

    import aiosqlite
    from bot.database import DATABASE_PATH

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT telegram_id FROM users")
        users = await cursor.fetchall()

    success_count = 0
    error_count = 0

    for user in users:
        try:
            if broadcast_media_type == "photo":
                await bot.send_photo(
                    user["telegram_id"],
                    photo=broadcast_media_file_id,
                    caption=broadcast_text or None,
                    parse_mode="HTML" if broadcast_text else None,
                )
            elif broadcast_media_type == "video":
                await bot.send_video(
                    user["telegram_id"],
                    video=broadcast_media_file_id,
                    caption=broadcast_text or None,
                    parse_mode="HTML" if broadcast_text else None,
                )
            else:
                await bot.send_message(
                    user["telegram_id"], broadcast_text, parse_mode="HTML"
                )
            success_count += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['telegram_id']}: {e}")
            error_count += 1

    await callback.message.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )

    await state.clear()


'''
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding='utf-8')
print('replaced broadcast confirm function')
