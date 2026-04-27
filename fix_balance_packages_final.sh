#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import re

PACKAGES = [
    (15, 65, "Мини"),
    (25, 90, "Старт"),
    (50, 160, "Оптимальный"),
    (100, 310, "Про"),
    (200, 605, "Студия"),
    (500, 1500, "Бизнес"),
    (1000, 2900, "Максимум"),
]

LABELS = [
    "🍌 Мини: 15🍌 за 65₽",
    "🍌 Старт: 25🍌 за 90₽",
    "🍌🍌 Оптимальный: 50🍌 за 160₽ 🔥",
    "🍌🍌🍌 Про: 100🍌 за 310₽",
    "🍌🍌🍌🍌 Студия: 200🍌 за 605₽",
    "🍌🍌🍌🍌🍌 Бизнес: 500🍌 за 1500₽",
    "🍌🍌🍌🍌🍌🍌 Максимум: 1000🍌 за 2900₽",
]

# Repair bot/keyboards.py specifically if old script broke package list syntax.
p = Path("bot/keyboards.py")
if p.exists():
    s = p.read_text(encoding="utf-8")

    # If a packages list was injected inside imports/top-level incorrectly, remove the broken tuple-only block.
    s = re.sub(
        r'\n\s*\(15,\s*65,\s*"Мини"\),[\s\S]*?\(1000,\s*2900,\s*"Максимум"\),\s*\]\s*',
        '\n',
        s,
        count=1,
    )

    # Directly replace visible old button labels.
    replacements = {
        "🍌 Мини: 15🍌 за 150₽": LABELS[0],
        "🍌🍌 Стандарт: 30🍌 за 250₽": LABELS[1],
        "🍌🍌🍌 Оптимальный: 50🍌 за 400₽ 🔥": LABELS[2],
        "🍌🍌🍌🍌 Про: 100🍌 за 700₽": LABELS[3],
        "🍌🍌🍌🍌🍌 Студия: 200🍌 за 1400₽": LABELS[4],
    }
    for old, new in replacements.items():
        s = s.replace(old, new)

    # Patch old callback payload amounts/credits if they are embedded in callback_data.
    for old, new in [
        ("buy_15_150", "buy_15_65"),
        ("buy_30_250", "buy_25_90"),
        ("buy_50_400", "buy_50_160"),
        ("buy_100_700", "buy_100_310"),
        ("buy_200_1400", "buy_200_605"),
        ("pay_15_150", "pay_15_65"),
        ("pay_30_250", "pay_25_90"),
        ("pay_50_400", "pay_50_160"),
        ("pay_100_700", "pay_100_310"),
        ("pay_200_1400", "pay_200_605"),
    ]:
        s = s.replace(old, new)

    # If a list of payment buttons exists, replace its body conservatively by labels only when old labels are still present.
    p.write_text(s, encoding="utf-8")

# Patch remaining Python files: only simple safe replacements, no generic package-list regex.
for rel in ["bot/handlers/common.py", "bot/handlers/payment.py", "bot/handlers/payments.py", "bot/main.py", "bot/miniapp.py"]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s
    for old, new in {
        "15🍌 за 150₽": "15🍌 за 65₽",
        "30🍌 за 250₽": "25🍌 за 90₽",
        "50🍌 за 400₽": "50🍌 за 160₽",
        "100🍌 за 700₽": "100🍌 за 310₽",
        "200🍌 за 1400₽": "200🍌 за 605₽",
        "15 бананов = 150₽": "15 бананов = 65₽",
        "30 бананов = 250₽": "25 бананов = 90₽",
        "50 бананов = 400₽": "50 бананов = 160₽",
        "100 бананов = 700₽": "100 бананов = 310₽",
        "200 бананов = 1400₽": "200 бананов = 605₽",
    }.items():
        s = s.replace(old, new)
    if s != original:
        p.write_text(s, encoding="utf-8")

# Mini App simple safe replacements.
for rel in [
    "frontend/miniapp-v0/lib/api.ts",
    "frontend/miniapp-v0/lib/mock-data.ts",
    "frontend/miniapp-v0/components/balance-sheet.tsx",
    "frontend/miniapp-v0/components/payment-sheet.tsx",
    "frontend/miniapp-v0/components/workspace-sheet.tsx",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s
    for old, new in {
        "15🍌 за 150₽": "15🍌 за 65₽",
        "30🍌 за 250₽": "25🍌 за 90₽",
        "50🍌 за 400₽": "50🍌 за 160₽",
        "100🍌 за 700₽": "100🍌 за 310₽",
        "200🍌 за 1400₽": "200🍌 за 605₽",
        "amountRub: 150": "amountRub: 65",
        "amountRub: 250": "amountRub: 90",
        "amountRub: 400": "amountRub: 160",
        "amountRub: 700": "amountRub: 310",
        "amountRub: 1400": "amountRub: 605",
        "amount_rub: 150": "amount_rub: 65",
        "amount_rub: 250": "amount_rub: 90",
        "amount_rub: 400": "amount_rub: 160",
        "amount_rub: 700": "amount_rub: 310",
        "amount_rub: 1400": "amount_rub: 605",
    }.items():
        s = s.replace(old, new)
    if s != original:
        p.write_text(s, encoding="utf-8")

Path("bot/banana_packages.py").write_text(
    "BANANA_PACKAGES = [\n"
    "    {\"credits\": 15, \"amount_rub\": 65, \"title\": \"Мини\"},\n"
    "    {\"credits\": 25, \"amount_rub\": 90, \"title\": \"Старт\"},\n"
    "    {\"credits\": 50, \"amount_rub\": 160, \"title\": \"Оптимальный\"},\n"
    "    {\"credits\": 100, \"amount_rub\": 310, \"title\": \"Про\"},\n"
    "    {\"credits\": 200, \"amount_rub\": 605, \"title\": \"Студия\"},\n"
    "    {\"credits\": 500, \"amount_rub\": 1500, \"title\": \"Бизнес\"},\n"
    "    {\"credits\": 1000, \"amount_rub\": 2900, \"title\": \"Максимум\"},\n"
    "]\n"
    "VALUE_HINT = \"Чем больше 🍌 — тем дешевле генерация\"\n",
    encoding="utf-8",
)
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in ["bot/keyboards.py", "bot/handlers/common.py", "bot/miniapp.py", "bot/banana_packages.py"]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("Balance packages patched safely.")
PY

echo "Check: grep -R '150₽\|250₽\|400₽\|700₽\|1400₽\|65₽\|90₽\|160₽\|310₽\|605₽' -n bot frontend/miniapp-v0 | head -120"
