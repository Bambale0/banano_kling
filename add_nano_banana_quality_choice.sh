#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

# 1) Ensure price.json has 2K/4K pricing.
p = Path("data/price.json")
if p.exists():
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("batch_pricing", {})["upscale_costs"] = {"2K": 5, "4K": 7}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 2) Patch generation handlers/keyboards conservatively.
for rel in ["bot/keyboards.py", "bot/handlers/generation.py", "bot/miniapp.py"]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    # Existing UI may have 1x/2x/4x/6x quantity buttons. Do not remove them globally.
    # Add a dedicated quality keyboard helper if missing.
    if rel == "bot/keyboards.py" and "get_nano_banana_quality_keyboard" not in s:
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

    if rel == "bot/handlers/generation.py":
        # Import helper if there is a keyboards import block and helper isn't imported.
        if "get_nano_banana_quality_keyboard" not in s:
            s = s.replace(
                "from bot.keyboards import (",
                "from bot.keyboards import (",
                1,
            )
        # Add standalone handlers at end; these callback names are safe and specific.
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

        # Quality cost: if unit_cost currently ignores img_quality, add adjustment near total_cost.
        if "if img_quality_upper == \"4K\":" not in s:
            s = s.replace(
                "unit_cost = preset_manager.get_generation_cost(img_service)\n    total_cost = unit_cost * img_count",
                "unit_cost = preset_manager.get_generation_cost(img_service)\n    img_quality_upper = str(img_quality or \"2K\").upper()\n    if img_service in {\"banana_pro\", \"nano_banana_pro\", \"nano-banana-pro\", \"banana_2\", \"nanobanana\"}:\n        unit_cost = 7 if img_quality_upper == \"4K\" else 5\n    total_cost = unit_cost * img_count",
            )

        # Current settings text: replace quality display/cost hints where possible.
        s = s.replace("Стоимость: 5🍌 ×", "Стоимость: 5🍌 ×")

    if rel == "bot/miniapp.py":
        # Ensure API/miniapp can pass quality and cost follows 2K/4K for Nano Banana.
        if "quality_cost = 7 if str(img_quality" not in s:
            s = s.replace(
                "unit_cost = preset_manager.get_generation_cost(img_service)",
                "unit_cost = preset_manager.get_generation_cost(img_service)\n    if img_service in {\"banana_pro\", \"nano_banana_pro\", \"nano-banana-pro\", \"banana_2\", \"nanobanana\"}:\n        unit_cost = 7 if str(img_quality or \"2K\").upper() == \"4K\" else 5",
                1,
            )

    if s != original:
        p.write_text(s, encoding="utf-8")
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in ["bot/keyboards.py", "bot/handlers/generation.py", "bot/miniapp.py"]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("Nano Banana quality patch applied.")
PY

echo "Now restart: ./restart.sh"
