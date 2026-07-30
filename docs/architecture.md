# Architecture

## 1. Система в одном абзаце

`Banano Kling` — это один Python runtime на `aiohttp`, внутри которого живут:

- Telegram bot (`aiogram`)
- Mini App backend
- provider/payment webhooks
- internal read-only APIs
- фоновые reconcile/cleanup задачи

Система использует единый слой доменных данных (`bot/database.py` + `bot/db.py`), а поверх него построены Telegram handlers, Mini App handlers и provider/payment services.

Production frontend размещён отдельно на `tanyapp.chillcreative.ru`; `/mini-app/api/` проксируется на `tanyapi.chillcreative.ru`. Состояние, авторизация и права остаются на backend. Bootstrap — источник истины для истории генераций и синхронно обновляет список, выбранную задачу и открытую карточку. Временные media URL провайдеров проходят через авторизованный same-origin gateway с allowlist и локальным кешем.

Публикация в боте и Mini App использует одну модель: генерация имеет один scope `private`, `profile` или `feed`. `feed` включает общую ленту и профиль, `profile` показывает работу только владельцу профиля и его посетителям. Повторный вызов обновляет настройки той же записи; backend возвращает deep link для открытия и копирования.

## 2. Основные подсистемы

### 2.1 Bot runtime

Ключевой файл: `bot/main.py`

Отвечает за:

- инициализацию логирования
- загрузку env/config
- выбор FSM storage
- регистрацию routers
- регистрацию HTTP routes
- startup/shutdown hooks
- background loops:
  - payment reconciliation
  - memory dumps
  - DB backups
  - cleanup jobs

### 2.2 Telegram UI / FSM

Ключевые файлы:

- `bot/states.py`
- `bot/keyboards.py`
- `bot/handlers/common.py`
- `bot/handlers/generation.py`
- `bot/handlers/payments.py`
- `bot/handlers/admin.py`
- `bot/handlers/image_analyzer.py`
- `bot/handlers/batch_generation.py`
- `bot/handlers/support.py`

Архитектурный принцип:

`callback/message -> FSM state/data -> service/database call -> task/payment side effects -> user-facing response`

### 2.3 Mini App backend

Ключевой файл: `bot/miniapp.py`

Отвечает за:

- Telegram `initData` validation
- bootstrap payload для клиента
- upload handling
- image/video generation launch
- task details/history
- feed/prompt/profile APIs
- payment creation
- AI assistant entrypoint
- fallback static asset serving для локальной разработки и быстрого rollback

Mini App использует те же бизнес-таблицы и большую часть тех же сервисов, что и Telegram bot.

### 2.4 Services layer

Каталог: `bot/services/`

Главные группы сервисов:

- generation providers:
  - `kling_service.py`
  - `seedream_service.py`
  - `seedance_service.py`
  - `gpt_image_service.py`
  - `grok_service.py`
  - `veo_service.py`
  - `gemini_service.py`
  - `gemini_omni_service.py`
  - `nano_banana_*_service.py`
  - `wan27_service.py`
- supporting services:
  - `reference_storage_service.py`
  - `media_input_utils.py`
  - `image_analyzer_service.py`
  - `photo_prompt_service.py`
  - `video_prompt_service.py`
  - `ai_assistant_service.py`
  - `batch_service.py`
- payments/ops:
  - `cryptobot_service.py`
  - `lava_service.py`
  - `yookassa_service.py`
  - `task_watchdog.py`
  - `rate_limiter.py`
  - `redis_service.py`
  - `memory_dump_service.py`

### 2.5 Data layer

Ключевые файлы:

- `bot/database.py` — high-level async data operations
- `bot/db.py` — DB backend compatibility layer
- `schema_postgres.sql` — PostgreSQL schema reference

Фактическая модель:

- SQLite schema эволюционирует через `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE`
- PostgreSQL path поддерживается отдельной схемой и migration scripts
- runtime может работать через `DATABASE_URL`

## 3. Storage model

### Основные таблицы

