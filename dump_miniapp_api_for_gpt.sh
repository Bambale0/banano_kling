#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$PROJECT_DIR/gpt_miniapp_api_${TS}.txt"

{
  echo "=== miniapp API dump ${TS} ==="
  cd "$APP_DIR"
  echo "PWD=$(pwd)"
  echo

  echo "=== lib/api.ts ==="
  if [ -f lib/api.ts ]; then
    sed -n '1,260p' lib/api.ts
  else
    echo "lib/api.ts not found"
  fi
  echo

  echo "=== lib/types.ts ==="
  if [ -f lib/types.ts ]; then
    sed -n '1,260p' lib/types.ts
  else
    echo "lib/types.ts not found"
  fi
  echo

  echo "=== lib/mock-data.ts ==="
  if [ -f lib/mock-data.ts ]; then
    sed -n '1,320p' lib/mock-data.ts
  else
    echo "lib/mock-data.ts not found"
  fi
  echo

  echo "=== current video form audio block ==="
  grep -nC 8 -E "audioReference|Аудио-референс|audio_reference|onUploadAudioReference" components/forms/video-generator-form.tsx components/tabs/video-tab.tsx || true
  echo

  echo "=== current motion model block ==="
  grep -nC 10 -E "motionModel|motion_control_v26|motion_control_v30|model: motionModel|generateMotion" components/tabs/motion-tab.tsx lib/api.ts || true

} > "$OUT" 2>&1

echo "$OUT"
