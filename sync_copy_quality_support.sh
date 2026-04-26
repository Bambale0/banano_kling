#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import json
import re

SUPPORT = "@only_tany"
SUPPORT_URL = "https://t.me/only_tany"

# support in bot + mini app
paths = list(Path("bot").rglob("*.py"))
paths += list(Path("frontend/miniapp-v0").rglob("*.ts"))
paths += list(Path("frontend/miniapp-v0").rglob("*.tsx"))
paths += [p for p in [Path("static/ofert.md"), Path("README.md")] if p.exists()]

old_supports = [
    "@chillcreative", "@ChillCreative", "@s_k7222", "@S_k7222",
    "@only_tm_ii", "@ai_neir_set", "@creative_support",
]
old_urls = [
    "https://t.me/chillcreative", "https://t.me/S_k7222", "https://t.me/s_k7222",
    "https://t.me/only_tm_ii", "https://t.me/ai_neir_set", "https://t.me/creative_support",
]

for p in paths:
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8", errors="ignore")
    original = s
    for old in old_supports:
        s = s.replace(old, SUPPORT)
    for old in old_urls:
        s = s.replace(old, SUPPORT_URL)
    if s != original:
        p.write_text(s, encoding="utf-8")

# quality pricing constants helper
Path("bot/quality_pricing.py").write_text(
    'QUALITY_COSTS = {"2k": 5, "2K": 5, "4k": 7, "4K": 7}\n'
    'DEFAULT_QUALITY = "2K"\n'
    'QUALITY_LABELS = {"2K": "2K качество — 5 🍌", "4K": "4K качество — 7 🍌"}\n',
    encoding="utf-8",
)
Path("bot/support_copy.py").write_text(
    'SUPPORT_USERNAME = "@only_tany"\nSUPPORT_URL = "https://t.me/only_tany"\n',
    encoding="utf-8",
)

# Patch obvious quality cost mappings in backend/frontend.
for p in list(Path("bot").rglob("*.py")) + list(Path("frontend/miniapp-v0").rglob("*.ts")) + list(Path("frontend/miniapp-v0").rglob("*.tsx")):
    s = p.read_text(encoding="utf-8", errors="ignore")
    original = s

    s = re.sub(r'(["\']2K["\']\s*:\s*)\d+', r'\g<1>5', s)
    s = re.sub(r'(["\']2k["\']\s*:\s*)\d+', r'\g<1>5', s)
    s = re.sub(r'(["\']4K["\']\s*:\s*)\d+', r'\g<1>7', s)
    s = re.sub(r'(["\']4k["\']\s*:\s*)\d+', r'\g<1>7', s)

    s = re.sub(r'(2K[^\n]{0,80}?)(\d+)\s*🍌', lambda m: m.group(1) + '5 🍌', s)
    s = re.sub(r'(4K[^\n]{0,80}?)(\d+)\s*🍌', lambda m: m.group(1) + '7 🍌', s)
    s = s.replace("2K качество", "2K качество")
    s = s.replace("4K качество", "4K качество")

    # common object pattern: quality/resolution then cost nearby
    s = re.sub(r'((?:quality|resolution|label|name)\s*[:=]\s*["\']2K["\'][\s\S]{0,160}?(?:cost|credits|price)\s*[:=]\s*)\d+', r'\g<1>5', s)
    s = re.sub(r'((?:quality|resolution|label|name)\s*[:=]\s*["\']4K["\'][\s\S]{0,160}?(?:cost|credits|price)\s*[:=]\s*)\d+', r'\g<1>7', s)

    if s != original:
        p.write_text(s, encoding="utf-8")

# Patch JSON-like price metadata if present.
for p in [Path("price.json"), Path("prices.json"), Path("bot/price.json"), Path("bot/prices.json"), Path("frontend/miniapp-v0/public/bootstrap.json")]:
    if not p.exists():
        continue
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        continue

    def walk(x):
        if isinstance(x, dict):
            joined = " ".join(str(x.get(k, "")) for k in ("id", "name", "label", "quality", "resolution"))
            low = joined.lower()
            if "2k" in low:
                for ck in ("cost", "credits", "price", "banana_cost"):
                    if isinstance(x.get(ck), (int, float)):
                        x[ck] = 5
            if "4k" in low:
                for ck in ("cost", "credits", "price", "banana_cost"):
                    if isinstance(x.get(ck), (int, float)):
                        x[ck] = 7
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

python3 - <<'PY'
from pathlib import Path
import py_compile
for rel in [
    "bot/handlers/common.py",
    "bot/handlers/generation.py",
    "bot/database.py",
    "bot/miniapp.py",
    "bot/keyboards.py",
    "bot/quality_pricing.py",
    "bot/support_copy.py",
]:
    p = Path(rel)
    if p.exists():
        py_compile.compile(str(p), doraise=True)
print("OK: support, quality pricing, and copy sync patch applied.")
PY

echo "Check support: grep -R '@chillcreative\|@S_k7222\|@s_k7222\|@only_tany' -n bot frontend/miniapp-v0 | head -80"
echo "Check mini app quality: grep -R '2K\|4K\|@only_tany' -n frontend/miniapp-v0 | head -120"
