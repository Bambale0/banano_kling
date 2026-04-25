#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# -----------------------------------------------------------------------------
# 1) keyboards.py: main menu button + Motion Control version keyboard
# -----------------------------------------------------------------------------
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")

# Main menu: standalone Motion Control button after video if missing.
main_start = s.find("def get_main_menu_keyboard")
main_end = s.find("def get_create_hub_keyboard", main_start)
main_block = s[main_start:main_end]
if 'callback_data="motion_control"' not in main_block:
    s = s.replace(
        '    builder.button(text="🎬 Создать видео", callback_data="create_video_new")\n',
        '    builder.button(text="🎬 Создать видео", callback_data="create_video_new")\n    builder.button(text="🎯 Motion Control", callback_data="motion_control")\n',
        1,
    )
    # Keep layout sane. If the exact old adjust is not found, leave it untouched.
    s = s.replace('builder.adjust(1, 2, 2, 2, 2, 1)', 'builder.adjust(1, 2, 2, 2, 2, 1, 1)', 1)
    s = s.replace('builder.adjust(2, 2, 2, 2, 1)', 'builder.adjust(2, 2, 2, 2, 1, 1)', 1)

# Human labels.
if '"motion_control_v26": "Kling 2.6 Motion Control"' not in s:
    s = s.replace(
        '    "avatar_pro": "Kling AI Avatar Pro",\n',
        '    "avatar_pro": "Kling AI Avatar Pro",\n    "motion_control_v26": "Kling 2.6 Motion Control",\n    "motion_control_v30": "Kling 3.0 Motion Control",\n',
        1,
    )

# Remove Motion entries from normal video model selector if previous patches added them there.
s = re.sub(
    r'\n\s*\("motion_control_v26",\s*"🎯 Kling 2\.6 Motion",\s*preset_manager\.get_video_cost\("motion_control_v26", 5\),\s*\),',
    '',
    s,
)
s = re.sub(
    r'\n\s*\("motion_control_v30",\s*"🚀 Kling 3\.0 Motion",\s*preset_manager\.get_video_cost\("motion_control_v30", 5\),\s*\),',
    '',
    s,
)

# Add dedicated keyboard function.
if "def get_motion_control_model_keyboard" not in s:
    insert_after = s.find("def get_animate_hub_keyboard")
    next_def = s.find("\ndef ", insert_after + 1)
    func = r'''

def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    """Separate Motion Control menu: choose Kling 2.6 or 3.0. Pro mode is default."""
    builder = InlineKeyboardBuilder()
    rows = [
        ("motion_control_v26", "🎯 Kling 2.6 Motion Control", preset_manager.get_video_cost("motion_control_v26", 5)),
        ("motion_control_v30", "🚀 Kling 3.0 Motion Control", preset_manager.get_video_cost("motion_control_v30", 5)),
    ]
    for model_key, label, cost in rows:
        check = "✅ " if current_model == model_key else ""
        builder.button(
            text=f"{check}{label} • Pro • {cost}🍌",
            callback_data=f"motion_model_{model_key}",
        )
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()
'''
    s = s[:next_def] + func + s[next_def:]

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) preset_manager.py: fallback aliases/costs if missing
# -----------------------------------------------------------------------------
p = Path("bot/services/preset_manager.py")
s = p.read_text(encoding="utf-8")
if '"motion_control_v26"' not in s:
    # Add aliases near glow if present, otherwise do nothing destructive.
    s = s.replace('"glow": "glow",', '"glow": "glow",\n    "motion_control_v26": "motion_control_v26",\n    "motion_control_v30": "motion_control_v30",')
if '"motion_control_v26": 12' not in s:
    s = s.replace('"glow": 5,', '"glow": 5,\n    "motion_control_v26": 12,\n    "motion_control_v30": 18,')
p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) kling_service.py: support v2.6/v3.0 motion model and force pro/1080p
# -----------------------------------------------------------------------------
p = Path("bot/services/kling_service.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    'MOTION_MODELS = {"kling-2.6/motion-control", "motion_control"}',
    'MOTION_MODELS = {"kling-2.6/motion-control", "kling-3.0/motion-control", "motion_control", "motion_control_v26", "motion_control_v30"}',
)

# Add model param to create_kie_motion_task if not already present.
if 'model: str = "kling-2.6/motion-control"' not in s:
    s = s.replace(
'''    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Kie.ai Kling 2.6 Motion Control task."""
        payload: Dict[str, Any] = {
            "model": "kling-2.6/motion-control",
            "input": input_data,
        }
''',
'''    async def create_kie_motion_task(
        self,
        input_data: Dict[str, Any],
        webhook: Optional[str] = None,
        model: str = "kling-2.6/motion-control",
    ) -> Dict[str, Any]:
        """Create Kie.ai Kling Motion Control task."""
        payload: Dict[str, Any] = {
            "model": model,
            "input": input_data,
        }
''')

# Add motion_model param to generate_motion_control.
if 'motion_model: str = "kling-2.6/motion-control"' not in s:
    s = s.replace(
'''        motion_direction: str = "video",
        mode: str = "std",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
''',
'''        motion_direction: str = "video",
        mode: str = "std",
        motion_model: str = "kling-2.6/motion-control",
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
''', 1)

