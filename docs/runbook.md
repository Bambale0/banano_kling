# Runbook

## 1. Что именно запускается

Основной runtime — `python -m bot.main`.

Он поднимает:

- Telegram webhook server
- Mini App routes
- payment/provider webhooks
- internal APIs
- background reconcile/cleanup loops

## 2. Перед запуском проверить

- `.env` загружен и содержит `BOT_TOKEN`
- `DATABASE_URL` указывает на корректный runtime backend
- Redis доступен, если ожидается FSM persistence
- `WEBHOOK_HOST` и `WEBHOOK_PATH` согласованы с внешним reverse proxy
- директория `logs/` доступна на запись

## 3. Базовые команды

### Локальный запуск

```bash
. venv/bin/activate
python -m bot.main
```

### Тесты

```bash
python -m pytest
python -m py_compile $(find bot tests scripts -name "*.py")
```

### Проверка health

```bash
curl http://127.0.0.1:8443/health
```

Если установлен `HEALTH_CHECK_SECRET`, нужен header:

```bash
Authorization: Bearer <secret>
```

## 4. Логи

По умолчанию runtime пишет в:

- `logs/bot.log`

Поведение логирования:

- file logging можно отключить через `BANANO_DISABLE_FILE_LOGGING=1`
- stdout logging можно включить через `BANANO_LOG_TO_STDOUT=1`

## 5. Частые проблемы

### Бот стартует, но FSM ведёт себя как будто без Redis

Причина:

- Redis storage недоступен, runtime переключился на in-memory fallback

Что проверить:

- `REDIS_URL`
- доступность Redis
- логи на тему `switching to in-memory FSM storage`

### Webhook приходит, но задача не закрывается

Что проверить:

- правильный route path из `bot/config.py`
- секреты/HMAC/signature headers
- наличие task в `generation_tasks`
- нет ли orphan webhook warnings

### Платёж застрял в pending

Что проверить:

- webhook logs
- reconcile loop logs
- provider-specific secret
- row в `transactions`

### Mini App открывается, но API отвечает 401

Причина:

- invalid/missing Telegram `initData`

Проверить:

- Mini App открыт из Telegram, а не прямой ссылкой в браузере
- время жизни Telegram session
- корректность Bot token

## 6. Incident checklist

### Если сломались генерации

1. Проверить `/health`
2. Проверить provider webhook paths
3. Проверить последние ошибки в `logs/bot.log`
4. Проверить, создаются ли новые rows в `generation_tasks`
5. Проверить, что provider keys доступны в env

### Если сломались платежи

1. Проверить текущий `PAYMENT_PROVIDER`
2. Проверить webhook signature logs
3. Проверить pending transactions
4. Проверить, идут ли reconcile ticks

### Если сломался Mini App

1. Проверить `MINI_APP_URL` и `MINI_APP_PATH`
2. Проверить, какой static frontend реально отдаётся
3. Проверить `bootstrap` и `task-detail` ответы

## 7. Scripts, которые полезны оператору

- `scripts/backup_db.sh`
- `scripts/check_postgres_runtime.py`
- `scripts/migrate_sqlite_to_postgres.py`
- `scripts/verify_postgres_migration.py`
- `scripts/poll_yookassa_pending.py`
- `scripts/redeliver_tasks.py`
- `scripts/watcher.py`

Перед запуском любого repair/migration script сначала читать [migration.md](migration.md).
