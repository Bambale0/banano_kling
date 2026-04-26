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

# 1) Patch keyboards/payment package source.
for rel in [
    "bot/keyboards.py",
    "bot/handlers/common.py",
    "bot/handlers/payment.py",
    "bot/handlers/payments.py",
    "bot/main.py",
    "bot/miniapp.py",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    # Replace old visible labels from screenshot.
    old_to_new = {
        "🍌 Мини: 15🍌 за 150₽": "🍌 Мини: 15🍌 за 65₽",
        "🍌🍌 Стандарт: 30🍌 за 250₽": "🍌 Старт: 25🍌 за 90₽",
        "🍌🍌🍌 Оптимальный: 50🍌 за 400₽ 🔥": "🍌🍌 Оптимальный: 50🍌 за 160₽ 🔥",
        "🍌🍌🍌🍌 Про: 100🍌 за 700₽": "🍌🍌🍌 Про: 100🍌 за 310₽",
        "🍌🍌🍌🍌🍌 Студия: 200🍌 за 1400₽": "🍌🍌🍌🍌 Студия: 200🍌 за 605₽",
    }
    for old, new in old_to_new.items():
        s = s.replace(old, new)

    # Replace common package tuple/list patterns.
    package_tuples = "[\n" + ",\n".join(
        f'        ({credits}, {rub}, "{name}"),' for credits, rub, name in PACKAGES
    ) + "\n    ]"
    package_dicts = "[\n" + ",\n".join(
        f'        {{"credits": {credits}, "amount_rub": {rub}, "price": {rub}, "title": "{name}"}},' for credits, rub, name in PACKAGES
    ) + "\n    ]"

    s = re.sub(r'(packages\s*=\s*)\[[\s\S]*?\]', r'\1' + package_tuples, s, count=1, flags=re.I)
    s = re.sub(r'(PAYMENT_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_dicts, s, count=1)
    s = re.sub(r'(BANANA_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_dicts, s, count=1)
    s = re.sub(r'(CREDIT_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_dicts, s, count=1)

    # If old amounts are hardcoded near old credit counts, patch directly.
    pairs = [(15,65),(25,90),(30,90),(50,160),(100,310),(200,605),(500,1500),(1000,2900)]
    for credits, rub in pairs:
        s = re.sub(rf'({credits}\s*🍌\s*за\s*)\d+\s*₽', rf'\g<1>{rub}₽', s)
        s = re.sub(rf'({credits}\s*банан\w*\s*[=:—-]\s*)\d+\s*₽', rf'\g<1>{rub}₽', s, flags=re.I)

    # Add/refresh value line.
    s = s.replace("Чем больше пакет, тем выгоднее цена за банан.", "Чем больше пакет, тем выгоднее цена за банан.")

    if s != original:
        p.write_text(s, encoding="utf-8")

# 2) Mini App package pricing.
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

    # visible labels
    s = s.replace("15🍌 за 150₽", "15🍌 за 65₽")
    s = s.replace("30🍌 за 250₽", "25🍌 за 90₽")
    s = s.replace("50🍌 за 400₽", "50🍌 за 160₽")
    s = s.replace("100🍌 за 700₽", "100🍌 за 310₽")
    s = s.replace("200🍌 за 1400₽", "200🍌 за 605₽")

    ts_packages = "[\n" + ",\n".join(
        f'  {{ credits: {credits}, amountRub: {rub}, amount_rub: {rub}, price: {rub}, title: "{name}" }},' for credits, rub, name in PACKAGES
    ) + "\n]"
    s = re.sub(r'(const\s+(?:packages|bananaPackages|paymentPackages|creditPackages)\s*=\s*)\[[\s\S]*?\]', r'\1' + ts_packages, s, count=1)

    if s != original:
        p.write_text(s, encoding="utf-8")

# 3) Canonical Python package file for future imports.
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
print("Balance packages patched.")
PY

echo "Check: grep -R '150₽\|250₽\|400₽\|700₽\|1400₽\|65₽\|90₽\|160₽\|310₽\|605₽' -n bot frontend/miniapp-v0 | head -120"
