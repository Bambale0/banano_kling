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

# First, surgically replace broken multiline welcome fragments regardless of quote style.
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

    # Handles: "Привет 👋\n...🚀" and 'Привет 👋\n...🚀'
    s = re.sub(
        r'([\"\'])Привет 👋[\s\S]{0,900}?начать творить 🚀\1',
        WELCOME_PY,
        s,
        flags=re.S,
    )
    # Handles broken strings without closing quote before comma/paren/new statement.
    s = re.sub(
        r'([\"\'])Привет 👋[\s\S]{0,900}?начать творить 🚀(?=\s*[,\)])',
        WELCOME_PY,
        s,
        flags=re.S,
    )
    # Handles the exact current failure: opened single quote at line 75, no matching close.
    s = re.sub(
        r"'Привет 👋[\s\S]{0,900}?творить 🚀",
        WELCOME_PY,
        s,
        flags=re.S,
    )
    s = re.sub(
        r'"Привет 👋[\s\S]{0,900}?творить 🚀',
        WELCOME_PY,
        s,
        flags=re.S,
    )

    s = s.replace("Banano AI Studio", "NEUROMIX")

    if s != original:
        p.write_text(s, encoding="utf-8")

Path("bot/neuromix_copy.py").write_text(
    "WELCOME_TEXT = " + WELCOME_PY + "\n",
    encoding="utf-8",
)
PY

# If common.py is still syntactically broken, patch the whole likely start/menu answer block by line range.
python3 - <<'PY'
from pathlib import Path
import py_compile

WELCOME = repr('''Привет 👋

Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.

👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀''')

p = Path("bot/handlers/common.py")
if p.exists():
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception:
        lines = p.read_text(encoding="utf-8").splitlines()
        start = None
        for i, line in enumerate(lines):
            if "Привет 👋" in line:
                start = i
                break
        if start is not None:
            end = start + 1
            while end < len(lines):
                if "reply_markup=" in lines[end] or "parse_mode=" in lines[end] or lines[end].strip().endswith(")"):
                    break
                end += 1
            lines[start:end] = ["        " + WELCOME]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
