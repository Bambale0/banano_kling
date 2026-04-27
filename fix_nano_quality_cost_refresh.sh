#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# 1) Short labels only: 2K / 4K
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")
original = s

repls = {
    'text=("◉ 2K качество - 5 бананов" if q == "2K" else "○ 2K качество - 5 бананов")': 'text=("◉ 2K" if q == "2K" else "○ 2K")',
    'text=("◉ 4K качество - 7 бананов" if q == "4K" else "○ 4K качество - 7 бананов")': 'text=("◉ 4K" if q == "4K" else "○ 4K")',
    'text=("◉ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")': 'text=("◉ 2K" if q == "2K" else "○ 2K")',
    'text=("◉ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")': 'text=("◉ 4K" if q == "4K" else "○ 4K")',
    'text=("✅ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")': 'text=("◉ 2K" if q == "2K" else "○ 2K")',
    'text=("✅ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")': 'text=("◉ 4K" if q == "4K" else "○ 4K")',
}
for a, b in repls.items():
    s = s.replace(a, b)

if s != original:
    p.write_text(s, encoding="utf-8")

# 2) Make settings screen read updated state after callback, so selected button and cost refresh.
p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")
original = s

# Make toasts short.
s = s.replace('await callback.answer("Выбрано 2K качество - 5 бананов")', 'await callback.answer("Выбрано 2K")')
s = s.replace('await callback.answer("Выбрано 4K качество - 7 бананов")', 'await callback.answer("Выбрано 4K")')
s = s.replace('await callback.answer("Выбрано 2K качество — 5🍌")', 'await callback.answer("Выбрано 2K")')
s = s.replace('await callback.answer("Выбрано 4K качество — 7🍌")', 'await callback.answer("Выбрано 4K")')

# Patch _show_image_settings_screen: if it computes data before callback update, force fresh data before cost/markup.
# Insert a robust cost override immediately before settings_lines when present.
if "nano_quality_cost_screen_v2" not in s:
    s = s.replace(
        '    settings_lines = [\n        f"• Модель: <code>{get_image_model_label(current_service)}</code>",',
        '    # nano_quality_cost_screen_v2\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n        total_cost = unit_cost * current_count\n\n    settings_lines = [\n        f"• Модель: <code>{get_image_model_label(current_service)}</code>",',
        1,
    )

# Some versions use another screen text block with info_lines.
if "nano_quality_cost_info_v2" not in s:
    s = s.replace(
        '    info_lines = [\n        f"• Модель: <code>{get_image_model_label(current_service)}</code>",',
        '    # nano_quality_cost_info_v2\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n        total_cost = unit_cost * current_count\n\n    info_lines = [\n        f"• Модель: <code>{get_image_model_label(current_service)}</code>",',
        1,
    )

# Ensure callback handlers refresh with fresh FSM data. Replace current handler block if it exists.
pattern = r'@router\.callback_query\(F\.data == "img_quality_2k"\)\nasync def set_image_quality_2k[\s\S]*?@router\.callback_query\(F\.data == "img_quality_4k"\)\nasync def set_image_quality_4k[\s\S]*?(?=\n\n@router\.callback_query|\Z)'
new_handlers = '''@router.callback_query(F.data == "img_quality_2k")
async def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="2K")
    await callback.answer("Выбрано 2K")
    await _show_image_settings_screen(callback, state)


@router.callback_query(F.data == "img_quality_4k")
async def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="4K")
    await callback.answer("Выбрано 4K")
    await _show_image_settings_screen(callback, state)
'''
if re.search(pattern, s):
    s = re.sub(pattern, new_handlers, s, count=1)
elif 'F.data == "img_quality_2k"' not in s:
    s += "\n\n" + new_handlers

if s != original:
    p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py bot/miniapp.py

echo "OK: Nano quality labels and cost refresh fixed. Restart: ./restart.sh"
