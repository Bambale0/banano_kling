#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import json
import re

report = []

def add_report(text):
    print(text)
    report.append(text)

price_path = Path("data/price.json")
if price_path.exists():
    data = json.loads(price_path.read_text(encoding="utf-8"))
    data.setdefault("batch_pricing", {})["upscale_costs"] = {"2K": 5, "4K": 7}
    data["support_contact"] = "@only_tany"
    costs = data.setdefault("costs_reference", {})
    image_models = costs.setdefault("image_models", {})
    image_models.update({
        "banana_2": 5,
        "nano-banana-pro": 5,
        "gemini_2_5_flash": 5,
        "gemini_3_pro": 5,
    })
    price_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    add_report("updated data/price.json quality prices")

keyboard_path = Path("bot/keyboards.py")
s = keyboard_path.read_text(encoding="utf-8")
original = s

s = re.sub(
    r'\n\ndef get_nano_banana_quality_keyboard\(current_quality: str = "2K"\):[\s\S]*?\n\s*return builder\.as_markup\(\)\n?',
    "\n",
    s,
    count=1,
)
s = s.replace('img_quality: str = "basic",', 'img_quality: str = "2K",')

if "nano_quality_buttons_inserted_v2" not in s:
    needle = "\n    count_buttons = []\n"
    block = '''\n    # nano_quality_buttons_inserted_v2\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        q = str(img_quality or "2K").upper()\n        builder.row(\n            InlineKeyboardButton(\n                text=("◉ 2K качество - 5 бананов" if q == "2K" else "○ 2K качество - 5 бананов"),\n                callback_data="img_quality_2k",\n            ),\n            InlineKeyboardButton(\n                text=("◉ 4K качество - 7 бананов" if q == "4K" else "○ 4K качество - 7 бананов"),\n                callback_data="img_quality_4k",\n            ),\n        )\n'''
    if needle not in s:
        raise SystemExit("Could not find count_buttons insertion point in bot/keyboards.py")
    s = s.replace(needle, block + needle, 1)
    add_report("inserted 2K and 4K buttons into get_create_image_keyboard")
else:
    add_report("2K and 4K buttons already inserted")

if s != original:
    keyboard_path.write_text(s, encoding="utf-8")

gen_path = Path("bot/handlers/generation.py")
s = gen_path.read_text(encoding="utf-8")
original = s

s = s.replace('img_quality="basic"', 'img_quality="2K"')
s = s.replace('img_quality = data.get("img_quality", "basic")', 'img_quality = data.get("img_quality", "2K")')
s = s.replace('img_quality = request_data.get("img_quality", "basic")', 'img_quality = request_data.get("img_quality", "2K")')
s = s.replace('data.get("img_quality", "basic")', 'data.get("img_quality", "2K")')
s = s.replace('request_data.get("img_quality", "basic")', 'request_data.get("img_quality", "2K")')
s = s.replace('await state.update_data(img_quality="basic")', 'await state.update_data(img_quality="2K")')
s = s.replace('await state.update_data(img_quality="high")', 'await state.update_data(img_quality="4K")')

s = re.sub(
    r'\n\n@router\.callback_query\(F\.data == "img_quality_2k"\)[\s\S]*?@router\.callback_query\(F\.data == "img_quality_4k"\)[\s\S]*?(?=\n\n@router\.callback_query|\Z)',
    "\n",
    s,
    count=1,
)

handler_block = '''\n\n@router.callback_query(F.data == "img_quality_2k")\nasync def set_image_quality_2k(callback: types.CallbackQuery, state: FSMContext):\n    await state.update_data(img_quality="2K")\n    await callback.answer("Выбрано 2K качество - 5 бананов")\n    await _show_image_settings_screen(callback, state)\n\n\n@router.callback_query(F.data == "img_quality_4k")\nasync def set_image_quality_4k(callback: types.CallbackQuery, state: FSMContext):\n    await state.update_data(img_quality="4K")\n    await callback.answer("Выбрано 4K качество - 7 бананов")\n    await _show_image_settings_screen(callback, state)\n'''

if 'F.data == "img_quality_2k"' not in s:
    s += handler_block
    add_report("added image quality callback handlers")
else:
    add_report("image quality callback handlers already present")

s = s.replace(
    'unit_cost = preset_manager.get_generation_cost(current_service)\n    total_cost = unit_cost * current_count',
    'unit_cost = preset_manager.get_generation_cost(current_service)\n    if current_service in {"banana_pro", "banana_2", "nanobanana", "nano_banana_pro", "nano-banana-pro"}:\n        unit_cost = 7 if str(img_quality or "2K").upper() == "4K" else 5\n    total_cost = unit_cost * current_count'
)

if s != original:
    gen_path.write_text(s, encoding="utf-8")

mini_path = Path("bot/miniapp.py")
if mini_path.exists():
    s = mini_path.read_text(encoding="utf-8")
    original = s
    s = s.replace('"qualities": ["basic", "high"]', '"qualities": ["2K", "4K"]')
    if s != original:
        mini_path.write_text(s, encoding="utf-8")
        add_report("updated miniapp quality metadata")

Path("nano_quality_patch_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py bot/handlers/generation.py bot/miniapp.py

echo "OK: Nano Banana quality buttons wired. Report:"
cat nano_quality_patch_report.txt

echo "Verify with: grep -n 'nano_quality_buttons_inserted_v2\|img_quality_2k\|img_quality_4k' bot/keyboards.py bot/handlers/generation.py"
echo "Restart: ./restart.sh"
