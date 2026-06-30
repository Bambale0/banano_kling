# LLM guide: как разработать бота уровня Banano Kling / BOOM Studio

Дата аудита: 2026-06-13.

Цель документа: дать LLM или новой команде полную карту для проектирования и разработки Telegram-бота схожего смысла и функциональности: AI-генерация изображений/видео, внутренняя валюта, подписки, платежи, промокоды, партнерка, админка, Telegram Mini App, webhooks, надежность и эксплуатация.

Этот файл описывает не только текущее устройство проекта, но и рекомендуемую целевую архитектуру для нового аналога. Текущий проект исторически SQLite-first; для нового production-проекта лучше сразу закладывать PostgreSQL + Redis.

## 1. Короткое резюме продукта

Бот - это AI studio внутри Telegram:

- пользователь создает изображения и видео через разные AI-провайдеры;
- загружает референсы, видео, фото персонажа, motion-видео;
- улучшает промпты, получает "фото -> промпт", общается с GPT-помощником;
- платит внутренней валютой BoomCoin или лимитами подписки;
- пополняет баланс через T-Bank/Crypto Bot;
- использует промокоды и реферальную/партнерскую программу;
- смотрит историю и публичную ленту;
- админ управляет пользователями, балансами, платежами, промо, тарифами, лентой, пуш-сценариями и системными настройками;
- Telegram Mini App дублирует ключевые пользовательские и админские сценарии в веб-интерфейсе.

## 2. Фактическая карта текущего проекта

Основной стек:

- Python 3.10+;
- Aiogram 3.x;
- aiohttp web server для Telegram/payment/provider/TMA routes;
- SQLite через `aiosqlite` в runtime;
- Redis опционально для idempotency, locks, rate counters;
- React 18 + Vite + TypeScript для `tma/`;
- systemd для production;
- pytest regression suite.

Ключевые файлы:

| Файл | Роль |
|---|---|
| `bot/main.py` | entrypoint, dispatcher, aiohttp server, Telegram/provider webhooks, background loops |
| `bot/config.py` | env config, derived URLs, flags providers/payments/TMA |
| `bot/database.py` | SQLite schema, auto-migrations, repositories/business operations |
| `bot/states.py` | FSM states для генерации, оплаты, партнерки, админки |
| `bot/keyboards.py` | Telegram inline keyboards |
| `bot/image_models.py` | реестр image-моделей, aliases, defaults, options |
| `bot/video_models.py` | реестр video-моделей по типам сценариев |
| `bot/tma_api.py` | TMA API, initData auth, user/admin endpoints |
| `tma/src/App.tsx` | Mini App UI: пользовательский кабинет и админка |
| `data/price.json` | пакеты, подписки, цены моделей, BoomCoin metadata |
| `bot/services/*_service.py` | провайдеры AI, платежи, reliability, subscriptions, push, admin AI |
| `tests/` | regression tests для конфигов, БД, webhooks, TMA, payments, subscriptions, referrals |

Крупные зоны риска в текущем коде:

- `bot/handlers/generation.py` концентрирует слишком много FSM и provider-specific логики;
- `bot/database.py` совмещает схему, миграции, DAO и бизнес-операции;
- `bot/main.py` содержит много webhook parsing/delivery logic;
- без `REDIS_URL` idempotency и locks становятся process-local;
- без `AI_WEBHOOK_SECRET` AI callbacks принимаются unsigned, что нельзя оставлять в production.

## 3. Целевая архитектура для нового похожего бота

Рекомендуемая структура:

```text
app/
  main.py                  # aiohttp/FastAPI bootstrap + lifespan
  config.py                # Pydantic Settings
  logging.py
bot/
  dispatcher.py            # create_dispatcher(), middlewares, router order
  middlewares/
    access.py              # ban, maintenance, profile sync
    rate_limit.py
  handlers/
    start.py
    common.py
    image_generation.py
    video_generation.py
    gemini_omni.py
    feed.py
    payments.py
    admin/
  keyboards/
  states.py
api/
  tma.py                   # TMA app/admin API
  webhooks/
    telegram.py
    tbank.py
    cryptobot.py
    providers.py
domain/
  models.py                # dataclasses/Pydantic domain DTOs
  pricing.py
  billing.py
  subscriptions.py
  referrals.py
  generations.py
services/
  providers/
    base.py                # normalized provider contract
    kling.py
    kie.py
    gpt_image.py
    gemini_omni.py
  payments/
  reliability.py
  storage.py
repositories/
  users.py
  credits.py
  payments.py
  subscriptions.py
  generation_tasks.py
  feed.py
  settings.py
db/
  migrations/
  schema.sql
tma/
  src/
tests/
docs/
```

