#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path('bot/handlers/generation.py')
s = p.read_text(encoding='utf-8')
orig = s

# The real screen function is _show_image_creation_screen, not _show_image_settings_screen.
s = s.replace('await _show_image_settings_screen(callback, state)', 'await _show_image_creation_screen(callback, state)')

# Ensure 2K/4K handler block uses the real refresh function.
pattern = r'@router\.callback_query\(F\.data == "img_quality_2k"\)\nasync def set_image_quality_2k[\s\S]*?@router\.callback_query\(F\.data == "img_quality_4k"\)\nasync def set_image_quality_4k[\s\S]*?(?=\n\n@router\.callback_query|\Z)'
block = '''@router.callback_query(F.data == "img_quality_2k")
async def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="2K")
    await callback.answer("Выбрано 2K")
    await _show_image_creation_screen(callback, state)


@router.callback_query(F.data == "img_quality_4k")
async def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="4K")
    await callback.answer("Выбрано 4K")
    await _show_image_creation_screen(callback, state)
'''
if re.search(pattern, s):
    s = re.sub(pattern, block, s, count=1)
elif 'F.data == "img_quality_2k"' not in s:
    s += '\n\n' + block

p.write_text(s, encoding='utf-8')

# Patch the text builder, because _build_image_creation_text is what displays the cost.
p = Path('bot/handlers/generation.py')
s = p.read_text(encoding='utf-8')
if 'nano_quality_build_text_cost_v3' not in s:
    s = s.replace(
        '    unit_cost = preset_manager.get_generation_cost(current_service)\n    total_cost = unit_cost * current_count',
        '    # nano_quality_build_text_cost_v3\n    unit_cost = preset_manager.get_generation_cost(current_service)\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n    total_cost = unit_cost * current_count',
        1
    )
p.write_text(s, encoding='utf-8')

# Keyboard labels and selected state.
p = Path('bot/keyboards.py')
s = p.read_text(encoding='utf-8')
s = s.replace('text=("◉ 2K качество - 5 бананов" if q == "2K" else "○ 2K качество - 5 бананов")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("◉ 4K качество - 7 бананов" if q == "4K" else "○ 4K качество - 7 бананов")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')
s = s.replace('text=("◉ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("◉ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')
s = s.replace('text=("✅ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("✅ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')
p.write_text(s, encoding='utf-8')
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py bot/miniapp.py

echo "OK: final Nano quality refresh fixed. Restart: ./restart.sh"
