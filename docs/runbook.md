# Banano Kling Bot — Runbook

## Быстрый запуск (правильный способ)

```bash
# 1. Полная остановка
systemctl stop banano-kling.service

# 2. Убить всё, что могло остаться на порту
fuser -k 1888/tcp 2>/dev/null
sleep 1

# 3. Запуск
systemctl start banano-kling.service
```

## Проверка статуса

```bash
systemctl status banano-kling.service --no-pager
```

## Логи

```bash
# Логи приложения (файл)
tail -f /root/tanya/banano_kling/logs/bot.log

# Логи systemd
journalctl -u banano-kling.service --no-pager -n 50 -f
```

## Почему `systemctl restart` — ПЛОХАЯ ИДЕЯ

`systemctl restart` посылает SIGTERM старому процессу и сразу запускает новый, **не дожидаясь** освобождения порта 1888. Из-за этого:

1. Новый процесс падает с `[Errno 98] address already in use`
2. Systemd перезапускает его снова и снова
3. Telegram видит шквал API-запросов (set_my_commands, set_webhook, etc.)
4. Telegram включает **flood control** и блокирует бота на ~30 минут

**Всегда делай `stop` → жди → `start`.**

## Если Telegram flood control активен

Симптом: в логах `TelegramRetryAfter: Flood control exceeded... Retry in N seconds`.

Решение:
1. Остановить бота: `systemctl stop banano-kling.service`
2. Подождать ~30 минут (или сколько указано в логе `Retry in N seconds`)
3. Запустить снова: `systemctl start banano-kling.service`

Telegram API-вызовы `set_my_commands`, `set_my_short_description`, `setChatMenuButton` обёрнуты в `try/except` и при flood control **не роняют бота** — он стартует с ограниченным функционалом.

## Полная перезагрузка (сначала остановка, потом запуск)

```bash
cd /root/tanya/banano_kling
systemctl stop banano-kling.service
sleep 2
pkill -9 -f "bot.main" 2>/dev/null
fuser -k 1888/tcp 2>/dev/null
sleep 1
ss -tlnp | grep 1888 || echo "Port free"
systemctl start banano-kling.service
sleep 5
systemctl status banano-kling.service --no-pager
tail -20 logs/bot.log
```

## Зависимости

- **Python venv**: `/root/tanya/banano_kling/venv/`
- **Redis**: должен быть запущен (`redis-server`)
- **PostgreSQL**: должен быть доступен
- **Nginx**: проксирует webhook-запросы с `tanyapi.chillcreative.ru` на `127.0.0.1:1888`

## Конфигурация systemd

Файл: `/root/tanya/banano_kling/bot.service` → установлен в `/etc/systemd/system/banano-kling.service`

```ini
[Service]
Type=simple
User=root
WorkingDirectory=/root/tanya/banano_kling
EnvironmentFile=-/root/tanya/banano_kling/.env
EnvironmentFile=-/root/tanya/banano_kling/.env.postgres
ExecStart=/root/tanya/banano_kling/venv/bin/python -m bot.main
Restart=always
RestartSec=5
```

## Полезные команды

```bash
# Какой процесс держит порт
ss -tlnp | grep 1888

# Процессы бота
pgrep -af "bot.main"

# Перезагрузить конфиг systemd после изменений bot.service
systemctl daemon-reload

# Включить автозапуск при старте сервера
systemctl enable banano-kling.service