Главный принцип: Telegram UX, TMA API, provider callbacks и платежи должны работать через одни доменные сервисы. Не дублировать списание, refunds, создание задач и проверку доступа в разных обработчиках.

## 4. Runtime modes и web server

Нужны два режима:

- polling: локальная разработка, `WEBHOOK_HOST` пустой;
- webhook: production, aiohttp/FastAPI server слушает Telegram, платежи, AI callbacks, TMA.

Минимальные HTTP routes:

| Route | Назначение |
|---|---|
| `POST {WEBHOOK_PATH}` | Telegram webhook |
| `POST /tbank/webhook` | payment notification |
| `POST /cryptobot/webhook` | crypto payment notification |
| `POST /webhook/provider/{provider}` | AI provider callbacks |
| `GET /health` | healthcheck |
| `GET /uploads/...` | публичные результаты/референсы |
| `GET /miniapp` | TMA index |
| `GET /miniapp/assets/...` | TMA build assets |
| `GET /api/tma/app/bootstrap` | user bootstrap |
| `POST /api/tma/app/generation` | generation from TMA |
| `POST /api/tma/app/upload` | TMA uploads |
| `GET /api/tma/app/ws` | realtime updates |
| `GET /api/tma/admin/bootstrap` | admin bootstrap |
| `GET/POST /api/tma/admin/...` | admin collections/actions |

Provider webhooks должны проверять секрет: query `secret`, header `x-webhook-secret`/`x-ai-webhook-secret` или bearer token. В production отсутствие секрета должно быть startup error, а не warning.

## 5. Конфигурация

Обязательные env-группы:

```env
BOT_TOKEN=
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=8443
ADMIN_IDS=

DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/app
REDIS_URL=redis://127.0.0.1:6379/0
AI_WEBHOOK_SECRET=

MINI_APP_URL=
MINI_APP_MODE=production
TMA_INIT_DATA_MAX_AGE_SECONDS=86400
```

Платежи:

```env
PAYMENT_PROVIDER=tbank
TBANK_TERMINAL_KEY=
TBANK_SECRET_KEY=
TBANK_API_URL=https://securepay.tinkoff.ru/v2/
TBANK_SUCCESS_URL=

CRYPTOBOT_API_TOKEN=
CRYPTOBOT_BASE_URL=https://pay.crypt.bot
CRYPTOBOT_ACCEPTED_ASSETS=USDT,TON,BTC,ETH,LTC,BNB,TRX,USDC
CRYPTOBOT_EXPIRES_IN=3600
```

AI providers:

```env
NANOBANANA_API_KEY=
KIE_AI_API_KEY=
GEMINI_API_KEY=
PIAPI_API_KEY=
FREEPIK_API_KEY=
NOVITA_API_KEY=
ALLOW_NSFW=0
```

Партнерка:

```env
PARTNER_MIN_WITHDRAWAL_RUB=0
PARTNER_RUB_PER_CREDIT=10
PARTNER_OFFER_URL=
PARTNER_RULES_URL=
JUMP_FINANCE_CLIENT_KEY=
JUMP_FINANCE_BASE_URL=https://api.jump.finance/services/openapi
JUMP_FINANCE_AGENT_ID=
JUMP_FINANCE_BANK_ACCOUNT_ID=
```

## 6. Доменная модель данных

Минимальные таблицы для аналога:

| Таблица | Назначение |
|---|---|
| `users` | Telegram profile, credits, referral fields, ban flags |
| `transactions` | платежные orders/invoices |
| `credit_transactions` | ledger BoomCoin, идемпотентные начисления/списания/refunds |
| `generation_tasks` | lifecycle AI generation task |
| `generation_history` | user-facing history |
| `user_settings` | default model/options |
| `gpt55_conversations` | chat history |
| `promo_codes` | discount/reward promo |
| `promo_redemptions` | promo usage by order/user |
| `bot_settings` | maintenance mode and JSON settings |
| `referrals` | referrer/referred relations |
| `partner_withdrawals` | withdrawal requests |
| `batch_jobs` | batch generation/edit jobs |
| `feed_interactions` | likes/shares/actions |
| `user_subscriptions` | active subscriptions |
| `subscription_usage` | image/video usage with refund flag |
| `recurring_subscriptions` | payment rebilling metadata |

