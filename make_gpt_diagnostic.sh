#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$PROJECT_DIR/gpt_${TS}.txt"

{
  echo "=== GPT DIAGNOSTIC ${TS} ==="
  echo "PWD=$(pwd)"
  echo

  echo "=== git ==="
  cd "$PROJECT_DIR"
  git rev-parse --abbrev-ref HEAD || true
  git rev-parse HEAD || true
  git status --short || true
  echo

  echo "=== root ignored lib rule ==="
  grep -nE '^lib/?$|/lib/?$|frontend/miniapp-v0/lib' "$PROJECT_DIR/.gitignore" || true
  echo

  echo "=== miniapp files ==="
  cd "$APP_DIR"
  find app components hooks lib -maxdepth 8 -type f 2>/dev/null | sort || true
  echo

  echo "=== likely UI/API strings ==="
  find app components hooks lib -type f 2>/dev/null \
    \( -name '*.tsx' -o -name '*.ts' -o -name '*.jsx' -o -name '*.js' \) \
    -print | xargs grep -niE "avatar|talk|lip|voice|sound|speech|audio|generate|video|motion|uploadFile|image_reference|video_reference|audio_reference|scenario|service|model" || true
  echo

  echo "=== lib content heads ==="
  find lib -maxdepth 4 -type f 2>/dev/null | sort | while read -r f; do
    echo "--- $f ---"
    sed -n '1,220p' "$f" || true
  done
  echo

  echo "=== route api files ==="
  find app -maxdepth 8 -type f 2>/dev/null | grep -E '/api/|route\.(ts|js)$' | sort | while read -r f; do
    echo "--- $f ---"
    sed -n '1,220p' "$f" || true
  done
  echo

  echo "=== backend avatar/motion endpoints/services ==="
  cd "$PROJECT_DIR"
  find bot -type f \( -name '*.py' \) -print | xargs grep -niE "avatar|talk|lip|voice|audio_reference|audio|motion_control|motion control|generate_motion|avatar_video" || true

} > "$OUT" 2>&1

echo "$OUT"
