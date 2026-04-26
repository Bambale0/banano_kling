#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

NEW_WELCOME = '''Привет 👋

Я <b>NEUROMIX</b> — самый выгодный и очень удобный бот для генерации изображений и видео.

👇 Пользуйся текстовым вариантом генераций или открой приложение, чтобы начать творить 🚀'''

# Patch visible bot welcome/menu copy wherever it is commonly rendered.
for rel in [
    "bot/main.py",
    "bot/handlers/generation.py",
    "bot/handlers/menu.py",
    "bot/handlers/start.py",
    "bot/handlers/common.py",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    patterns = [
        r'🏠\s*<b>Banano AI Studio</b>[\s\S]{0,900}?Нажмите нужную кнопку ниже\.?',
        r'🏠\s*Banano AI Studio[\s\S]{0,900}?Нажмите нужную кнопку ниже\.?',
        r'<b>Banano AI Studio</b>[\s\S]{0,900}?Нажмите нужную кнопку ниже\.?',
        r'Banano AI Studio[\s\S]{0,900}?Нажмите нужную кнопку ниже\.?',
        r'Выберите, что хотите сделать\. Бот сам провед[её]т вас по шагам\.[\s\S]{0,700}?Нажмите нужную кнопку ниже\.?',
    ]
    for pat in patterns:
        s = re.sub(pat, NEW_WELCOME, s, flags=re.S)

    # Conservative replacements for leftover brand mentions in user-facing text.
    s = s.replace("🏠 Banano AI Studio", "NEUROMIX")
    s = s.replace("<b>Banano AI Studio</b>", "<b>NEUROMIX</b>")
    s = s.replace("Banano AI Studio", "NEUROMIX")

    if s != original:
        p.write_text(s, encoding="utf-8")

# Add a tiny helper with the canonical welcome text for future reuse.
p = Path("bot/neuromix_copy.py")
p.write_text(
    'WELCOME_TEXT = ''' + repr(NEW_WELCOME) + '''\n',
    encoding="utf-8",
)
PY

# Verify changed Python files that exist.
python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in ["bot/main.py", "bot/handlers/generation.py", "bot/handlers/menu.py", "bot/handlers/start.py", "bot/handlers/common.py", "bot/neuromix_copy.py"]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("NEUROMIX bot welcome patch applied.")
PY

echo "Restart bot: ./stop.sh && ./start.sh"
echo "Check: grep -R 'NEUROMIX\|Banano AI Studio' -n bot | head -40"