Критически важные constraints:

- `users.telegram_id` unique;
- `transactions.order_id` unique;
- `generation_tasks.task_id` unique;
- `credit_transactions(reason, external_id)` unique для идемпотентности;
- `promo_redemptions(promo_id, order_id)` unique;
- `feed_interactions(task_id, telegram_id, action)` unique.

Для нового проекта используйте PostgreSQL migrations вместо runtime `ALTER TABLE` при старте.

## 7. Деньги, BoomCoin, подписки

Внутренняя валюта: BoomCoin. Текущая бизнес-логика: `1 BoomCoin = 10 ₽ внутреннего баланса`.

Пакеты из `data/price.json` делятся на:

- `kind=credits`: разовое пополнение;
- `kind=subscription`: доступ на период с лимитами image/video, includes_pro, priority.

Правильный платежный поток:

1. Пользователь выбирает пакет.
2. Backend создает `transactions` со статусом `pending`.
3. Payment provider возвращает payment URL/invoice.
4. Webhook подтверждает оплату.
5. `_complete_transaction` или аналог должен быть идемпотентным.
6. Для credit package начислить BoomCoin через ledger.
7. Для subscription package активировать подписку и, если нужно, добавить стартовые credits.
8. Применить promo redemption к конкретному `order_id`.
9. Начислить referral/partner бонус только на первый успешный платеж, если правила это требуют.

Нельзя просто делать `users.credits += amount` без ledger. Любое изменение баланса должно иметь reason, amount, external_id, metadata.

Списание генерации:

- сначала проверить активную подписку и лимиты;
- если подписка подходит, создать `subscription_usage`;
- если не подходит, списать BoomCoin через `credit_transactions`;
- при provider failure сделать refund: либо `subscription_usage.refunded=true`, либо обратный ledger entry.

## 8. Generation lifecycle

Единый lifecycle задачи:

```text
draft -> confirmed -> charged -> provider_submitted -> processing -> success|failed|cancelled -> delivered -> archived
```

Рекомендуемые поля `generation_tasks`:

- `task_id`: internal/provider-correlated id;
- `provider_task_id`: provider id, если отличается;
- `telegram_id` and `user_id`;
- `type`: image/video/gpt/photo_to_prompt/batch;
- `scenario`: text_to_image, image_to_image, text_to_video, image_to_video, video_to_video, motion_control, omni;
- `model`;
- `prompt`;
- `reference_images` / `reference_videos` as JSON;
- `duration`, `aspect_ratio`, `options` JSON;
- `cost`, `billing_source`, `subscription_usage_id`;
- `status`, `result_url`, `error_code`, `error_message`;
- `is_public_feed`, `feed_status`, `likes_count`;
- timestamps.

Важные правила:

- списание делать до provider submit или атомарно вокруг submit;
- если provider submit не создал задачу, сразу refund;
- provider callback должен быть идемпотентным;
- success callback должен сохранить result URL, скачать/проксировать файл при необходимости, отправить пользователю;
- failure callback должен показать friendly error и refund;
- большие видео могут не пройти direct Telegram upload: нужен fallback link/CDN.

## 9. Реестр моделей

Не хардкодить модели в UI. Нужен единый registry.

Image registry должен хранить:

- `id`;
- `label`;
- `cost_key`;
- `service`;
- `requires_refs`;
- `supports_refs`;
- `aspect_ratios`;
- `defaults`;
- `options`;
- provider-specific `api_model`.

Video registry должен хранить:

- `id`;
- `label`;
- `v_types`: `text`, `imgtxt`, `video`;
- `requires_refs`;
- `supports_refs`;
- `aspect_ratios`;
- `durations`;
- `defaults`;
- `options`;
- cost key.

Из текущего проекта стоит повторить модельный набор:

- image: Banana Pro, Banana 2, GPT Image 2, Grok T2I/I2I, Seedream 5 Lite, Seedream Edit, Ideogram Character, Wan 2.7 Image/Pro;
- video: Gemini Omni, Kling 3 Std/Pro, Seedance 2.0, Runway, Grok Imagine, Veo 3.1 Fast/Pro/Lite, Hailuo, HappyHorse, Wan 2.7, Aleph, Glow.

Добавьте тест: каждая модель из registry имеет price/cost, service adapter, валидные defaults и хотя бы один user-facing path.

## 10. Telegram FSM и UX flows

Основные FSM-группы:

