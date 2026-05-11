# Operations

This document describes the current production setup for `2loop.chillcreative.ru`.

## Services

### Bot

Systemd unit:

```text
/etc/systemd/system/2loop-bot.service
```

Important fields:

```text
WorkingDirectory=/root/2loop
EnvironmentFile=/root/2loop/.env
ExecStart=/root/2loop/venv/bin/python -m bot.main
```

Commands:

```bash
systemctl status 2loop-bot.service --no-pager
systemctl restart 2loop-bot.service
journalctl -u 2loop-bot.service -n 100 --no-pager
```

### Watchdog

Systemd units:

```text
/etc/systemd/system/2loop-watchdog.service
/etc/systemd/system/2loop-watchdog.timer
```

The timer runs every minute and checks:

- nginx service state;
- bot service state;
- local Mini App API health;
- external Mini App API health;
- Telegram webhook URL/IP and last error.

Logs:

```bash
tail -n 100 /var/log/2loop-watchdog.log
```

### Nginx

Active site:

```text
/etc/nginx/sites-available/2loop.chillcreative.ru
```

Important locations:

```text
/webhook             -> http://127.0.0.1:8443/webhook
/webhook/            -> http://127.0.0.1:8443/webhook/
/yookassa/webhook    -> http://127.0.0.1:8443/yookassa/webhook
/webhook/yookassa    -> http://127.0.0.1:8443/webhook/yookassa
/robokassa/          -> http://127.0.0.1:8443/robokassa/
/api/miniapp/        -> http://127.0.0.1:8443/api/miniapp/
/static/             -> /var/www/2loop/static/
/uploads/            -> /var/www/2loop/static/uploads/
/                     -> /var/www/2loop/static/miniapp/index.html
```

Check and reload:

```bash
nginx -t
systemctl reload nginx
```

## Health Checks

```bash
curl -fsS http://127.0.0.1:8443/api/miniapp/health
curl -fsS https://2loop.chillcreative.ru/api/miniapp/health
curl -fsS http://127.0.0.1:8443/health
```

Expected response:

```json
{"ok": true, "service": "2loop-miniapp"}
```

## Deploy Backend Changes

```bash
cd /root/2loop
venv/bin/python -m py_compile bot/main.py bot/config.py bot/handlers/*.py bot/services/*.py
systemctl restart 2loop-bot.service
```

Then verify:

```bash
systemctl is-active 2loop-bot.service
curl -fsS http://127.0.0.1:8443/api/miniapp/health
journalctl -u 2loop-bot.service -n 50 --no-pager
```

## Database

Main SQLite database:

```text
/root/2loop/bot.db
```

Mini App JSON data:

```text
/root/2loop/data/products.json
/root/2loop/data/orders.json
/root/2loop/data/settings.json
```

Quick backup before risky work:

```bash
cd /root/2loop
sqlite3 bot.db 'pragma integrity_check;'
cp bot.db "bot.db.$(date +%Y%m%d-%H%M%S).bak"
cp -a data "data.$(date +%Y%m%d-%H%M%S).bak"
```

Do not use `/root/2loop/data/bot.db` unless `DATABASE_PATH` was explicitly changed. The
current code defaults to `/root/2loop/bot.db`.

## Deploy Mini App Changes

```bash
cd /root/2loop/miniapp
npm run build
cp -a dist/. /root/2loop/static/miniapp/
cp -a dist/. /var/www/2loop/static/miniapp/
chown -R www-data:www-data /var/www/2loop/static/miniapp
```

No bot restart is required for pure frontend changes.

## Payment Webhooks

YooKassa URL to configure in the YooKassa dashboard:

```text
https://2loop.chillcreative.ru/yookassa/webhook
```

Subscribe at least to:

```text
payment.succeeded
payment.canceled
```

The code verifies YooKassa webhooks by fetching the payment from YooKassa before crediting
the user.

## Static Uploads

AI input/output URLs under `/uploads/...` must resolve to real files, not the Mini App HTML.

Check example:

```bash
curl -I https://2loop.chillcreative.ru/uploads/YYYYMMDD/file.jpg
```

Expected content type: `image/*` or `video/*`.

Mini App product images are stored under:

```text
/var/www/2loop/static/uploads/2loop/
```

and returned as:

```text
/static/uploads/2loop/<filename>
```

## Cleanup

Safe cleanup:

```bash
find /root/2loop -name '__pycache__' -type d -prune -exec rm -rf {} +
find /root/2loop -name '*.pyc' -type f -delete
rm -f /root/2loop/logs/*.log
```

Do not delete:

- `/root/2loop/.env`
- `/root/2loop/data`
- `/var/www/2loop/static/uploads`
- active systemd unit files
- active nginx site config