# Ensure return passes chosen model.
s = s.replace(
'''        return await self.create_kie_motion_task(input_data, webhook_url)
''',
'''        if motion_model not in {"kling-2.6/motion-control", "kling-3.0/motion-control"}:
            motion_model = "kling-2.6/motion-control"
        logger.info("Motion Control payload prepared: model=%s mode=%s", motion_model, input_data.get("mode"))
        return await self.create_kie_motion_task(input_data, webhook_url, model=motion_model)
''', 1)

# High-level routing: map v26/v30 and force pro mode.
s = s.replace(
'''        if model in self.MOTION_MODELS or "motion" in model.lower():
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                prompt=prompt,
                motion_direction="video",
                mode="std",
                webhook_url=webhook_url,
            )
''',
'''        if model in self.MOTION_MODELS or "motion" in model.lower():
            motion_model = (
                "kling-3.0/motion-control"
                if model in {"motion_control_v30", "kling-3.0/motion-control"}
                else "kling-2.6/motion-control"
            )
            return await self.generate_motion_control(
                image_url=image_url or "",
                video_urls=video_urls or [],
                prompt=prompt,
                motion_direction="video",
                mode="pro",
                motion_model=motion_model,
                webhook_url=webhook_url,
            )
''')

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 4) generation.py: dedicated Motion Control menu handlers
# -----------------------------------------------------------------------------
p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

# Ensure imports include the new keyboard.
if "get_motion_control_model_keyboard" not in s:
    s = s.replace(
        "get_more_menu_keyboard,",
        "get_more_menu_keyboard,\n    get_motion_control_model_keyboard,",
        1,
    )

# Remove earlier broken Motion Control final blocks if present.
s = re.sub(
    r'\n# =============================================================================\n# FINAL KLING AVATAR / MOTION BUTTON FIXES\n# =============================================================================\n.*',
    '\n',
    s,
    flags=re.S,
)

append = r'''

# =============================================================================
# MOTION CONTROL DEDICATED MENU
# =============================================================================

@router.callback_query(F.data == "motion_control")
async def open_motion_control_menu(callback: types.CallbackQuery, state: FSMContext):
    """Open dedicated Motion Control version chooser."""
    await state.clear()
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model="motion_control_v26",
        v_duration=5,
        v_ratio="motion",
        v_image_url=None,
        v_reference_videos=[],
        motion_mode="1080p",
        motion_orientation="video",
    )
    text = (
        "🎯 <b>Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Выберите версию Kling. Обе версии запускаются в <b>Pro-режиме</b> по умолчанию."
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_motion_control_model_keyboard("motion_control_v26"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.in_({"motion_model_motion_control_v26", "motion_model_motion_control_v30"}))
async def select_motion_control_model(callback: types.CallbackQuery, state: FSMContext):
    """Select Motion Control model and ask for character photo."""
    model = callback.data.replace("motion_model_", "")
    label = "Kling 3.0 Motion Control" if model == "motion_control_v30" else "Kling 2.6 Motion Control"
    user_credits = await get_user_credits(callback.from_user.id)
    await state.update_data(
        generation_type="video",
        v_type="motion",
        v_model=model,
        v_duration=5,
        v_ratio="motion",
        v_image_url=None,
        v_reference_videos=[],
        motion_mode="1080p",
        motion_orientation="video",
    )
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    text = (
        f"🎯 <b>{label}</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n"
        "⚙️ Режим: <b>Pro / 1080p</b>\n\n"
        "Шаг 1. Отправьте <b>фото персонажа</b>, которого нужно оживить."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer(label)


@router.message(GenerationStates.waiting_for_video_start_image, F.photo)
async def motion_control_character_photo_upload(message: types.Message, state: FSMContext):
    """Upload character photo for dedicated Motion Control flow."""
    data = await state.get_data()
    if data.get("v_type") != "motion":
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    image_url = save_uploaded_file(downloaded.read(), "jpg")
    await state.update_data(v_image_url=image_url)
    await state.set_state(GenerationStates.uploading_reference_videos)
    await message.answer(
        "✅ Фото персонажа загружено.\n\n"
        "Шаг 2. Теперь отправьте <b>видео движения</b>.",
        parse_mode="HTML",
    )


@router.message(GenerationStates.uploading_reference_videos, F.video)
async def motion_control_reference_video_upload(message: types.Message, state: FSMContext):
    """Upload movement video for dedicated Motion Control flow."""
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
        "✅ Видео движения загружено.\n\n"
        "Шаг 3. Отправьте короткое описание результата.\n"
        "Например: <i>сохранить лицо, плавное движение, кинематографичный свет</i>.",
        parse_mode="HTML",
    )
'''

if "MOTION CONTROL DEDICATED MENU" not in s:
    s += append

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py bot/services/preset_manager.py bot/services/kling_service.py bot/handlers/generation.py

echo "Motion Control dedicated menu installed. Restart bot with ./stop.sh && ./start.sh"
