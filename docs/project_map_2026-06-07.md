# Карта проекта Banano Kling

Дата анализа: 2026-06-07.

## 1. Резюме

`Banano Kling AI Bot` - production Telegram-бот на Aiogram 3.x для генерации AI-изображений и AI-видео. Проект работает как монолитный Python-процесс: Telegram dispatcher, aiohttp webhook server, provider callbacks, платежи, подписки, партнерка, админка, фоновые задачи и хранение состояния находятся в одном приложении.

Проектная метка: `Boom`. Канонический рабочий путь: `/root/bot/banano_kling`. Пользовательский алиас в переписке: `/root/bot/banana_kling`.

Система функционально зрелая: есть мультипровайдерная генерация, BoomCoin-баланс, подписки, T-Bank/Crypto Bot, промокоды, реферальная и партнерская программа, админ-панель, ИИ-админ, публичная лента, фоновые push-сценарии, авто-продление подписок, health endpoint, systemd/watchdog и набор regression-тестов.

Главный архитектурный риск - концентрация сложности в нескольких крупных файлах:

- `bot/handlers/generation.py` - 8056 строк, основной UX генерации и provider-specific ветки.
- `bot/database.py` - 3374 строки, схема, миграции, users, payments, credits, partner, subscriptions, feed, history.
- `bot/main.py` - 2079 строк, entrypoint, aiohttp server и provider webhook controllers.
- `bot/handlers/common.py` - 2292 строки, меню, партнерка, GPT 5.5, Motion Control, AI assistant.

Текущее состояние тестов: `195 passed in 27.47s`.

## 2. Стек

- Python 3.10+.
- Aiogram 3.x.
- aiohttp для Telegram/payment/provider webhook server.
- SQLite через `aiosqlite` как основной runtime storage.
- Redis опционально для idempotency, locks и rate counters.
- asyncpg и SQL-миграции под будущий PostgreSQL.
- Systemd services: основной бот, reloader, watchdog.
- Конфигурация через `.env` и `bot/config.py`.

## 3. Точки входа

### Runtime

Основной запуск:

```bash
python -m bot.main
```

Production-обвязка:

- `scripts/run_bot_foreground.sh` - foreground start для systemd.
- `bot.service` - основной unit.
- `bot-reloader.service` - watcher изменений кода и `.env`.
- `bot-watchdog.service` и `scripts/bot_watchdog.py` - health monitoring.
- `start.sh` / `stop.sh` - локальные helper-скрипты.

### HTTP routes

В webhook mode `bot/main.py` поднимает aiohttp:

- `POST {WEBHOOK_PATH}` - Telegram webhook.
- `POST /tbank/webhook` - T-Bank notifications.
- `POST /cryptobot/webhook` - Crypto Bot notifications.
- `POST /webhook/kling` - Kling/PiAPI/Kie-compatible callbacks.
- `POST {KIE_AI_WEBHOOK_PATH}` - Kie.ai callbacks.
- `POST /webhook/veo` - Veo callbacks.
- `GET /health` - health check.
- `GET /uploads/...` - static uploads/results.

AI webhooks защищаются `AI_WEBHOOK_SECRET`, который принимается через query `secret`, headers `x-webhook-secret`/`x-ai-webhook-secret` или bearer token. Если секрет не задан, callbacks принимаются без подписи, что допустимо только для dev.

## 4. Карта модулей

### Ядро

| Файл | Назначение |
|---|---|
| `bot/main.py` | App bootstrap, Aiogram dispatcher, aiohttp routes, Telegram/provider webhooks, background loops |
| `bot/config.py` | Env config, derived webhook/payment URLs, provider flags |
| `bot/database.py` | SQLite schema/migrations and data access for users, credits, payments, tasks, feed, subscriptions, partner |
| `bot/states.py` | FSM states for generation, payments, partner withdrawal, admin, batch, image analyzer |
| `bot/keyboards.py` | Inline keyboard builders |
| `bot/image_models.py` | Image model registry, aliases, options, defaults |
| `bot/video_models.py` | Video model registry by scenario type, options, defaults |

### Handlers

| Файл | Возможности |
|---|---|
| `bot/handlers/common.py` | `/start`, help, main menu, balance, settings, partner/referral UI, GPT 5.5, Motion Control, AI assistant |
| `bot/handlers/generation.py` | Main image/video generation flows, references, model/options selection, feed retry, Gemini Omni helpers |
| `bot/handlers/batch_generation.py` | Batch edit/generation, batch status and downloads |
| `bot/handlers/image_analyzer.py` | Photo-to-prompt flow |
| `bot/handlers/feed.py` | Public feed: list, like, share, retry |
| `bot/handlers/payments.py` | Top up, subscriptions, recurring consent, promo input, payment checking, payment webhooks |
| `bot/handlers/admin.py` | Admin panel, stats, users, balance adjustments, prices, promo, broadcast, ban/maintenance, AI admin |
| `bot/handlers/admin_packages.py` | Runtime editing of payment/subscription packages |
| `bot/handlers/admin_referral_tools.py` | Referral/partner settings, anti-fraud toggles, payout overview |
| `bot/handlers/admin_push_scenarios.py` | Admin UI for automated push scenarios |

