#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# -----------------------------------------------------------------------------
# 1) keyboards.py: remove Motion from video model list, add separate Motion menu
# -----------------------------------------------------------------------------
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")

# Remove Motion Control rows from get_video_model_selection_keyboard no matter what cost value is used.
s = re.sub(
    r'\n\s*\(\s*"motion_control_v26",\s*"🎯 Kling 2\.6 Motion",\s*preset_manager\.get_video_cost\("motion_control_v26",\s*\d+\),\s*\),',
    '',
    s,
    flags=re.S,
)
s = re.sub(
    r'\n\s*\(\s*"motion_control_v30",\s*"🚀 Kling 3\.0 Motion",\s*preset_manager\.get_video_cost\("motion_control_v30",\s*\d+\),\s*\),',
    '',
    s,
    flags=re.S,
)

# Also remove any simple leftover rows if script was edited manually.
s = re.sub(r'\n\s*\("motion_control_v26".*?\),', '', s, flags=re.S)
s = re.sub(r'\n\s*\("motion_control_v30".*?\),', '', s, flags=re.S)

# Add a dedicated keyboard for Motion Control model selection.
if 'def get_motion_control_model_keyboard' not in s:
    insert_after = 'def get_animate_hub_keyboard():'
    idx = s.find(insert_after)
    if idx == -1:
        raise SystemExit('Could not find get_animate_hub_keyboard marker')
    # put helper after get_animate_hub_keyboard block, before get_more_menu_keyboard
    marker = '\n\ndef get_more_menu_keyboard():'
    pos = s.find(marker)
    if pos == -1:
        raise SystemExit('Could not find get_more_menu_keyboard marker')
    helper = '''

def get_motion_control_model_keyboard(current_model: str = "motion_control_v26"):
    """Отдельный выбор версии Motion Control."""
    builder = InlineKeyboardBuilder()

    options = [
        (
            "motion_control_v26",
            "🎯 Kling 2.6 Motion Control",
            "Стабильный перенос движения",
            preset_manager.get_video_cost("motion_control_v26", 5),
        ),
        (
            "motion_control_v30",
            "🚀 Kling 3.0 Motion Control",
            "Новая версия с улучшенной стабильностью",
            preset_manager.get_video_cost("motion_control_v30", 5),
        ),
    ]

    for model_key, title, description, cost in options:
        check = "✅ " if current_model == model_key else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{check}{title} • {cost}🍌",
                callback_data=f"v_model_{model_key}",
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main"))
    return builder.as_markup()
'''
    s = s[:pos] + helper + s[pos:]

p.write_text(s, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) generation.py: import new keyboard, make main Motion button show model choice
# -----------------------------------------------------------------------------
p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

# Add import into keyboards import tuple/list.
if 'get_motion_control_model_keyboard' not in s:
    s = s.replace(
        'get_video_media_step_keyboard,',
        'get_video_media_step_keyboard,\n    get_motion_control_model_keyboard,',
        1,
    )

# Replace the standalone Motion entry handler body so it first shows model choice.
pattern = re.compile(
    r'@router\.callback_query\(F\.data == "motion_control"\)\n'
    r'async def open_motion_control_from_main\(callback: types\.CallbackQuery, state: FSMContext\):\n'
    r'.*?\n\n(?=@router\.callback_query|@router\.message|# =============================================================================|\Z)',
    re.S,
)
replacement = '''@router.callback_query(F.data == "motion_control")
async def open_motion_control_from_main(callback: types.CallbackQuery, state: FSMContext):
    """Standalone Motion Control entry from main menu: choose Kling version first."""
    await state.clear()
    user_credits = await get_user_credits(callback.from_user.id)
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
    await callback.message.edit_text(
        "🎯 <b>Motion Control</b>\n"
        f"🍌 Баланс: <code>{user_credits}</code> бананов\n\n"
        "Выберите версию Kling для переноса движения.\n\n"
        "После выбора загрузите фото персонажа и видео с движением.",
        reply_markup=get_motion_control_model_keyboard("motion_control_v26"),
        parse_mode="HTML",
    )
    await callback.answer()

'''
if 'async def open_motion_control_from_main' in s:
    s, n = pattern.subn(replacement, s, count=1)
    if n == 0:
        raise SystemExit('Could not replace motion_control handler')
else:
    s += '\n\n' + replacement

# Ensure model selection handlers show media-upload screen and not generic video list.
for model_key, title in [
    ('motion_control_v26', 'Kling 2.6 Motion Control'),
    ('motion_control_v30', 'Kling 3.0 Motion Control'),
]:
    func = f'select_{model_key.replace("motion_control_", "motion_")}'
    if f'F.data == "v_model_{model_key}"' not in s:
        s += f'''

@router.callback_query(F.data == "v_model_{model_key}")
async def {func}(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(v_model="{model_key}", v_type="motion", v_ratio="motion", v_duration=5, v_image_url=None, v_reference_videos=[])
    await state.set_state(GenerationStates.waiting_for_video_start_image)
    await callback.message.edit_text(
        "🎯 <b>{title}</b>\n\n"
        "Загрузите фото персонажа и видео движения.",
        reply_markup=get_video_media_step_keyboard(
            current_v_type="motion",
            current_model="{model_key}",
            has_start_image=False,
            reference_video_count=0,
        ),
        parse_mode="HTML",
    )
    await callback.answer("{title}")
'''

# If old handlers exist, make their first screen consistent and include model choice only after main entry.
# No-op if they already work.

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py

echo "Motion Control split fixed."
echo "Checks:"
echo "  grep -n 'motion_control_v26\|motion_control_v30' bot/keyboards.py | head -40"
echo "  grep -n 'get_motion_control_model_keyboard\|open_motion_control_from_main' bot/handlers/generation.py bot/keyboards.py"
