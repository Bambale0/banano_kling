#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("bot/keyboards.py")
s = p.read_text(encoding="utf-8")

# Remove prompt channel / Telegram channel links from the main bot menu completely.
s = re.sub(
    r'\n\s*builder\.button\(text="📚 Промпт-канал",\s*url="https://t\.me/only_tm_ii"\)',
    '',
    s,
)
s = re.sub(
    r'\n\s*builder\.button\([^\n]*Промпт-канал[^\n]*\)',
    '',
    s,
)
s = re.sub(
    r'\n\s*builder\.button\([^\n]*only_tm_ii[^\n]*\)',
    '',
    s,
)

# Main menu layout had one extra button before. Keep rows clean after removing the channel button.
s = s.replace('builder.adjust(1, 2, 2, 2, 2, 1, 1)', 'builder.adjust(1, 2, 2, 2, 1, 1)', 1)
s = s.replace('builder.adjust(2, 2, 2, 2, 1, 1)', 'builder.adjust(2, 2, 2, 1, 1)', 1)

p.write_text(s, encoding="utf-8")
PY

python3 -m py_compile bot/keyboards.py

echo "Prompt channel button removed from bot main menu. Restart bot: ./stop.sh && ./start.sh"
echo "Check: grep -R 'Промпт-канал\|only_tm_ii' -n bot || true"
