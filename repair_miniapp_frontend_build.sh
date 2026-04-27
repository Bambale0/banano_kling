#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== Locate Mini App package.json =="
PKG=""
for d in frontend/miniapp-v0 frontend/miniapp frontend; do
  if [ -f "$d/package.json" ]; then
    PKG="$d"
    break
  fi
done

if [ -z "$PKG" ]; then
  PKG="$(find "$ROOT" -path '*/package.json' -not -path '*/node_modules/*' -print | grep -E '/frontend/|/miniapp' | head -1 | xargs -r dirname)"
fi

if [ -z "$PKG" ] || [ ! -f "$PKG/package.json" ]; then
  echo "ERROR: Не найден package.json для Mini App."
  echo "Покажи вывод: find $ROOT -name package.json -print"
  exit 1
fi

echo "Mini App dir: $PKG"
cd "$PKG"

echo "== Clean build dirs =="
rm -rf .next out node_modules/.cache

echo "== Install deps =="
if [ -f package-lock.json ]; then
  npm ci || npm install
else
  npm install
fi

echo "== Build =="
npm run build

cd "$ROOT"

echo "== Verify static out =="
if [ -d "$PKG/out" ]; then
  find "$PKG/out" -maxdepth 2 -type f | head -30
else
  echo "WARNING: out directory not found after build. Проверяем .next."
  find "$PKG/.next" -maxdepth 2 -type f | head -30 || true
fi

echo "== Check backend compile =="
python3 -m py_compile bot/miniapp.py bot/main.py bot/keyboards.py bot/handlers/common.py

echo "== Restart =="
./restart.sh

echo "OK: Mini App rebuilt/restarted. If Telegram still shows blank, close WebView fully and open again."