### Services

| Группа | Файлы |
|---|---|
| Image providers | `nano_banana_pro_service.py`, `nano_banana_2_service.py`, `gpt_image_service.py`, `grok_service.py`, `seedream_service.py`, `ideogram_service.py`, `gemini_service.py` |
| Video providers | `kling_service.py`, `gemini_omni_service.py`, `runway_service.py`, `veo_service.py`, `hailuo_service.py`, `happyhorse_service.py`, `aleph_service.py` |
| Payments | `tbank_service.py`, `cryptobot_service.py`, `jump_finance_service.py`, `recurring_service.py` |
| Product/business | `preset_manager.py`, `subscription_service.py`, `admin_config_service.py`, `referral_admin_config.py`, `push_scenario_service.py`, `push_scenario_dispatcher.py` |
| Reliability/storage | `redis_service.py`, `reliability.py`, `generation_guard.py`, `storage_policy.py` |
| Assistants | `gpt55_service.py`, `ai_assistant_service.py`, `admin_ai_service.py`, `image_analyzer_service.py` |

## 5. Карта возможностей

### Пользователь

- Главное меню и быстрый старт через `/start`.
- Помощь через `/help`.
- Баланс BoomCoin.
- Пополнение баланса.
- Покупка подписок.
- Промокоды.
- Настройки моделей/режимов.
- История генераций.
- Лента публичных работ через `/feed`.
- Реферальная программа через `/ref`.
- Партнерская программа через `/earn`.
- GPT 5.5 чат/помощник.
- Улучшение промпта.
- Фото -> промпт.
- Motion Control.
- AI assistant внутри бота.

### Генерация изображений

Поддерживаемые image-модели по реестру:

- Banana Pro.
- Banana 2.
- GPT Image 2.
- Grok Imagine T2I.
- Grok Image-to-Image.
- Seedream 5.0 Lite.
- Seedream 4.5 Edit.
- Ideogram Character.

Сценарии:

- text -> image;
- image/reference + text -> image;
- несколько reference images;
- face preservation modes;
- batch edit;
- retry из ленты.

### Генерация видео

Поддерживаемые video-сценарии:

- text -> video;
- image + text -> video;
- video + text -> video;
- reference-to-video;
- Motion Control;
- Gemini Omni multimodal flow.

Основные модели:

- Gemini Omni.
- Kling 3 Std/Pro.
- Seedance 2.0.
- Runway.
- Grok Imagine.
- Veo 3.1 Fast/Pro/Lite.
- Hailuo 2.3/02.
- HappyHorse T2V/I2V/Ref2V/Edit.
- Wan 2.7.
- Aleph Video.
- Kling Glow.

### Монетизация

- Внутренняя валюта BoomCoin.
- Разовые пакеты BoomCoin.
- Подписки: `try24`, `week`, `boom`, `pro`, `studio`.
- Image/video лимиты подписки.
- Includes Pro / priority flags.
- Доплаты через BoomCoin.
- T-Bank payments.
- Crypto Bot payments.
- Promo discount и credit reward promo.
- Recurring subscriptions через T-Bank.

### Партнерка

- Referral code у каждого пользователя.
- One-time referrer binding.
- Первый платеж реферала запускает бонус.
- Если пригласивший не партнер - бонус BoomCoin.
- Если партнер - рублевое партнерское начисление по цепочке до 3 уровней.
- Ставки партнерки: 1 уровень - 30%, 2 уровень - 10%, 3 уровень - 3%.
- Partner balance in RUB.
- Withdrawal через Jump Finance.
- Конвертация RUB partner balance -> BoomCoin.
- Admin referral tools и anti-fraud config.

### Админка

- Статистика.
- Пользователи.
- Ручное изменение баланса.
- Промокоды.
- Прайсы/пакеты.
- Подписочные параметры пакетов.
- Broadcast.
- Ban/unban.
- Maintenance mode.
- AI admin request flow.
- Push scenario management.
- Referral/partner controls.

## 6. Данные и хранение

Основной storage сейчас SQLite (`bot.db`), путь берется из `DATABASE_PATH`, а `DATABASE_URL` в конфиге пока скорее декларативен/миграционный.

Ключевые сущности:

- `users`.
- `transactions`.
- `generation_tasks`.
- `credit_transactions`.
- `promo_codes`.
- `promo_redemptions`.
- subscription tables.
- recurring subscription tables.
- partner withdrawal/referral-related fields.
- feed/public task fields.
- bot settings.
- user settings.
- batch jobs.
- GPT 5.5 history.

Важная особенность: `init_db()` делает auto-migrations при старте через `ALTER TABLE ... ADD COLUMN` и вспомогательные rebuild-миграции.

## 7. Надежность

Что уже есть:

