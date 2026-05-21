#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

install -m 0644 "${PROJECT_DIR}/bot.service" "${SYSTEMD_DIR}/bot.service"
install -m 0644 "${PROJECT_DIR}/bot-reloader.service" "${SYSTEMD_DIR}/bot-reloader.service"
install -m 0644 "${PROJECT_DIR}/bot-watchdog.service" "${SYSTEMD_DIR}/bot-watchdog.service"
chmod +x "${PROJECT_DIR}/scripts/run_bot_foreground.sh"
chmod +x "${PROJECT_DIR}/scripts/bot_watchdog.py"
chmod +x "${PROJECT_DIR}/scripts/code_reload_watchdog.py"

systemctl daemon-reload
systemctl enable bot.service
systemctl enable --now bot-reloader.service

echo "Installed systemd units:"
echo "  bot.service"
echo "  bot-reloader.service"
echo "  bot-watchdog.service"
echo
echo "Useful commands:"
echo "  systemctl status bot.service"
echo "  systemctl status bot-reloader.service"
echo "  journalctl -u bot-reloader.service -n 100 --no-pager"
echo "  python scripts/bot_watchdog.py --no-restart"
