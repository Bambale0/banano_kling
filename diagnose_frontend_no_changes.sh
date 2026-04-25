#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/frontend/miniapp-v0"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$PROJECT_DIR/gpt_frontend_no_changes_${TS}.txt"

{
  echo "=== Frontend no changes diagnostic $TS ==="
  echo
  cd "$PROJECT_DIR"
  echo "=== git ==="
  git branch --show-current || true
  git rev-parse HEAD || true
  git status --short || true
  echo

  echo "=== source audio markers ==="
  grep -Rni "Аудио-референс\|audioReference\|audio_reference" "$APP_DIR/components" "$APP_DIR/lib" 2>/dev/null || true
  echo

  echo "=== build audio markers ==="
  grep -Rni "Аудио-референс\|audioReference\|audio_reference" "$APP_DIR/.next" 2>/dev/null | head -80 || true
  echo

  echo "=== package/build scripts ==="
  cat "$APP_DIR/package.json" || true
  echo

  echo "=== running processes ==="
  ps auxww | grep -E "next|node|npm|pnpm|miniapp|mini-app|3000|3001" | grep -v grep || true
  echo

  echo "=== process cwd ==="
  for pid in $(pgrep -f "next|node|npm|pnpm" || true); do
    echo "--- PID $pid ---"
    ps -p "$pid" -o pid,ppid,cmd || true
    readlink -f "/proc/$pid/cwd" 2>/dev/null || true
  done
  echo

  echo "=== listening ports ==="
  ss -ltnp 2>/dev/null | grep -E "3000|3001|3002|8888|node|next" || true
  echo

  echo "=== systemd candidates ==="
  systemctl list-units --type=service --all 2>/dev/null | grep -Ei "mini|next|node|npm|pnpm|banano|kling" || true
  echo

  echo "=== nginx mini app routes ==="
  grep -Rni "mini-app\|miniapp\|3000\|3001\|frontend/miniapp" /etc/nginx 2>/dev/null || true
  echo

  echo "=== env/base path ==="
  find "$APP_DIR" -maxdepth 2 -name '.env*' -type f -print -exec sed -n '1,120p' {} \; 2>/dev/null || true

} > "$OUT" 2>&1

echo "$OUT"
