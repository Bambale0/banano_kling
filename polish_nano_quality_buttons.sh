#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")
original = s

# Shorten visible labels: only 2K / 4K.
s = s.replace('text=("◉ 2K качество - 5 бананов" if q == "2K" else "○ 2K качество - 5 бананов")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("◉ 4K качество - 7 бананов" if q == "4K" else "○ 4K качество - 7 бананов")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')
s = s.replace('text=("◉ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("◉ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')
s = s.replace('text=("✅ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌")', 'text=("◉ 2K" if q == "2K" else "○ 2K")')
s = s.replace('text=("✅ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌")', 'text=("◉ 4K" if q == "4K" else "○ 4K")')

if s != original:
    p.write_text(s, encoding="utf-8")

p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")
original = s

# Short callback toasts.
s = s.replace('await callback.answer("Выбрано 2K качество - 5 бананов")', 'await callback.answer("Выбрано 2K")')
s = s.replace('await callback.answer("Выбрано 4K качество - 7 бананов")', 'await callback.answer("Выбрано 4K")')
s = s.replace('await callback.answer("Выбрано 2K качество — 5🍌")', 'await callback.answer("Выбрано 2K")')
s = s.replace('await callback.answer("Выбрано 4K качество — 7🍌")', 'await callback.answer("Выбрано 4K")')

# Ensure current settings cost recalculates for Nano Banana at the screen-render stage.
if 'nano_quality_cost_display_v1' not in s:
    s = s.replace(
        'unit_cost = preset_manager.get_generation_cost(current_service)\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n    total_cost = unit_cost * current_count',
        '# nano_quality_cost_display_v1\n    unit_cost = preset_manager.get_generation_cost(current_service)\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n    total_cost = unit_cost * current_count'
    )

if s != original:
    p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py bot/miniapp.py

echo "OK: Nano quality labels shortened. Restart: ./restart.sh"
