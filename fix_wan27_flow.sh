#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("bot/handlers/generation.py")
s = p.read_text(encoding="utf-8")

# Remove every old/experimental Wan model callback handler.
pattern = re.compile(
    r'\n*@router\.callback_query\(F\.data == "model_wan_27"\)\n'
    r'async def select_model_wan_27(?:_test)?\(callback: types\.CallbackQuery, state: FSMContext\):\n'
    r'(?:(?!\n@router\.callback_query|\n@router\.message|\n# =============================================================================).+\n)*',
    re.MULTILINE,
)
s = pattern.sub('\n', s)

handler = '''
@router.callback_query(F.data == "model_wan_27")
async def select_model_wan_27(callback: types.CallbackQuery, state: FSMContext):
    """Select Wan 2.7 Pro through the standard image flow."""
    logger.info("Wan 2.7 selected by user_id=%s", callback.from_user.id)
    data = await state.get_data()
    await state.update_data(
        generation_type="image",
        img_service="wan_27",
        img_ratio=data.get("img_ratio", "1:1"),
        img_count=data.get("img_count", 1),
        reference_images=list(data.get("reference_images") or []),
        img_quality="basic",
        img_nsfw_checker=False,
        nsfw_enabled=False,
        preset_id="new",
        img_flow_step="settings",
    )
    await _show_image_creation_screen(callback, state)
    await callback.answer("Выбрана тестовая модель Wan 2.7 Pro")
'''

if 'F.data == "model_wan_27"' not in s:
    marker = '@router.callback_query(F.data.startswith("repeat_image_"))'
    if marker not in s:
        marker = '@router.callback_query(F.data == "main_img_banana_pro")'
    if marker not in s:
        raise SystemExit('Could not find insertion marker for wan_27 handler')
    idx = s.index(marker)
    s = s[:idx] + handler + '\n\n' + s[idx:]

# Ensure main shortcut uses standard model handler if present.
s = s.replace(
    'async def show_main_img_wan_27(callback: types.CallbackQuery, state: FSMContext):\n    await _open_image_model_from_main(callback, state, model="wan_27")',
    'async def show_main_img_wan_27(callback: types.CallbackQuery, state: FSMContext):\n    await state.update_data(img_service="wan_27", preset_id="new", img_flow_step="settings")\n    await _show_image_creation_screen(callback, state)\n    await callback.answer("Выбрана тестовая модель Wan 2.7 Pro")',
)

p.write_text(s, encoding="utf-8")

# Patch keyboards: ensure Wan row is exactly 4 fields and labels exist.
p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")
if '"wan_27": "Wan 2.7 Pro"' not in s:
    s = s.replace(
        '"grok_imagine_i2i": "Grok Imagine",',
        '"grok_imagine_i2i": "Grok Imagine",\n    "wan_27": "Wan 2.7 Pro",',
    )

if '"model_wan_27"' not in s:
    needle = '''        (
            "grok_imagine_i2i",
            "model_grok_i2i",
            "🧠 Grok Imagine",
            preset_manager.get_generation_cost("grok_imagine_i2i"),
        ),'''
    insert = needle + '''
        (
            "wan_27",
            "model_wan_27",
            "🧪 Wan 2.7 Pro",
            preset_manager.get_generation_cost("wan_27"),
        ),'''
    if needle in s:
        s = s.replace(needle, insert, 1)

p.write_text(s, encoding="utf-8")

# Patch preset manager aliases/cost fallback cautiously.
p = Path("bot/services/preset_manager.py")
s = p.read_text(encoding="utf-8")
if '"wan_27": "wan_27"' not in s:
    s = s.replace(
        '"grok_imagine_i2i": "grok_imagine_i2i",',
        '"grok_imagine_i2i": "grok_imagine_i2i",\n    "wan_27": "wan_27",\n    "wan27": "wan_27",\n    "wan-2.7": "wan_27",',
    )
if '"wan_27": 7' not in s:
    s = s.replace('"grok_imagine_i2i": 7,', '"grok_imagine_i2i": 7,\n    "wan_27": 7,')
p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/handlers/generation.py bot/keyboards.py bot/services/preset_manager.py bot/services/wan27_service.py

echo "Wan 2.7 flow repaired. Check with: grep -n 'model_wan_27\|select_model_wan' bot/handlers/generation.py"
