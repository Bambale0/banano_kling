#!/usr/bin/env bash
set -Eeuo pipefail

MAIN="bot/main.py"

echo "[fix] checking $MAIN"

if [[ ! -f "$MAIN" ]]; then
  echo "bot/main.py not found"
  exit 1
fi

cp "$MAIN" "$MAIN.bak.webhook.$(date +%s)"

python3 - <<'PY'
from pathlib import Path

p = Path("bot/main.py")
s = p.read_text(encoding="utf-8")

# Ensure miniapp import exists only if miniapp file exists.
if "from bot.miniapp_api import setup_miniapp_routes" not in s and Path("bot/miniapp_api.py").exists():
    marker = "from bot.services.preset_manager import preset_manager\n"
    if marker in s:
        s = s.replace(marker, marker + "from bot.miniapp_api import setup_miniapp_routes\n", 1)

# Find app creation.
markers = [
    "app = web.Application()\n",
    "app = web.Application(client_max_size=1024**3)\n",
    "app = web.Application(client_max_size=1024 * 1024 * 1024)\n",
]

found = None
for m in markers:
    if m in s:
        found = m
        break

if not found:
    raise SystemExit("Could not find app = web.Application(...) in bot/main.py")

# Add explicit webhook route after app creation if it is missing.
if 'app.router.add_post(config.WEBHOOK_PATH, lambda request: handle_telegram_webhook(request, bot, dp))' not in s and 'handle_telegram_webhook(request, bot, dp)' not in s:
    injection = (
        found
        + "    app.router.add_post(config.WEBHOOK_PATH, lambda request: handle_telegram_webhook(request, bot, dp))\n"
        + "    app.router.add_post('/webhook', lambda request: handle_telegram_webhook(request, bot, dp))\n"
    )
    s = s.replace(found, injection, 1)

# Add miniapp routes after app creation if missing.
if "setup_miniapp_routes(app)" not in s and Path("bot/miniapp_api.py").exists():
    marker = "app.router.add_post(config.WEBHOOK_PATH, lambda request: handle_telegram_webhook(request, bot, dp))\n"
    if marker in s:
        s = s.replace(marker, marker + "    setup_miniapp_routes(app)\n", 1)
    else:
        s = s.replace(found, found + "    setup_miniapp_routes(app)\n", 1)

# Static route: guard against duplicate route registration.
if "add_static(\"/static/\"" not in s and "add_static('/static/'" not in s:
    marker = "setup_miniapp_routes(app)\n"
    if marker in s:
        s = s.replace(marker, marker + "    app.router.add_static('/static/', path='static', name='static')\n", 1)

p.write_text(s, encoding="utf-8")
print("patched bot/main.py")
PY

python3 -m py_compile bot/main.py
echo "[fix] compile OK"
echo "[fix] restart bot now: ./stop.sh && ./start.sh"
