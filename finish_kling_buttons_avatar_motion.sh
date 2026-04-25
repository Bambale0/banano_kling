#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# -----------------------------------------------------------------------------
# 1) Keyboards: main menu Motion Control + avatar upload buttons + motion models
# -----------------------------------------------------------------------------
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")

# Main menu: add standalone Motion Control button after video.
if 'callback_data="motion_control"' not in s.split('def get_main_menu_keyboard', 1)[1].split('def get_create_hub_keyboard', 1)[0]:
    s = s.replace(
        '    builder.button(text="🎬 Создать видео", callback_data="create_video_new")\n',
        '    builder.button(text="🎬 Создать видео", callback_data="create_video_new")\n    builder.button(text="🎯 Motion Control", callback_data="motion_control")\n',
        1,
    )
    s = s.replace('builder.adjust(1, 2, 2, 2, 2, 1)', 'builder.adjust(1, 2, 2, 2, 2, 1, 1)', 1)
    s = s.replace('builder.adjust(2, 2, 2, 2, 1)', 'builder.adjust(2, 2, 2, 2, 1, 1)', 1)

# Video labels / type labels / supported ratios.
if '"motion_control_v26": "Kling 2.6 Motion Control"' not in s:
    s = s.replace(
        '    "avatar_pro": "Kling AI Avatar Pro",\n',
        '    "avatar_pro": "Kling AI Avatar Pro",\n    "motion_control_v26": "Kling 2.6 Motion Control",\n    "motion_control_v30": "Kling 3.0 Motion Control",\n',
        1,
    )
if '"motion": "Motion Control"' not in s:
    s = s.replace(
        '        "avatar": "Аватар + Аудио -> Видео",\n',
        '        "avatar": "Аватар + Аудио -> Видео",\n        "motion": "Motion Control",\n',
        1,
    )
if '"motion_control_v26": ["motion"]' not in s:
    s = s.replace(
        '    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],\n',
        '    "grok_imagine": ["16:9", "9:16", "1:1", "3:2", "2:3"],\n    "motion_control_v26": ["motion"],\n    "motion_control_v30": ["motion"],\n',
        1,
    )

# Video model selection: show Motion Control entries.
if '"motion_control_v26",' not in s:
    marker = '        ("glow", "✨ Kling Glow", preset_manager.get_video_cost("glow", 5)),\n'
    add = marker + '        ("motion_control_v26", "🎯 Kling 2.6 Motion", preset_manager.get_video_cost("motion_control_v26", 5)),\n        ("motion_control_v30", "🚀 Kling 3.0 Motion", preset_manager.get_video_cost("motion_control_v30", 5)),\n'
    s = s.replace(marker, add, 1)

# Avatar media buttons must not be ignore; they must set upload mode.
s = s.replace('builder.button(text=f"🖼 Аватар: {image_status}", callback_data="ignore")', 'builder.button(text=f"🖼 Аватар: {image_status}", callback_data="avatar_upload_image")')
s = s.replace('builder.button(text=f"🎵 Аудио: {audio_status}", callback_data="ignore")', 'builder.button(text=f"🎵 Аудио: {audio_status}", callback_data="avatar_upload_audio")')

# Motion media step if v_type motion.
if 'current_v_type == "motion"' not in s:
    anchor = '    if current_v_type == "avatar":\n'
    block = '''    if current_v_type == "motion":
        image_status = "загружено" if has_start_image else "не загружено"
        video_status = "загружено" if reference_video_count else "не загружено"
        builder.button(text=f"🖼 Фото персонажа: {image_status}", callback_data="motion_upload_image")
        builder.button(text=f"🎬 Видео движения: {video_status}", callback_data="motion_upload_video")
        builder.button(text="▶️ К промпту", callback_data="video_media_continue")
        builder.button(text="🤖 Сменить модель", callback_data="video_change_model")
        builder.button(text="🏠 Главное меню", callback_data="back_main")
        builder.adjust(2, 1, 2)
        return builder.as_markup()

'''
    s = s.replace(anchor, block + anchor, 1)

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) Preset manager fallback costs for motion/avatar if missing
# -----------------------------------------------------------------------------
p = Path("bot/services/preset_manager.py")
s = p.read_text(encoding="utf-8")
if '"motion_control_v26"' not in s:
    s = s.replace('"glow": "glow",', '"glow": "glow",\n    "motion_control_v26": "motion_control_v26",\n    "motion_control_v30": "motion_control_v30",')
