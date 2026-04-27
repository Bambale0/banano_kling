#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path

files = [
    Path("bot/keyboards.py"),
    Path("bot/handlers/common.py"),
    Path("bot/miniapp.py"),
]

for p in files:
    if not p.exists():
        continue
    s = p.read_text(encoding="utf-8")
    original = s

    lines = []
    for line in s.splitlines(True):
        low = line.lower()
        if "промпт-канал" in low or "prompt channel" in low or "only_tm_ii" in low:
            continue
        lines.append(line)
    s = "".join(lines)

    if s != original:
        p.write_text(s, encoding="utf-8")
        print(f"updated {p}")

PY

python3 -m py_compile bot/keyboards.py bot/handlers/common.py bot/miniapp.py

echo "OK: prompt channel removed. Restart: ./restart.sh"