- Idempotency Telegram updates через `runtime_reliability.mark_telegram_update()`.
- Provider event idempotency через Redis/NullRedis abstraction.
- Generation submit lock через `generation_guard`.
- Идемпотентное начисление платежей через ledger/reason/external id.
- Refund billing for failed generations.
- Friendly provider failure messages.
- Maintenance mode middleware.
- Ban middleware.
- Static uploads cleanup loop.
- Push scenarios background loop.
- Recurring payments background loop.
- Health endpoint.
- Systemd restart/watchdog.

Ограничение: если `REDIS_URL` не задан, используется in-memory `NullRedisService`; после рестарта idempotency keys и locks теряются.

## 8. Тестовая карта

Покрытые зоны по текущему `tests/`:

- config;
- database;
- subscriptions/payments;
- referral system;
- admin packages;
- admin AI service;
- push scenario service;
- Redis/reliability;
- generation guard;
- webhook handler;
- validators/help texts;
- keyboards/states;
- storage policy;
- migration assets;
- WAN/Kie payload;
- GPT 5.5 delivery;
- cleanup uploads.

Проверка 2026-06-07:

```bash
pytest -q
195 passed in 27.47s
```

## 9. Риски

### Высокие

1. `generation.py` слишком большой. Любое изменение FSM или callback patterns может случайно задеть соседние сценарии.
2. `database.py` совмещает storage, schema migrations и бизнес-логику. Это усложняет денежные изменения, подписки и партнерку.
3. `main.py` держит много provider webhook parsing/delivery logic. Callback-контракты провайдеров лучше изолировать.
4. При отсутствии Redis runtime idempotency не переживает рестарт.
5. `AI_WEBHOOK_SECRET` без значения превращает AI callbacks в unsigned endpoints.

### Средние

1. Есть legacy/переходные элементы: YooKassa config, Novita comments, PostgreSQL future backend, старые model aliases.
2. `price.json`, admin overrides и model registries требуют синхронности: модель может быть в UI, но без корректного cost key, или наоборот.
3. Auto-migrations в SQLite удобны, но сложнее контролируются, чем версионированные миграции.
4. Большая часть provider integrations зависит от внешних API, поэтому unit tests проверяют не весь production-path.

### Низкие

1. Документация частично дублируется между README и `docs/`.
2. Есть standalone/manual test-файлы рядом с pytest suite.
3. Некоторые сервисы имеют fallback/legacy paths, которые стоит периодически чистить.

## 10. Рекомендованная целевая карта

### Короткий горизонт

1. Проверить production `.env`: `AI_WEBHOOK_SECRET`, `REDIS_URL`, payment provider keys, `WEBHOOK_HOST`.
2. Зафиксировать таблицу `model -> provider -> env vars -> webhook route -> cost key`.
3. Добавить smoke tests на все активные model registries: модель из UI должна иметь cost и service mapping.
4. Добавить health check глубже, чем `OK`: DB доступна, Redis mode, config warnings.
5. Разделить provider webhook parsing на маленькие pure functions и покрыть payload tests.

### Средний горизонт

1. Разбить `bot/database.py` на `bot/db/schema.py`, `users.py`, `credits.py`, `payments.py`, `subscriptions.py`, `partners.py`, `generation_tasks.py`, `feed.py`.
2. Сохранить `bot/database.py` как compatibility facade, чтобы не ломать handlers сразу.
3. Разбить `bot/handlers/generation.py` по сценариям: image, video, omni, references, retry, callbacks.
4. Вынести `bot/webhooks/` с normalized provider event schema.
5. Перейти от SQLite auto-migrations к версионированным миграциям для production DB.

### Длинный горизонт

1. PostgreSQL как основной storage.
2. Redis обязателен в production.
3. Очередь фоновых provider jobs/callback processing, если нагрузка растет.
4. Отдельный admin API или TMA, если Telegram admin UX станет тесным.
5. Domain-level observability: payment completion rate, provider failure rate, generation latency, refund rate, subscription renewal success.

## 11. Быстрая навигация

```text
bot/
  main.py                     entrypoint, webhook server, background loops
  config.py                   env config
  database.py                 SQLite schema + data access + business operations
  handlers/
    common.py                 menu, partner, GPT 5.5, Motion Control
    generation.py             main generation UX
    payments.py               topup/subscriptions/payment webhooks
    admin.py                  admin panel
    feed.py                   public feed
    batch_generation.py       batch flows
    image_analyzer.py         photo -> prompt
    admin_packages.py         package editing
    admin_referral_tools.py   referral/partner admin
    admin_push_scenarios.py   push scenario admin
  services/
    *_service.py              providers, payments, reliability, subscriptions
  utils/
    validators.py
    help_texts.py
data/
  price.json                  packages, subscription params, model costs
  runway_characters.json      local Runway character ids
docs/
  project_map_2026-06-07.md   this map
  project_analysis.md         previous analysis from 2026-05-25
  *_runbook / integration docs
scripts/
  run_bot_foreground.sh
  code_reload_watchdog.py
  bot_watchdog.py
  migrate_sqlite_to_postgres.py
tests/
  pytest regression suite
```
