from pathlib import Path

path = Path('/root/banano_kling/bot/handlers/admin.py')
text = path.read_text(encoding='utf-8')

text = text.replace(
    '        "Отправьте текст сообщения или фото с подписью.\n"\n        "Можно отправить фото без подписи — пользователи получат только изображение.\n\n"\n        "<i>В тексте и подписи поддерживается HTML-форматирование</i>",',
    '        "Отправьте текст сообщения, фото или видео с подписью.\n"\n        "Можно отправить фото/видео без подписи — пользователи получат только медиа.\n\n"\n        "<i>В тексте и подписи поддерживается HTML-форматирование</i>",'
)

start = text.index('@router.message(AdminStates.waiting_broadcast_text)')
end = text.index('@router.callback_query(F.data == "admin_broadcast_confirm")')
new_mid = '''@router.message(AdminStates.waiting_broadcast_text)
async def admin_process_broadcast_text(message: types.Message, state: FSMContext):
    """Показывает превью рассылки"""
    broadcast_media_type = None
    broadcast_media_file_id = None

    if message.photo:
        broadcast_media_type = "photo"
        broadcast_media_file_id = message.photo[-1].file_id
        broadcast_text = (message.caption or "").strip()

        if len(broadcast_text) > BROADCAST_PHOTO_CAPTION_LIMIT:
            await message.answer(
                "❌ Подпись к фото слишком длинная.\n"
                f"Максимум: <code>{BROADCAST_PHOTO_CAPTION_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    elif message.video:
        broadcast_media_type = "video"
        broadcast_media_file_id = message.video.file_id
        broadcast_text = (message.caption or "").strip()

        if len(broadcast_text) > BROADCAST_PHOTO_CAPTION_LIMIT:
            await message.answer(
                "❌ Подпись к видео слишком длинная.\n"
                f"Максимум: <code>{BROADCAST_PHOTO_CAPTION_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    elif message.text:
        broadcast_text = message.text.strip()

        if not broadcast_text:
            await message.answer(
                "❌ Текст рассылки пустой. Отправьте текст, фото или видео.",
                reply_markup=get_back_keyboard("admin_back"),
            )
            return

        if len(broadcast_text) > BROADCAST_MESSAGE_LIMIT:
            await message.answer(
                "❌ Текст рассылки слишком длинный.\n"
                f"Максимум: <code>{BROADCAST_MESSAGE_LIMIT}</code> символов.",
                reply_markup=get_back_keyboard("admin_back"),
                parse_mode="HTML",
            )
            return
    else:
        await message.answer(
            "❌ Для рассылки отправьте текст, фото или видео с необязательной подписью.",
            reply_markup=get_back_keyboard("admin_back"),
        )
        return

    await state.update_data(
        broadcast_text=broadcast_text,
        broadcast_media_type=broadcast_media_type,
        broadcast_media_file_id=broadcast_media_file_id,
    )

    if broadcast_media_type == "photo":
        await message.answer_photo(
            photo=broadcast_media_file_id,
            caption=broadcast_text or None,
            parse_mode="HTML" if broadcast_text else None,
        )
        await message.answer(
            "📢 <b>Превью рассылки с фото выше.</b>\n\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )
    elif broadcast_media_type == "video":
        await message.answer_video(
            video=broadcast_media_file_id,
            caption=broadcast_text or None,
            parse_mode="HTML" if broadcast_text else None,
        )
        await message.answer(
            "📢 <b>Превью рассылки с видео выше.</b>\n\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "📢 <b>Превью рассылки:</b>\n"
            "───────────────\n"
            f"{broadcast_text}\n"
            "───────────────\n"
            "Подтверждаете отправку?",
            reply_markup=_broadcast_confirm_keyboard(),
            parse_mode="HTML",
        )

    await state.set_state(AdminStates.confirming_broadcast)


'''
text = text[:start] + new_mid + text[end:]

start = text.index('@router.callback_query(F.data == "admin_broadcast_confirm")')
end = text.index('    await state.clear()', start)
end = text.index('\n', end + 1) + 1
new_confirm = '''@router.callback_query(F.data == "admin_broadcast_confirm")
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
text = text[:start] + new_confirm + text[end:]

path.write_text(text, encoding='utf-8')
print('patched broadcast media precise')
