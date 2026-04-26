#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

WELCOME_HTML = '''Привет 👋

Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.

👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀'''

WELCOME_PY = repr(WELCOME_HTML)

for rel in [
    "bot/handlers/common.py",
    "bot/main.py",
    "bot/handlers/generation.py",
    "bot/handlers/menu.py",
    "bot/handlers/start.py",
]:
    p = Path(rel)
    if not p.exists():
        continue

    s = p.read_text(encoding="utf-8")
    original = s

    # Fix the broken raw multiline string that starts with "Привет 👋 and was inserted without triple quotes.
    s = re.sub(
        r'"Привет 👋\n\nЯ <b>NEUROMIX</b>[\s\S]*?чтобы начать творить 🚀"',
        WELCOME_PY,
        s,
        flags=re.S,
    )
    s = re.sub(
        r'"Привет 👋\n\s*Я <b>NEUROMIX</b>[\s\S]*?творить 🚀"',
        WELCOME_PY,
        s,
        flags=re.S,
    )

    # More defensive: if a line contains an opened quote before Привет and the next few lines are the welcome, replace the whole string literal content.
    s = re.sub(
        r'"Привет 👋[\s\S]{0,500}?начать творить 🚀',
        WELCOME_PY[:-1],
        s,
        flags=re.S,
    )

    # Replace old brand leftovers in normal strings.
    s = s.replace("Banano AI Studio", "NEUROMIX")

    if s != original:
        p.write_text(s, encoding="utf-8")

Path("bot/neuromix_copy.py").write_text(
    "WELCOME_TEXT = " + WELCOME_PY + "\n",
    encoding="utf-8",
)
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
files = [
    "bot/handlers/common.py",
    "bot/main.py",
    "bot/handlers/generation.py",
    "bot/handlers/menu.py",
    "bot/handlers/start.py",
    "bot/neuromix_copy.py",
]
for rel in files:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("NEUROMIX multiline welcome strings fixed.")
PY

echo "Restart bot: ./stop.sh && ./start.sh"