- `GenerationStates`: image/video refs, prompt, options, confirmation, Gemini Omni helper flows;
- `PaymentStates`: package, promo, confirmation, waiting payment;
- `PartnerWithdrawalStates`: amount, full name, phone, card, conversion;
- `AdminStates`: broadcast, user id, credits, promo, AI admin;
- `BatchGenerationStates`: mode, preset, prompts, refs, confirmation;
- `ImageAnalyzerStates`: waiting photo.

Router order важен:

1. `start_router` - `/start` должен сбрасывать любой FSM;
2. generation routers с StateFilter;
3. image analyzer/feed;
4. admin routers;
5. payments;
6. batch;
7. common fallback.

UX-сценарии, которые нужно реализовать:

- главное меню;
- создать фото;
- мульти-фото / edit by references;
- создать видео из текста;
- оживить фото;
- video-to-video;
- Motion Control: фото персонажа + видео движения;
- Gemini Omni multimodal;
- фото -> промпт;
- улучшение промпта;
- история;
- лента: открыть, лайк, повторить, редактировать промпт;
- баланс/пополнение;
- подписки;
- промокод;
- рефералка/партнерка;
- GPT 5.5 чат;
- админка.

## 11. Telegram Mini App

TMA должна быть не лендингом, а рабочим кабинетом.

Backend:

- валидировать `initData` через HMAC `WebAppData` + `BOT_TOKEN`;
- проверять `auth_date` по `TMA_INIT_DATA_MAX_AGE_SECONDS`;
- user endpoints доступны только с валидным user;
- admin endpoints дополнительно проверяют `ADMIN_IDS`;
- bootstrap должен быть ограниченным и пагинированным;
- тяжелые коллекции грузить лениво.

Frontend:

- React + Vite + TypeScript;
- Telegram WebApp SDK;
- tabs: home, create, history, feed, gpt55, settings;
- admin tabs: dashboard, users, payments, subscriptions, generations, feed, packages, promos, partners, automation, system;
- upload controls для референсов;
- WebSocket/SSE или polling для realtime task updates;
- graceful fallback, если Mini App открыт вне Telegram и initData нет.

TMA action bridge полезен для сценариев, где web UI должен отправить пользователю Telegram inline-button/deep link.

## 12. Партнерка и рефералы

Минимальная логика:

- у каждого пользователя referral code;
- приглашенный закрепляется за referrer один раз;
- signup bonus optional;
- first payment bonus only once;
- партнерская цепочка до 3 уровней: 30%, 10%, 3%;
- если referrer не партнер, можно начислять BoomCoin;
- если партнер, начислять RUB balance;
- withdrawals через payout provider;
- conversion partner RUB -> BoomCoin по курсу `PARTNER_RUB_PER_CREDIT`.

Нужны anti-fraud ограничения:

- нельзя пригласить себя;
- нельзя менять referrer после первого binding;
- лимиты бонусов в день;
- блокировка suspicious users;
- audit trail всех начислений.

## 13. Admin panel

Обязательные возможности:

- dashboard: users, revenue, active tasks, failed tasks, provider stats;
- users: поиск, карточка, ban/unban, balance adjustment;
- payments: список, проверка, cancel/archive pending;
- subscriptions/recurring: просмотр, отключение, renewal status;
- generations: просмотр задач, retry/refund/manual mark failed;
- feed moderation;
- packages: price, credits, bonus, visibility, subscription limits;
- promos: discount/reward, limits, active dates;
- partners: balances, withdrawals, payouts, settings;
- push scenarios: automation rules and due events;
- system: maintenance mode, config warnings, health.

Admin actions должны быть auditable: `admin_id`, action, target, before/after, timestamp.

## 14. Reliability и безопасность

Обязательные механизмы:

- Redis idempotency для Telegram update_id;
- Redis idempotency для provider events;
- Redis/user lock на generation submit;
- rate limits на user actions;
- signed provider webhooks;
- TMA initData HMAC;
- payment webhook signature/token verification;
- ledger unique ids;
- friendly provider errors;
- refund on failure;
- maintenance middleware;
- ban middleware;
- uploads cleanup;
- healthcheck с DB/Redis/config warnings.

Production invariants:

- `AI_WEBHOOK_SECRET` must be set;
- `REDIS_URL` must be set;
- `DATABASE_URL` must be PostgreSQL;
- all payment callbacks must be idempotent;
- all money movements must be in ledger;
- raw provider errors must not leak secrets;
- logs must not contain API keys or full payment tokens.

