#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_DIR/compose.backend.yml}"
CONTAINER_NAME="${CONTAINER_NAME:-banano-kling-bot}"
EXPECTED_MINI_APP_URL="${MINI_APP_URL:-https://tanyapi.chillcreative.ru/mini-app/}"

log() {
    printf '[tanyapi-deploy] %s\n' "$*"
}

die() {
    printf '[tanyapi-deploy] ERROR: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash scripts/deploy_tanyapi_container.sh"
command -v docker >/dev/null 2>&1 || die "Docker is not installed"
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is not installed"
[ -f "$PROJECT_DIR/.env" ] || die "Missing $PROJECT_DIR/.env"
[ -f "$COMPOSE_FILE" ] || die "Missing $COMPOSE_FILE"

cd "$PROJECT_DIR"

# The production stack uses PostgreSQL variables from this optional file.
# Keeping an empty file makes the Compose definition compatible with older
# Compose v2 releases that do not support env_file.required.
if [ ! -f .env.postgres ]; then
    install -m 0600 /dev/null .env.postgres
fi

export MINI_APP_URL="$EXPECTED_MINI_APP_URL"

log "repo=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
log "docker=$(docker --version)"
log "compose=$(docker compose version --short 2>/dev/null || docker compose version)"
log "mini_app_url=$MINI_APP_URL"

log "Validating Compose configuration"
docker compose --project-directory "$PROJECT_DIR" -f "$COMPOSE_FILE" config --quiet

log "Building and deploying one image for the Telegram bot and Mini App"
bash "$PROJECT_DIR/scripts/deploy_backend_docker.sh" deploy

log "Verifying running container"
health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER_NAME")"
revision="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CONTAINER_NAME")"
runtime_mini_app_url="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER_NAME" | sed -n 's/^MINI_APP_URL=//p' | tail -n 1)"

printf 'container=%s\nhealth=%s\nrevision=%s\nmini_app_url=%s\n' \
    "$CONTAINER_NAME" "$health" "$revision" "$runtime_mini_app_url"

[ "$health" = "healthy" ] || die "Container is not healthy"
[ "$runtime_mini_app_url" = "$EXPECTED_MINI_APP_URL" ] \
    || die "Container uses an unexpected MINI_APP_URL"

docker exec -i "$CONTAINER_NAME" python - <<'PY'
from pathlib import Path

from bot.database import PARTNER_NEW_USER_BONUS
from bot.keyboards import get_main_menu_keyboard
from bot.services.photo_prompt_billing import photo_prompt_price_label

assert PARTNER_NEW_USER_BONUS == 5, PARTNER_NEW_USER_BONUS

button_texts = [
    button.text
    for row in get_main_menu_keyboard(5).inline_keyboard
    for button in row
]
assert "✍️ Промпт по описанию" in button_texts, button_texts
assert not any(text.startswith("✍️ Промпт по описанию •") for text in button_texts), button_texts

handler_text = Path("/app/bot/handlers/image_analyzer.py").read_text(encoding="utf-8")
assert "✍️ <b>Промпт по описанию</b>" in handler_text
assert "Стоимость анализа: <b>{photo_prompt_price_label()}</b>" in handler_text

miniapp_out = Path("/app/frontend/miniapp-v0/out")
assert (miniapp_out / "index.html").is_file()

print("runtime verification: ok")
print(f"welcome_bonus={PARTNER_NEW_USER_BONUS}")
print(f"photo_prompt_price={photo_prompt_price_label()}")
print("menu_button=✍️ Промпт по описанию")
print(f"miniapp_index={miniapp_out / 'index.html'}")
PY

log "Deployment and runtime verification completed"
