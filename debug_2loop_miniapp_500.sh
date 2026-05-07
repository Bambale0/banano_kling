#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="${TWOLOOP_DOMAIN:-2loop.chillcreative.ru}"
BACKEND_PORT="${TWOLOOP_BACKEND_PORT:-8444}"

log() { printf '\033[1;36m[2loop-debug]\033[0m %s\n' "$*"; }

log "Testing public Mini App frontend"
curl -k -i "https://$DOMAIN/" | sed -n '1,20p' || true

echo
log "Testing public API health"
curl -k -i "https://$DOMAIN/api/miniapp/health" || true

echo
log "Testing local API health"
curl -i "http://127.0.0.1:$BACKEND_PORT/api/miniapp/health" || true

echo
log "Testing local products endpoint"
curl -i "http://127.0.0.1:$BACKEND_PORT/api/miniapp/products" || true

echo
log "Testing local settings endpoint"
curl -i "http://127.0.0.1:$BACKEND_PORT/api/miniapp/settings" || true

echo
log "Testing direct static miniapp files"
ls -lah static/miniapp || true

echo
log "Recent app log errors"
if [[ -f logs/bot.log ]]; then
  tail -n 160 logs/bot.log | grep -iE "miniapp|api/miniapp|traceback|exception|error|500|aiohttp" || true
else
  echo "logs/bot.log not found"
fi

echo
log "Nginx error log tail"
if [[ -f /var/log/nginx/error.log ]]; then
  tail -n 80 /var/log/nginx/error.log || true
fi

echo
log "Done"
