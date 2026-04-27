#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")
original = s

# Restore the Mini App button at the top of the main menu if it was removed by a bad line-based cleanup.
if '🚀 Открыть Mini App' not in s:
    marker = '    builder = InlineKeyboardBuilder()\n\n'
    insert = '''    if config.mini_app_url:\n        builder.button(\n            text="🚀 Открыть Mini App",\n            web_app=WebAppInfo(url=config.mini_app_url),\n        )\n'''
    # Insert only inside get_main_menu_keyboard.
    idx = s.find('def get_main_menu_keyboard')
    if idx == -1:
        raise SystemExit('get_main_menu_keyboard not found')
    sub = s[idx:]
    mpos = sub.find(marker)
    if mpos == -1:
        raise SystemExit('builder marker not found in get_main_menu_keyboard')
    abs_pos = idx + mpos + len(marker)
    s = s[:abs_pos] + insert + s[abs_pos:]

# Remove only prompt channel line, not Mini App.
s = "".join(
    line for line in s.splitlines(True)
    if "Промпт-канал" not in line and "only_tm_ii" not in line
)

# Make sure layout accounts for optional Mini App first row.
if 'if config.mini_app_url:' not in s[s.find('def get_main_menu_keyboard'):s.find('def get_create_hub_keyboard')]:
    pass

if s != original:
    p.write_text(s, encoding="utf-8")
    print("updated bot/keyboards.py")
PY

python3 -m py_compile bot/keyboards.py bot/handlers/common.py bot/miniapp.py

echo "OK: Mini App button restored and prompt channel removed. Restart: ./restart.sh"
