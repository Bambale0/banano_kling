#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/frontend/miniapp-v0" && pwd)"
cd "$APP_DIR"

echo "=== tracked/untracked files that may contain Avatar UI ==="
find app components hooks lib -maxdepth 6 -type f 2>/dev/null | sort | grep -Ev 'node_modules|\.next|\.bak' || true

echo

echo "=== routes/pages ==="
find app -maxdepth 6 -type f 2>/dev/null | sort || true

echo

echo "=== exported components/forms ==="
find components -maxdepth 6 -type f 2>/dev/null | sort || true

echo

echo "=== grep: generation/action names ==="
find app components hooks lib -type f 2>/dev/null \
  \( -name '*.tsx' -o -name '*.ts' -o -name '*.jsx' -o -name '*.js' \) \
  -print | xargs grep -niE "generate|video|motion|kling|scenario|service|model|uploadFile|image_reference|video_reference|audio_reference|audio" || true