# Do a conservative textual fallback cost injection only if fallback map has glow.
if '"motion_control_v26": 12' not in s:
    s = s.replace('"glow": 5,', '"glow": 5,\n    "motion_control_v26": 12,\n    "motion_control_v30": 18,')
p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) Generation handlers: callbacks + upload fallbacks for avatar and motion
# -----------------------------------------------------------------------------
p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

append = r'''

# =============================================================================
# FINAL KLING AVATAR / MOTION BUTTON FIXES
# =============================================================================

@router.callback_query(F.data == "motion_control")
async def open_motion_control_from_main(callback: types.CallbackQuery, state: FSMContext):
    """Standalone Motion Control entry from main menu."""
    await state.clear()
    await state.update_data(
        generation_type="video",
        v_model="motion_control_v26",
        v_type="motion",
        v_duration=5,
        v_ratio="motion",
        v_image_url=None,
        v_reference_videos=[],
        motion_mode="720p",
        motion_orientation="video",
    )
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    user_credits = await get_user_credits(callback.from_user.id)
    await callback.message.edit_text(
        "🎯 <b>Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Выберите версию Kling, затем загрузите фото персонажа и видео движения.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="motion",
            current_model="motion_control_v26",
            has_start_image=False,
            reference_video_count=0,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "v_model_motion_control_v26")
async def select_motion_v26(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(v_model="motion_control_v26", v_type="motion", v_ratio="motion", v_duration=5)
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    data = await state.get_data()
    await callback.message.edit_text(
        "🎯 <b>Kling 2.6 Motion Control</b>\n\n"
        "Загрузите фото персонажа и видео движения.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="motion",
            current_model="motion_control_v26",
            has_start_image=bool(data.get("v_image_url")),
            reference_video_count=len(data.get("v_reference_videos") or []),
        ),
        parse_mode="HTML",
    )
    await callback.answer("Kling 2.6 Motion Control")


@router.callback_query(F.data == "v_model_motion_control_v30")
async def select_motion_v30(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(v_model="motion_control_v30", v_type="motion", v_ratio="motion", v_duration=5)
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    data = await state.get_data()
    await callback.message.edit_text(
        "🎯 <b>Kling 3.0 Motion Control</b>\n\n"
        "Загрузите фото персонажа и видео движения.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="motion",
            current_model="motion_control_v30",
            has_start_image=bool(data.get("v_image_url")),
            reference_video_count=len(data.get("v_reference_videos") or []),
        ),
        parse_mode="HTML",
    )
    await callback.answer("Kling 3.0 Motion Control")


@router.callback_query(F.data == "avatar_upload_image")
async def avatar_upload_image(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    await callback.answer("Отправьте фото аватара")
    await callback.message.answer("🖼 Отправьте фото аватара одним сообщением.")


@router.callback_query(F.data == "avatar_upload_audio")
async def avatar_upload_audio(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GenerationStates.waiting_for_avatar_audio)
    await callback.answer("Отправьте аудио")
    await callback.message.answer("🎵 Отправьте аудиофайл, голосовое или документ с аудио.")


@router.callback_query(F.data == "motion_upload_image")
async def motion_upload_image(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    await callback.answer("Отправьте фото персонажа")
    await callback.message.answer("🖼 Отправьте фото персонажа для Motion Control.")


@router.callback_query(F.data == "motion_upload_video")
async def motion_upload_video(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GenerationStates.uploading_reference_videos)
    await callback.answer("Отправьте видео движения")
    await callback.message.answer("🎬 Отправьте видео движения для Motion Control.")


@router.message(GenerationStates.waiting_for_video_start_image, F.photo)
async def final_video_start_image_upload(message: types.Message, state: FSMContext):
    """Fallback upload for Avatar/Motion start image when old handlers do not catch it."""
    data = await state.get_data()
    v_type = data.get("v_type")
    if v_type not in {"avatar", "motion", "imgtxt"}:
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    image_url = save_uploaded_file(downloaded.read(), "jpg")
    await state.update_data(v_image_url=image_url)

    if v_type == "avatar":
        await message.answer(
            "✅ Фото аватара загружено. Теперь загрузите аудиофайл.",
            reply_markup=get_video_media_step_keyboard(
                current_v_type="avatar",
                current_model=data.get("v_model", "avatar_std"),
                has_start_image=True,
                has_avatar_audio=bool(data.get("avatar_audio_url")),
            ),
        )
        await state.set_state(GenerationStates.waiting_for_avatar_audio)
    elif v_type == "motion":
        await message.answer(
            "✅ Фото персонажа загружено. Теперь загрузите видео движения.",
            reply_markup=get_video_media_step_keyboard(
                current_v_type="motion",
                current_model=data.get("v_model", "motion_control_v26"),
                has_start_image=True,
                reference_video_count=len(data.get("v_reference_videos") or []),
            ),
        )
        await state.set_state(GenerationStates.uploading_reference_videos)
    else:
        await message.answer("✅ Стартовое фото загружено. Можно продолжать.")


@router.message(GenerationStates.uploading_reference_videos, F.video)
async def final_motion_video_upload(message: types.Message, state: FSMContext):
    """Fallback video upload for Motion Control."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        return

    video = message.video
    file = await message.bot.get_file(video.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    video_url = save_uploaded_file(downloaded.read(), "mp4")
    await state.update_data(v_reference_videos=[video_url])
    await state.set_state(GenerationStates.waiting_for_video_prompt)
    await message.answer(
        "✅ Видео движения загружено. Теперь отправьте промпт или короткое описание результата.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="motion",
            current_model=data.get("v_model", "motion_control_v26"),
            has_start_image=bool(data.get("v_image_url")),
            reference_video_count=1,
        ),
    )


@router.message(GenerationStates.waiting_for_avatar_audio, F.audio | F.voice | F.document)
async def final_avatar_audio_upload(message: types.Message, state: FSMContext):
    """Upload audio for Kling Avatar."""
    data = await state.get_data()
    if data.get("v_type") != "avatar":
        return

    media = message.audio or message.voice or message.document
    file = await message.bot.get_file(media.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    ext = "ogg" if message.voice else "mp3"
    if message.document and getattr(message.document, "file_name", ""):
        ext = message.document.file_name.rsplit(".", 1)[-1].lower() if "." in message.document.file_name else "mp3"
    audio_url = save_uploaded_file(downloaded.read(), ext)
    await state.update_data(avatar_audio_url=audio_url, audio_url=audio_url)
    await state.set_state(GenerationStates.waiting_for_video_prompt)

    await message.answer(
        "✅ Аудио загружено. Теперь отправьте промпт или короткую инструкцию для аватара.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="avatar",
            current_model=data.get("v_model", "avatar_std"),
            has_start_image=bool(data.get("v_image_url")),
            has_avatar_audio=True,
        ),
    )
'''

if 'FINAL KLING AVATAR / MOTION BUTTON FIXES' not in s:
    s += append

p.write_text(s, encoding="utf-8")

PY

python3 -m py_compile bot/keyboards.py bot/services/preset_manager.py bot/handlers/generation.py

echo "Kling bot buttons/avatar/motion patch applied."
echo "Run: ./stop.sh && ./start.sh"
