from pathlib import Path

path = Path('/root/banano_kling/bot/handlers/admin.py')
text = path.read_text(encoding='utf-8')

start = text.index('@router.message(AdminStates.waiting_broadcast_text)')
end = text.index('@router.callback_query(F.data == "admin_broadcast_confirm")')
replacement = r'''@router.message(AdminStates.waiting_broadcast_text)
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
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding='utf-8')
print('fixed broadcast strings raw')
