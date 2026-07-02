#!/usr/bin/env bash
set -e
cd /root/tanya/banano_kling
source venv/bin/activate
exec python -m bot.main
