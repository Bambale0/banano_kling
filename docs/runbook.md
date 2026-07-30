# Runbook

## 1. Что именно запускается

Основной runtime — `python -m bot.main`.

Он поднимает:

- Telegram webhook server
- Mini App routes
- payment/provider webhooks
- internal APIs
- background reconcile/cleanup loops

Production Mini App развёрнут раздельно:

- frontend: `https://tanyapp.chillcreative.ru/mini-app/`, host `2.27.160.11`
- backend: `https://tanyapi.chillcreative.ru`, local aiohttp `127.0.0.1:1888`
- backend service: `banano-kling.service`

Полный frontend runbook: [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md).

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
curl http://127.0.0.1:1888/health
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

Прямой API smoke без `initData` обязан отвечать `401`. Это нормальная проверка proxy/auth boundary, а не признак поломки.

### Mini App долго загружается

Сначала разделить frontend и backend:

- document/JS/CSS: проверить DNS, TLS, HTTP/2, gzip и cache headers на `tanyapp.chillcreative.ru`
- лента Mini App обновляется при возврате в окно/приложение и каждые 15 секунд в видимом состоянии; API `/mini-app/api/feed` должен отдавать `Cache-Control: no-store`
- в remix-режиме кнопки «Причёска», «Одежда», «Фон», «Стиль» и «Детали» должны вставлять явную инструкцию в prompt, а не только менять подсветку
- видео-тренд хранит в tags выбранные автором `trend-scenario:<mode>` и `trend-duration:<seconds>`; повтор в Mini App обязан их подставить и не очищать опубликованные референсы
- видео-карточки ленты показывают первый кадр и сохраняют исходный aspect ratio ролика (9:16, 1:1, 16:9 и т. д.) как в сетке, так и в полном просмотре
- фото-карточка ленты всегда содержит `<img>`; не возвращать отложенную вставку DOM через `IntersectionObserver`, так как Telegram iOS может оставить видимые masonry-карточки пустыми
- в image remix запрошенная правка имеет приоритет над preservation: указанный атрибут обязан видимо измениться, а возврат неизменённого исходника считается некорректным результатом
- `bootstrap` и другие API: проверить proxy и время ответа `tanyapi.chillcreative.ru`
- hashed `/_next/static/` assets должны иметь `immutable`, HTML — `no-store`
- при бесконечном стартовом spinner проверить `404` на старые hashed chunks в nginx access log; frontend выкладывать без `rsync --delete`, сохраняя минимум две сборки на время Telegram WebView cache-overlap
- стартовая `Студия` должна входить в основной bundle; lazy-вкладки обязаны показывать skeleton fallback, а не оставлять пустой центр между header и нижней навигацией

### Результат пришёл в чат, но карточка всё ещё «В обработке»

- проверить, что bootstrap возвращает тот же `task_id` со статусом `completed` и `result_url`
- проверить 5-секундный bootstrap sync в видимой вкладке и повторный sync при возврате в приложение
- проверить Telegram `initData`; при `401` локальное состояние намеренно не подменяется
- убедиться, что свежая задача обновляет `recentTasks`, `selectedTask` и `taskDetail`

### В ленте или профиле чёрные карточки

- адрес результата должен быть переписан на `/mini-app/api/media/{task_id}/{index}`
- upstream host должен входить в allowlist media gateway
- backend должен иметь доступ к provider URL и право записи в `static/uploads/miniapp-media-cache`
- proxy `/mini-app/api/` на frontend host должен вести на `tanyapi.chillcreative.ru`

### Публикация из Mini App

Нормальный поток: одна кнопка в деталях → `Лента и профиль` либо `Только профиль` → настройки приватности → сохранение. `POST /mini-app/api/generations/share` возвращает `feed_item` с `publication_link`; повторный вызов обновляет существующую публикацию. Удаление должно убрать работу и из общей ленты, и из профиля.

В результате генерации бот всегда оставляет ровно одну кнопку `📤 Опубликовать`, даже если клавиатура повторно прошла через compatibility adapter при обновлении сообщения. Ссылка `Открыть работу в боте` сначала ищет пост в общей ленте, затем безопасно открывает ту же работу в профиле автора, если scope равен `profile`.

Команды замера и подробная диагностика: [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md#10-если-mini-app-долго-грузится).

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

1. Проверить `MINI_APP_URL=https://tanyapp.chillcreative.ru/mini-app/` и `MINI_APP_PATH`
2. Проверить TLS, frontend document и реальный hashed asset
3. Проверить `banano-miniapp`, `artflow-nginx-1` и `nginx -t` на frontend host
4. Проверить ожидаемый `401` от `bootstrap` без Telegram `initData`
5. Проверить авторизованные `bootstrap` и `task-detail` внутри Telegram
6. Если быстро исправить нельзя, выполнить rollback из frontend runbook

### Проверка TLS renewal frontend

```bash
ssh root@2.27.160.11 \
  'certbot renew --dry-run --cert-name tanyapp.chillcreative.ru --no-random-sleep-on-renew'
```

## 7. Scripts, которые полезны оператору

- `scripts/backup_db.sh`
- `scripts/check_postgres_runtime.py`
- `scripts/migrate_sqlite_to_postgres.py`
- `scripts/verify_postgres_migration.py`
- `scripts/poll_yookassa_pending.py`
- `scripts/redeliver_tasks.py`
- `scripts/watcher.py`

Перед запуском любого repair/migration script сначала читать [migration.md](migration.md).