- `users`
- `transactions`
- `generation_tasks`
- `generation_history`
- `user_settings`
- `bot_settings`
- `referrals`
- `partner_withdrawals`
- `promo_codes`
- `promo_redemptions`
- `user_prompts`
- `prompt_likes`
- `feed_generation_likes`
- `feed_remix_events`
- `prompt_repeat_events`
- `saved_references`
- `feed_comments`
- `batch_jobs`
- `miniapp_notifications`

### Доменные инварианты

- списание кредитов не должно происходить дважды за один task
- completed payment не должен повторно зачисляться
- feed/remix/share действия должны быть user-scoped
- task detail не должен раскрывать чужие задачи
- webhook processing должно быть безопасно к retry/dedup

## 4. HTTP surface

### Public runtime

- Telegram webhook
- provider webhooks
- payment webhooks
- `/health`
- Mini App routes and APIs

### Internal APIs

1. `/internal/v1/*`
   - HMAC auth
   - health/stats

2. `/internal/admin/*`
   - HMAC auth
   - IP allowlist
   - cursor pagination
   - read-only operational aggregates

## 5. Основные data flows

### 5.1 Telegram generation flow

1. Пользователь проходит FSM в `bot/handlers/generation.py`
2. Выбранные параметры пишутся в FSM data
3. Выполняется проверка баланса и допустимости input
4. Создаётся `generation_tasks`
5. Провайдерский сервис отправляет запрос
6. В БД сохраняется `task_id`, request snapshot и метаданные
7. Финал приходит через webhook или direct result
8. `generation_tasks` обновляется до `completed/failed`
9. Пользователь получает файл/ссылку и кнопки post-actions

### 5.2 Mini App generation flow

1. Client вызывает `bootstrap`
2. Backend валидирует Telegram `initData`
3. Client отправляет generation request
4. Используются те же DB/service primitives, что и у Telegram bot
5. Client опрашивает `task-detail` или получает обновления через history/bootstrap

### 5.3 Payment flow

1. Пользователь выбирает package
2. Создаётся `transactions`
3. Внешний payment provider выдаёт invoice/payment session
4. Webhook или provider poll подтверждает факт оплаты
5. Выполняется idempotent completion
6. Баланс пользователя увеличивается
7. Реферальные/partner side effects фиксируются отдельно

### 5.4 Feed / prompt library flow

1. Completed generation может быть опубликована в feed/library
2. На запись навешиваются likes/shares/remix/repeat events
3. Deep links формируются через `bot/miniapp_links.py`
4. Feed доступен в bot и Mini App

## 6. Frontend architecture

`frontend/miniapp-v0` — отдельный Next.js frontend, который:

- использует backend APIs из `bot/miniapp.py`
- может быть собран в static export
- в production обслуживается отдельным nginx host на `tanyapp.chillcreative.ru`
- проксирует API и uploads на backend `tanyapi.chillcreative.ru`

Сейчас это не отдельный Node backend: Node нужен для сборки, а production отдаёт статические файлы. Python runtime сохраняет local/fallback static serving, поэтому rollback не требует переноса backend. Источник истины по маршрутам и контрактам остаётся в Python backend.

Production topology и процедуры эксплуатации описаны в [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md).

## 7. Безопасность и операционные ограничения

- webhook signature verification реализована там, где провайдер это поддерживает
- internal APIs защищены HMAC, timestamp skew и allowlist rules
- Mini App backend валидирует Telegram `initData`
- секреты не должны логироваться
- FSM storage имеет fallback с Redis на in-memory
- в проекте есть backup/reconcile/watchdog loops, но они не заменяют внешнего мониторинга

## 8. Слабые места, которые важно помнить

- часть бизнес-логики исторически сосредоточена в крупных модулях (`bot/main.py`, `bot/miniapp.py`, `bot/database.py`)
- в репозитории много legacy/reference файлов, которые легко принять за актуальные
- SQLite и PostgreSQL paths сосуществуют; это полезно для миграции, но повышает сложность поддержки

## 9. Источники истины

- runtime wiring: `bot/main.py`
- Mini App contracts: `bot/miniapp.py`
- config/env surface: `bot/config.py`
- pricing/model aliases: `bot/services/preset_manager.py`, `data/price.json`
- keyboard labels / UI labels: `bot/keyboards.py`
- DB behavior: `bot/database.py`, `schema_postgres.sql`
- verification: `tests/`
