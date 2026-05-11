#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/root/2loop"
ENV_FILE="$PROJECT_ROOT/.env"
LOG_FILE="/var/log/2loop-watchdog.log"

log() {
  printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG_FILE"
}

restart_bot() {
  log "Restarting 2loop-bot.service: $*"
  systemctl restart 2loop-bot.service || log "Failed to restart 2loop-bot.service"
}

restart_nginx() {
  log "Restarting nginx: $*"
  nginx -t >> "$LOG_FILE" 2>&1 && systemctl restart nginx || log "Failed to restart nginx"
}

if [[ ! -f "$ENV_FILE" ]]; then
  log "Missing env file: $ENV_FILE"
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

WEBHOOK_URL="${WEBHOOK_HOST%/}${WEBHOOK_PATH:-/webhook}"
WEBHOOK_IP="${WEBHOOK_IP:-}"

log "watchdog start"

if systemctl is-active --quiet nginx; then
  log "nginx active"
else
  restart_nginx "service inactive"
fi

if systemctl is-active --quiet 2loop-bot.service; then
  log "2loop-bot.service active"
else
  restart_bot "service inactive"
fi

if curl -fsS --max-time 5 "http://127.0.0.1:${WEBHOOK_PORT:-8443}/api/miniapp/health" >/dev/null; then
  log "local health ok"
else
  restart_bot "local miniapp health failed"
  sleep 3
fi

if curl -fsS --max-time 8 "${WEBHOOK_HOST%/}/api/miniapp/health" >/dev/null; then
  log "external health ok"
else
  restart_nginx "external miniapp health failed"
fi

if [[ -n "${BOT_TOKEN:-}" && -n "${WEBHOOK_HOST:-}" ]]; then
  "$PROJECT_ROOT/venv/bin/python" - "$BOT_TOKEN" "$WEBHOOK_URL" "$WEBHOOK_IP" >> "$LOG_FILE" 2>&1 <<'PY'
import json
import sys
import urllib.parse
import urllib.request

token, expected_url, expected_ip = sys.argv[1], sys.argv[2], sys.argv[3]
base = f"https://api.telegram.org/bot{token}"


def post(method, data):
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{base}/{method}", data=encoded, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


info = post("getWebhookInfo", {})
result = info.get("result") or {}
current_url = result.get("url")
current_ip = result.get("ip_address") or ""
last_error = result.get("last_error_message")

needs_reset = current_url != expected_url or bool(last_error)
if expected_ip:
    needs_reset = needs_reset or current_ip != expected_ip

if needs_reset:
    data = {"url": expected_url, "drop_pending_updates": "false"}
    if expected_ip:
        data["ip_address"] = expected_ip
    reset = post("setWebhook", data)
    print(
        "webhook reset:",
        json.dumps(
            {
                "expected_url": expected_url,
                "previous_url": current_url,
                "expected_ip": expected_ip,
                "previous_ip": current_ip,
                "last_error": last_error,
                "result": reset.get("ok"),
            },
            ensure_ascii=False,
        ),
    )
else:
    print(
        "webhook ok:",
        json.dumps(
            {
                "url": current_url,
                "ip": current_ip,
                "pending_update_count": result.get("pending_update_count"),
            },
            ensure_ascii=False,
        ),
    )
PY
fi

log "watchdog ok"
