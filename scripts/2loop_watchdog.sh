#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/root/2loop"
ENV_FILE="$PROJECT_ROOT/.env"
LOG_FILE="/var/log/2loop-watchdog.log"
LOCK_FILE="/tmp/2loop-watchdog.lock"

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

restart_redis() {
  log "Restarting Redis: $*"
  if systemctl list-unit-files --no-pager 2>/dev/null | grep -q '^redis-server\.service'; then
    systemctl restart redis-server.service || log "Failed to restart redis-server.service"
  elif systemctl list-unit-files --no-pager 2>/dev/null | grep -q '^redis\.service'; then
    systemctl restart redis.service || log "Failed to restart redis.service"
  else
    log "Redis systemd unit not found"
  fi
}

restart_postgres() {
  log "Restarting PostgreSQL: $*"
  if systemctl list-unit-files --no-pager 2>/dev/null | grep -q '^postgresql\.service'; then
    systemctl restart postgresql.service || log "Failed to restart postgresql.service"
  else
    log "PostgreSQL systemd unit not found"
  fi
}

check_http() {
  local label="$1"
  local url="$2"
  local timeout="${3:-5}"

  if curl -fsS --max-time "$timeout" "$url" >/dev/null; then
    log "$label ok"
    return 0
  fi

  log "$label failed: $url"
  return 1
}

check_redis() {
  if [[ -z "${REDIS_URL:-}" ]]; then
    log "Redis check skipped: REDIS_URL is empty"
    return 1
  fi

  if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli -u "$REDIS_URL" ping 2>> "$LOG_FILE" | grep -q '^PONG$'; then
      log "redis ok"
      return 0
    fi
  else
    log "redis-cli not found"
  fi

  restart_redis "redis ping failed"
  sleep 2

  if command -v redis-cli >/dev/null 2>&1 && redis-cli -u "$REDIS_URL" ping 2>> "$LOG_FILE" | grep -q '^PONG$'; then
    log "redis ok after restart"
    return 0
  fi

  log "redis still failing after restart"
  restart_bot "redis unavailable"
  return 1
}

check_postgres() {
  if [[ -z "${POSTGRES_DSN:-}" ]]; then
    log "PostgreSQL check skipped: POSTGRES_DSN is empty"
    return 1
  fi

  if command -v pg_isready >/dev/null 2>&1 && pg_isready -d "$POSTGRES_DSN" >/dev/null 2>> "$LOG_FILE"; then
    log "postgres ok"
    return 0
  fi

  if "$PROJECT_ROOT/venv/bin/python" - >> "$LOG_FILE" 2>&1 <<'PY'
import asyncio
import os
import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["POSTGRES_DSN"])
    try:
        await conn.fetchval("select 1")
    finally:
        await conn.close()


asyncio.run(main())
PY
  then
    log "postgres ok"
    return 0
  fi

  restart_postgres "postgres connectivity failed"
  sleep 3

  if command -v pg_isready >/dev/null 2>&1 && pg_isready -d "$POSTGRES_DSN" >/dev/null 2>> "$LOG_FILE"; then
    log "postgres ok after restart"
    return 0
  fi

  log "postgres still failing after restart"
  restart_bot "postgres unavailable"
  return 1
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "watchdog already running, skip"
  exit 0
fi

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

check_redis || true
check_postgres || true

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

if ! check_http "local app health" "http://127.0.0.1:${WEBHOOK_PORT:-8443}/health" 5; then
  restart_bot "local app health failed"
  sleep 3
fi

if ! check_http "local miniapp health" "http://127.0.0.1:${WEBHOOK_PORT:-8443}/api/miniapp/health" 5; then
  restart_bot "local miniapp health failed"
  sleep 3
fi

if ! check_http "external miniapp health" "${WEBHOOK_HOST%/}/api/miniapp/health" 8; then
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
last_error_date = result.get("last_error_date")

needs_reset = current_url != expected_url
if expected_ip:
    needs_reset = needs_reset or current_ip != expected_ip

if last_error:
    print(
        "webhook last_error observed:",
        json.dumps(
            {
                "url": current_url,
                "ip": current_ip,
                "last_error": last_error,
                "last_error_date": last_error_date,
            },
            ensure_ascii=False,
        ),
    )

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
