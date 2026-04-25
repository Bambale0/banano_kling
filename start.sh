#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && export $(grep -v '^#' .env | xargs) || true
mkdir -p logs
rm -f bot.pid
[ -f venv/bin/activate ] && source venv/bin/activate
nohup python -m bot.main >> logs/bot_output.log 2>&1 &
echo $! > bot.pid
sleep 2
kill -0 "$(cat bot.pid)" 2>/dev/null && echo "Bot started PID=$(cat bot.pid)" || (tail -100 logs/bot_output.log && exit 1)