## 15. Storage

Текущий проект хранит файлы под `/uploads/` и физически делит:

- `temp_refs`;
- `results`;
- `user_uploads`.

Для аналога:

- normalize extension;
- validate MIME and size;
- store date-based paths;
- keep public URL compatibility;
- clean temporary refs by TTL;
- for large video use CDN/object storage or proxy download;
- never trust provider filename.

## 16. Тестовая стратегия

Минимальный suite:

- config parsing and derived URLs;
- TMA initData validation;
- DB migrations/schema constraints;
- ledger idempotency;
- payment completion idempotency;
- subscription consume/refund;
- referral first payment rules;
- generation submit guard and user locks;
- provider payload builders for every model;
- provider callback parsing success/failure;
- prompt guards;
- keyboards/callback data;
- admin package updates;
- TMA bootstrap/action endpoints;
- upload storage policy;
- Redis Null/real adapter behavior.

Команды:

```bash
pytest -q
python -m compileall -q bot tests
python -m pip check
cd tma && npm run build
cd tma && npm audit --omit=dev --audit-level=high
```

## 17. Production deployment

Минимальный production набор:

- systemd service или Docker Compose;
- nginx reverse proxy with HTTPS;
- webhook URL set in Telegram;
- `/health` behind localhost/public monitoring;
- logs rotation;
- Redis and PostgreSQL backups;
- object storage backup policy;
- watchdog or external monitor;
- deploy checklist.

Полезные команды из текущего проекта:

```bash
systemctl status bot.service --no-pager -l
journalctl -u bot.service -n 120 --no-pager
tail -n 180 logs/bot.log
curl -fsS -i http://127.0.0.1:8443/health
pytest -q
cd tma && npm run build
```

## 18. LLM implementation playbook

Если LLM пишет такой проект с нуля, действовать в таком порядке:

1. Создать scaffold: config, logging, bot dispatcher, aiohttp/FastAPI app, health.
2. Поднять PostgreSQL schema и repository interfaces.
3. Реализовать users, settings, ledger, transactions.
4. Реализовать pricing registry и model registry.
5. Реализовать один image provider end-to-end: Telegram flow, billing, provider submit, callback, delivery, refund.
6. Добавить Redis idempotency/locks до второго provider.
7. Добавить платежи и subscription activation.
8. Добавить TMA initData validation и user bootstrap.
9. Добавить остальные generation scenarios.
10. Добавить feed/history.
11. Добавить referrals/partner.
12. Добавить admin panel.
13. Добавить provider matrix tests и payment/generation regression tests.
14. Подготовить production runbook and monitoring.

При изменении или добавлении модели всегда проверить матрицу:

```text
model id -> registry -> UI option -> cost key -> provider service -> payload builder -> callback parser -> tests
```

При изменении денег всегда проверить матрицу:

```text
package -> transaction -> payment provider -> completion idempotency -> ledger -> subscription/referral -> tests
```

При изменении TMA всегда проверить матрицу:

```text
route -> initData auth -> admin/user permissions -> payload size -> frontend state -> tests/build
```

## 19. Советы по качеству

- Не держать provider-specific ветки в Telegram handlers; вынести adapters.
- Не смешивать SQL и бизнес-правила в одном гигантском модуле.
- Все callbacks нормализовать в единый `ProviderEvent`.
- Не полагаться на provider callback как единственный источник статуса: добавить polling/reconcile job.
- Все долгие операции запускать с timeout.
- Все внешние API покрывать payload unit tests без live keys.
- Делать human-friendly errors, но логировать технический контекст.
- Хранить model options в registry, а не в разбросанных callback handlers.
- TMA bootstrap не должен тащить всю историю и всю ленту.
- Для больших видео сразу проектировать CDN/object storage.
- Для админских действий хранить audit log.
- Для production запрещать старт с пустыми critical secrets.

## 20. Быстрый definition of done

Похожий бот можно считать production-ready, если:

- пользователь может создать фото и видео end-to-end;
- списание и refund работают идемпотентно;
- платеж подтверждается webhook-ом и не начисляется дважды;
- подписка расходуется и возвращается при failure;
- TMA endpoints защищены initData;
- admin endpoints защищены admin id;
- provider webhooks подписаны;
- Redis включен;
- health показывает DB/Redis/config state;
- есть regression tests для денег, webhooks, model payloads и TMA;
- production deploy имеет restart, logs, backup, monitoring.
