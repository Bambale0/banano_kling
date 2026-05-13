#!/usr/bin/env bash
set -euo pipefail
cd /root/bot/banano_kling
mkdir -p logs static/uploads
source venv/bin/activate
exec python -m bot.main
