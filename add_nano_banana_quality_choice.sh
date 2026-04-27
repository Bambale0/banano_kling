#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import json
import re

# 0) Repair bot/miniapp.py if previous script inserted a bad line inside try block.
p = Path("bot/miniapp.py")
if p.exists():
    s = p.read_text(encoding="utf-8")
    s = re.sub(
        r'\n\s*if img_service in \{"banana_pro", "nano_banana_pro", "nano-banana-pro", "banana_2", "nanobanana"\}:\n\s*unit_cost = 7 if str\(img_quality or "2K"\)\.upper\(\) == "4K" else 5\n',
        '\n',
        s,
        count=1,
    )
    p.write_text(s, encoding="utf-8")

# 1) Ensure price.json has 2K/4K pricing.
p = Path("data/price.json")
if p.exists():
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("batch_pricing", {})["upscale_costs"] = {"2K": 5, "4K": 7}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 2) Add keyboard helper only; do not blindly patch miniapp/generation blocks.
p = Path("bot/keyboards.py")
if p.exists():
    s = p.read_text(encoding="utf-8")
    if "get_nano_banana_quality_keyboard" not in s:
        s += '''


def get_nano_banana_quality_keyboard(current_quality: str = "2K"):
    """Клавиатура качества для Nano Banana: 2K/4K."""
    builder = InlineKeyboardBuilder()
    q = (current_quality or "2K").upper()
    builder.button(
        text=("✅ 2K качество — 5🍌" if q == "2K" else "○ 2K качество — 5🍌"),
        callback_data="img_quality_2k",
    )
    builder.button(
        text=("✅ 4K качество — 7🍌" if q == "4K" else "○ 4K качество — 7🍌"),
        callback_data="img_quality_4k",
    )
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.adjust(1, 1, 1)
    return builder.as_markup()
'''
    p.write_text(s, encoding="utf-8")

# 3) Add callback handlers to generation.py only if missing.
p = Path("bot/handlers/generation.py")
if p.exists():
    s = p.read_text(encoding="utf-8")
    if "img_quality_2k" not in s:
        s += '''


@router.callback_query(F.data == "img_quality_2k")
async def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="2K")
    await callback.answer("Выбрано 2K качество — 5🍌")
    try:
        await _show_image_settings_screen(callback, state)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "img_quality_4k")
async def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(img_quality="4K")
    await callback.answer("Выбрано 4K качество — 7🍌")
    try:
        await _show_image_settings_screen(callback, state)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=None)
'''
    p.write_text(s, encoding="utf-8")
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in ["bot/keyboards.py", "bot/handlers/generation.py", "bot/miniapp.py"]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("Nano Banana quality patch repaired safely.")
PY

echo "Now restart: ./restart.sh"
