#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import json
import re

IMAGE_COSTS = {
    "nanobanana": 5,
    "banana_pro": 5,
    "banana_2": 5,
    "nano_banana": 5,
    "nano_banana_pro": 5,
    "nano_banana_2": 5,
    "seedream": 4,
    "seedream_edit": 4,
    "grok_imagine_i2i": 3,
    "grok": 3,
    "gpt_image_2": 5,
    "gpt_image": 5,
    "wan_27": 5,
    "wan": 5,
}

PACKAGES = [
    {"credits": 15, "amount_rub": 65},
    {"credits": 25, "amount_rub": 90},
    {"credits": 50, "amount_rub": 160},
    {"credits": 100, "amount_rub": 310},
    {"credits": 200, "amount_rub": 605},
    {"credits": 500, "amount_rub": 1500},
    {"credits": 1000, "amount_rub": 2900},
]

# 1) price/config JSON files
for rel in ["price.json", "prices.json", "bot/price.json", "bot/prices.json", "config/prices.json"]:
    p = Path(rel)
    if not p.exists():
        continue
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue

    def walk(obj):
        if isinstance(obj, dict):
            obj_id = str(obj.get("id") or obj.get("key") or obj.get("model") or obj.get("name") or "")
            for key, val in IMAGE_COSTS.items():
                if key in obj_id:
                    for cost_key in ("cost", "credits", "price", "banana_cost"):
                        if cost_key in obj and isinstance(obj[cost_key], (int, float)):
                            obj[cost_key] = val
            for k, v in list(obj.items()):
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(data)

    # common package fields
    for k in ("packages", "credit_packages", "banana_packages", "payment_packages", "tariffs"):
        if isinstance(data, dict) and k in data and isinstance(data[k], list):
            data[k] = PACKAGES

    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 2) Python source replacements for model costs and package lists
for rel in [
    "bot/services/preset_manager.py",
    "bot/miniapp.py",
    "bot/keyboards.py",
    "bot/handlers/common.py",
    "bot/handlers/generation.py",
    "bot/handlers/payment.py",
    "bot/handlers/payments.py",
    "bot/main.py",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    # explicit key/value costs in dicts
    for key, cost in IMAGE_COSTS.items():
        escaped = re.escape(key)
        s = re.sub(rf'(["\']{escaped}["\']\s*:\s*)\d+', rf'\g<1>{cost}', s)
        s = re.sub(rf'(["\']id["\']\s*:\s*["\']{escaped}["\'][\s\S]{{0,220}}?["\']cost["\']\s*:\s*)\d+', rf'\g<1>{cost}', s)
        s = re.sub(rf'(id\s*:\s*["\']{escaped}["\'][\s\S]{{0,220}}?cost\s*:\s*)\d+', rf'\g<1>{cost}', s)

    # payment package tuple/list replacements when obvious
    package_block_py = "[\n" + ",\n".join(
        f"    {{'credits': {x['credits']}, 'amount_rub': {x['amount_rub']}}}" for x in PACKAGES
    ) + "\n]"
    package_block_jsonish = "[\n" + ",\n".join(
        f"        {{\"credits\": {x['credits']}, \"amount_rub\": {x['amount_rub']}}}" for x in PACKAGES
    ) + "\n    ]"

    s = re.sub(r'(BANANA_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_block_py, s, flags=re.S)
    s = re.sub(r'(CREDIT_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_block_py, s, flags=re.S)
    s = re.sub(r'(PAYMENT_PACKAGES\s*=\s*)\[[\s\S]*?\]', r'\1' + package_block_py, s, flags=re.S)

    # update visible package text buttons like 15 бананов / 65₽ where present
    replacements = {
        r'15\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '15 бананов — 65₽',
        r'25\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '25 бананов — 90₽',
        r'50\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '50 бананов — 160₽',
        r'100\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '100 бананов — 310₽',
        r'200\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '200 бананов — 605₽',
        r'500\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '500 бананов — 1500₽',
        r'1000\s*банан\w*\s*[—\-:]\s*\d+\s*₽': '1000 бананов — 2900₽',
    }
    for pat, repl in replacements.items():
        s = re.sub(pat, repl, s, flags=re.I)

    if s != original:
        p.write_text(s, encoding="utf-8")

# 3) Frontend Mini App model costs and package lists
for rel in [
    "frontend/miniapp-v0/lib/api.ts",
    "frontend/miniapp-v0/lib/mock-data.ts",
    "frontend/miniapp-v0/components/balance-sheet.tsx",
    "frontend/miniapp-v0/components/payment-sheet.tsx",
    "frontend/miniapp-v0/components/forms/image-generator-form.tsx",
    "frontend/miniapp-v0/components/forms/video-generator-form.tsx",
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    for key, cost in IMAGE_COSTS.items():
        escaped = re.escape(key)
        s = re.sub(rf'(id\s*:\s*["\']{escaped}["\'][\s\S]{{0,220}}?cost\s*:\s*)\d+', rf'\g<1>{cost}', s)
        s = re.sub(rf'(["\']{escaped}["\']\s*:\s*)\d+', rf'\g<1>{cost}', s)

    # Replace common package arrays if named.
    ts_packages = "[\n" + ",\n".join(
        f"  {{ credits: {x['credits']}, amountRub: {x['amount_rub']}, amount_rub: {x['amount_rub']} }}" for x in PACKAGES
    ) + "\n]"
    s = re.sub(r'(const\s+(?:bananaPackages|creditPackages|paymentPackages|packages)\s*=\s*)\[[\s\S]*?\]', r'\1' + ts_packages, s, flags=re.S)

    if s != original:
        p.write_text(s, encoding="utf-8")

# 4) Add a canonical pricing file for future reference.
Path("bot/pricing_final.py").write_text(
    "BANANA_RUB_BASE = 3\n"
    "IMAGE_MODEL_COSTS = " + repr(IMAGE_COSTS) + "\n"
    "BANANA_PACKAGES = " + repr(PACKAGES) + "\n",
    encoding="utf-8",
)
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in [
    "bot/services/preset_manager.py",
    "bot/miniapp.py",
    "bot/keyboards.py",
    "bot/handlers/common.py",
    "bot/handlers/generation.py",
    "bot/main.py",
    "bot/pricing_final.py",
]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("Pricing patch applied and Python files compile.")
PY

echo "Check with: grep -R '15 бананов\|65₽\|banana_pro\|seedream\|grok_imagine_i2i\|wan_27' -n bot frontend/miniapp-v0 | head -120"
