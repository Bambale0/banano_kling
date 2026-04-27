#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path('bot/keyboards.py')
s = p.read_text(encoding='utf-8')

# Add 2K/4K buttons inside get_create_image_keyboard right before count buttons.
if 'nano_quality_buttons_inserted_v1' not in s:
    marker = '    # Количество\n'
    insert = '''    # nano_quality_buttons_inserted_v1\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        q = (img_quality or "2K").upper()\n        builder.button(\n            text=("◉ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌"),\n            callback_data="img_quality_2k",\n        )\n        builder.button(\n            text=("◉ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌"),\n            callback_data="img_quality_4k",\n        )\n\n'''
    if marker not in s:
        raise SystemExit('marker not found in bot/keyboards.py')
    s = s.replace(marker, insert + marker, 1)

p.write_text(s, encoding='utf-8')

p = Path('bot/handlers/generation.py')
s = p.read_text(encoding='utf-8')

# Normalize defaults for image flow from basic to 2K where explicit setup initializes basic.
s = s.replace('img_quality="basic"', 'img_quality="2K"')
s = s.replace('data.get("img_quality", "basic")', 'data.get("img_quality", "2K")')
s = s.replace('request_data.get("img_quality", "basic")', 'request_data.get("img_quality", "2K")')

# Make legacy basic/high callbacks map to new visible quality where used.
s = s.replace('await state.update_data(img_quality="basic")', 'await state.update_data(img_quality="2K")')
s = s.replace('await state.update_data(img_quality="high")', 'await state.update_data(img_quality="4K")')
s = s.replace('await callback.answer("Basic quality")', 'await callback.answer("Выбрано 2K качество — 5🍌")')
s = s.replace('await callback.answer("High quality")', 'await callback.answer("Выбрано 4K качество — 7🍌")')

p.write_text(s, encoding='utf-8')
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py bot/miniapp.py

echo "Nano quality buttons wired into image settings keyboard. Restart: ./restart.sh"
