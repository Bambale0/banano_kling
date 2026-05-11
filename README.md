# 2Loop Bot

Telegram-бот и веб-слой для 2Loop: AI-генерации изображений/видео, баланса GOE,
платежей, Telegram Mini App и магазина аксессуаров.

## Production

Текущий production-контур:

- домен: `https://2loop.chillcreative.ru`
- bot process: `2loop-bot.service`
- watchdog: `2loop-watchdog.timer`
- backend: `127.0.0.1:8443`
- Telegram webhook: `https://2loop.chillcreative.ru/webhook`
- YooKassa webhook: `https://2loop.chillcreative.ru/yookassa/webhook`
- YooKassa legacy alias: `https://2loop.chillcreative.ru/webhook/yookassa`
- Kie.ai webhook: `https://2loop.chillcreative.ru/webhook/kie_ai`
- Mini App / storefront: `https://2loop.chillcreative.ru/shop`
- Mini App API health: `https://2loop.chillcreative.ru/api/miniapp/health`

## Repository Layout

```text
bot/
  main.py                 aiohttp server, Telegram webhook, provider webhooks
  config.py               environment-based config
  database.py             SQLite schema, migrations, data access
  states.py               aiogram FSM states
  handlers/               Telegram flows
  services/               AI/payment/provider integrations
  miniapp_api.py          Telegram Mini App JSON API
  catalog_webapp.py       /shop storefront API built around catalog.xlsx

miniapp/                  React/Vite Telegram Mini App
static/                   local static assets
data/                     SQLite-adjacent JSON/Excel data
scripts/                  operational scripts
docs/                     project documentation
tests/                    pytest suite
```

## Documentation

- [Operations](docs/OPERATIONS.md): deploy, restart, logs, health checks.
- [Environment](docs/ENVIRONMENT.md): required env variables and webhook URLs.
- [Architecture](docs/ARCHITECTURE.md): components, data stores, request flow.
- [Project Audit](docs/PROJECT_AUDIT.md): current risks and cleanup notes.
- [Recommendations](docs/RECOMMENDATIONS.md): prioritized engineering roadmap.
- [UX Guide](docs/UX_GUIDE.md): message patterns, button rules, error wording.
- [YooKassa](docs/yookassa.md): payment setup and webhook behavior.

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cd miniapp
npm install
npm run build
```

Run backend locally:

```bash
source venv/bin/activate
python -m bot.main
```

The legacy `start.sh` and `stop.sh` scripts are kept only for local foreground/background
experiments. Production uses systemd directly.

## Production Commands

```bash
systemctl status 2loop-bot.service --no-pager
systemctl restart 2loop-bot.service
systemctl status 2loop-watchdog.timer --no-pager
journalctl -u 2loop-bot.service -n 100 --no-pager
tail -n 100 /var/log/2loop-watchdog.log
```

Deploy Mini App build:

```bash
cd /root/2loop/miniapp
npm run build
cp -a dist/. /root/2loop/static/miniapp/
cp -a dist/. /var/www/2loop/static/miniapp/
chown -R www-data:www-data /var/www/2loop/static/miniapp
```

## Cleanup Policy

One-off fix/setup scripts were removed from the repository. Operational scripts that remain:

- `scripts/2loop_watchdog.sh`
- `scripts/poll_yookassa_pending.py`
- `scripts/update_cloudflare_conf.sh`
- `set_webhook.py`

Do not commit secrets, `.env` backups, Playwright artifacts, `__pycache__`, or generated
test screenshots.
