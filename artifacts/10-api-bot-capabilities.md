# 2Loop API And Bot Capabilities Artifact

Дата: 2026-05-16  
Статус: анализ текущего кода + OpenAPI-артефакт для утверждения  
Runtime сейчас: `aiohttp`, не FastAPI  
OpenAPI: `docs/openapi.json`  
Live docs routes после рестарта backend: `/api/docs`, `/api/redoc`, `/api/openapi.json`

## 1. Executive Summary

2Loop сейчас состоит из четырёх больших поверхностей:

1. Telegram bot на `aiogram`: генерация изображений/видео/контента, GOE-баланс, платежи, админ-команды, каталог.
2. Public website / landing SPA: pastel grunge сайт, demo site cabinet, demo GOE, генерация через `/api/site/*`.
3. Telegram Mini App / storefront: React/Vite Mini App + API `/api/miniapp/*`.
4. Shop/admin HTTP API: каталог, заказы, лиды, статусы, overview, payment/delivery stubs.

Технически backend поднимается в `bot/main.py` как `aiohttp` сервер на `127.0.0.1:8443`. FastAPI в проекте сейчас не используется. Поэтому безопасная первая реализация документации: добавить OpenAPI JSON и Swagger/ReDoc routes поверх текущего aiohttp, без миграции рантайма.

## 2. Добавленный Артефакт OpenAPI

Создано:

- `docs/openapi.json` — OpenAPI 3.1 спецификация текущих HTTP endpoints.
- `bot/openapi.py` — aiohttp routes:
  - `GET /api/openapi.json`
  - `GET /api/docs`
  - `GET /api/redoc`
- `bot/main.py` подключает `setup_openapi_routes(app)`.

После деплоя и рестарта сервиса:

- Swagger UI: `https://2loop.chillcreative.ru/api/docs`
- ReDoc: `https://2loop.chillcreative.ru/api/redoc`
- JSON: `https://2loop.chillcreative.ru/api/openapi.json`

Важно: Swagger UI и ReDoc HTML используют CDN (`swagger-ui-dist`, `redoc`). Если нужен полностью автономный production without CDN, нужно положить эти assets локально в `/static/docs/`.

## 3. HTTP API Inventory

### System

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | Health check backend | none |
| GET | `/api/openapi.json` | OpenAPI JSON | none |
| GET | `/api/docs` | Swagger UI | none |
| GET | `/api/redoc` | ReDoc UI | none |

### Site / Public Cabinet

Файл: `bot/catalog_webapp.py`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/site/session` | Создать/обновить site session | `X-2Loop-Session` optional |
| GET | `/api/site/cabinet` | Профиль сайта, demo GOE, features | `X-2Loop-Session` optional |
| POST | `/api/site/generate` | Demo генерация на сайте, списание demo GOE | `X-2Loop-Session` optional |
| GET | `/api/site/history` | История site generations + transactions | `X-2Loop-Session` optional |

Текущая модель сайта:

- `site_users`
- `site_generations`
- `site_goe_transactions`

Ограничение: это пока demo/session кабинет, не полноценный user account. Для реального кабинета нужна фаза auth: Telegram link + Google OAuth + session cookie.

### Shop / Public Storefront

Файл: `bot/catalog_webapp.py`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/catalog` | Каталог из `data/catalog.xlsx` + overrides/images | none |
| POST | `/api/shop/order` | Создать заказ из storefront | none / optional Telegram user payload |
| POST | `/api/shop/lead` | Лид/контактная форма | none |
| POST | `/api/shop/analytics` | Публичное событие аналитики | none |
| GET | `/api/shop/bot-capabilities` | Описание user/admin modules | none |
| POST | `/api/shop/payment/session` | Payment stub | none |
| GET | `/api/shop/delivery/methods` | Delivery methods stub | none |

Важная безопасность:

- `/api/shop/order` не доверяет клиентским ценам.
- Сервер пересобирает позиции через каталог и остатки.
- Проверяет customer/delivery required fields.

### Shop Admin

Файл: `bot/catalog_webapp.py`

Auth:

- `X-Shop-Admin-Key`
- или Telegram initData admin user.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/shop/admin/orders` | Список заказов |
| PUT | `/api/shop/admin/orders/{order_id}/status` | Обновить статус заказа |
| PUT | `/api/shop/admin/products/{wb_article}` | Override товара |
| GET | `/api/shop/admin/overview` | Users/tasks/orders/events overview |

Статусы заказа:

- `new`
- `pending`
- `confirmed`
- `paid`
- `shipped`
- `done`
- `cancelled`

### Telegram Mini App

Файл: `bot/miniapp_api.py`

Auth:

- `X-Telegram-Init-Data`
- проверка по `BOT_TOKEN`, если `TWOLOOP_VERIFY_INIT_DATA=1`.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/miniapp/health` | Health Mini App API | none |
| GET | `/api/miniapp/me` | Telegram user, admin flag, GOE stats | optional Telegram |
| GET | `/api/miniapp/goe` | GOE balance | Telegram required |
| GET | `/api/miniapp/history` | История генераций | Telegram required |
| GET | `/api/miniapp/tasks` | Задачи генерации | Telegram required |
| GET | `/api/miniapp/presets` | Presets | none |
| POST | `/api/miniapp/generate` | Генерация content/image/video/tryon/prompt | Telegram required |
| POST | `/api/miniapp/generate/smm` | SMM generation | Telegram required |
| GET | `/api/miniapp/products` | Список Mini App товаров | none |
| GET | `/api/miniapp/products/{product_id}` | Один товар | none |
| POST | `/api/miniapp/promo` | Promo calculation | none |
| POST | `/api/miniapp/orders` | Создать Mini App заказ | optional Telegram |

Mini App generation costs:

| Type | Cost |
|---|---:|
| `content` | 15 GOE |
| `image` | 30 GOE |
| `video` | 60 GOE |
| `tryon` | 45 GOE |
| `prompt` | 5 GOE |
| `smm` | 0 GOE |

### Mini App Admin

Файл: `bot/miniapp_api.py`

Auth:

- Telegram admin ids from `TWOLOOP_ADMIN_IDS` / `ADMIN_IDS`
- or open admin only if explicitly allowed with `TWOLOOP_ALLOW_OPEN_ADMIN=1`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/miniapp/products` | Создать товар |
| PUT | `/api/miniapp/products/{product_id}` | Обновить товар |
| DELETE | `/api/miniapp/products/{product_id}` | Удалить товар |
| POST | `/api/miniapp/products/{product_id}/images` | Upload product image |
| GET | `/api/miniapp/settings` | Settings |
| PUT | `/api/miniapp/settings` | Update settings |
| GET | `/api/miniapp/orders` | List Mini App orders |

### Webhooks

Файл: `bot/main.py`, `bot/handlers/payments.py`

| Method | Path | Purpose |
|---|---|---|
| POST | `/webhook` | Telegram webhook, path configurable via `WEBHOOK_PATH` |
| POST | `/yookassa/webhook` | YooKassa webhook |
| POST | `/webhook/yookassa` | Legacy YooKassa alias |
| POST/GET | `/robokassa/result` | Robokassa result |
| GET | `/robokassa/success` | Robokassa success |
| POST | `/webhook/kling` | Kling / PiAPI / Replicate style callback |
| POST | `/webhook/kie_ai` | Kie.ai callback, path configurable via `KIE_AI_WEBHOOK_PATH` |

Webhook security notes:

- Kie.ai supports shared token / signature verification.
- Replicate/Kling webhook branch verifies signature when configured.
- Payment webhooks verify provider signatures in their handler layer.

## 4. Telegram Bot Capabilities

### User-facing bot modules

Из `bot/handlers/common.py`, `bot/handlers/generation.py`, `bot/handlers/batch_generation.py`, `bot/handlers/catalog.py`, `bot/handlers/payments.py`, `bot/handlers/image_analyzer.py`.

Core flows:

- `/start` onboarding.
- `/help` help.
- Main menu with content/generation/wallet/catalog/support/settings.
- AI assistant chat/help.
- GOE balance.
- Payment/top-up flows.
- Generation history.
- Subscription check middleware.

Generation:

- Text-to-video.
- Image-to-video.
- Video-to-video / edit style flows.
- Image generation.
- Image editing from references.
- Photo to prompt analysis.
- Motion Control.
- Batch editing up to multiple images.
- Upscale/download flow for batch results.

Supported model families found in handlers/services:

- Kling.
- Seedream.
- Runway.
- Grok.
- Aleph.
- Nano Banana / Banana Pro / Banana 2.
- Gemini / Google image models.
- PiAPI fallback.

Commerce:

- Catalog menu.
- Mini shop web app button.
- Accessory finder.
- Promo code flow.
- Telegram web_app_data order intake.
- Server-side shop order creation.

Payments:

- YooKassa.
- Robokassa.
- Manual/provider selection UI.
- Payment check callbacks.
- Pending payment reconciliation helpers in services.

Admin:

- `/admin`
- Reload presets.
- Stats.
- Shop image/photo management.
- Product stock/price overrides.
- Orders overview.
- User lookup.
- Add/deduct credits.
- Broadcast.

## 5. Current Data Stores

Main DB:

- SQLite via `bot/database.py`.
- Optional Postgres/Redis documentation exists, but current runtime references SQLite paths.

Site tables:

- `site_users`
- `site_generations`
- `site_goe_transactions`

Mini App tables:

- `miniapp_products`
- `miniapp_generation_results`
- `miniapp_orders`

Bot/common tables referenced:

- `users`
- `generation_tasks`
- `generation_history`
- `transactions`
- `shop_orders`
- `analytics_events`
- product override/image tables.

JSON/Excel fallback:

- `data/catalog.xlsx`
- `data/products.json`
- `data/orders.json`
- `data/settings.json`
- `data/miniapp_generation_tasks.json`
- `data/miniapp_generation_history.json`

## 6. Auth Analysis

### Implemented now

Telegram Mini App:

- Header: `X-Telegram-Init-Data`.
- Parser: `_parse_init_data`.
- Verification: HMAC with `BOT_TOKEN` when `TWOLOOP_VERIFY_INIT_DATA=1`.
- Admin: `TWOLOOP_ADMIN_IDS` / `ADMIN_IDS`.

Site:

- Header/query/body session id: `X-2Loop-Session`, `sessionId`.
- Stored in frontend `localStorage` as `2loop.siteSession`.
- Not a secure HttpOnly session yet.

Admin:

- `X-Shop-Admin-Key`.
- Telegram admin init data.

### Missing for полноценный личный кабинет

Required next:

- HttpOnly secure session cookie.
- `GET /api/auth/me`.
- `POST /api/auth/logout`.
- `POST /api/auth/telegram/link`.
- Google OAuth:
  - `GET /api/auth/google/start`
  - `GET /api/auth/google/callback`
- Account identity table:
  - `user_id`
  - `provider`
  - `provider_user_id`
  - `email`
  - `display_name`
  - `avatar_url`
- Cart/account merge after login.

## 7. FastAPI / Open Docs Decision

Current backend is aiohttp and tightly connected to aiogram webhooks. Full migration to FastAPI would be a separate refactor.

Recommended path:

1. Keep aiohttp runtime now.
2. Serve OpenAPI JSON + Swagger/ReDoc via `bot/openapi.py`.
3. Use OpenAPI artifact as contract.
4. Later add FastAPI as either:
   - sidecar API service mounted behind nginx at `/api/v2/*`, or
   - full replacement after webhook/provider tests are locked.

FastAPI migration risks:

- Telegram webhook lifecycle changes.
- aiogram bot object app storage changes.
- Provider webhook compatibility.
- Existing aiohttp tests need rewrite.
- Static routing and nginx assumptions may drift.

## 8. Recommended Next Implementation Plan

### Phase 1: Docs and API contract

Done in this artifact:

- OpenAPI JSON.
- `/api/docs`.
- `/api/redoc`.
- API/bot capabilities artifact.

### Phase 2: Real auth foundation

- Add `web_users`, `auth_identities`, `web_sessions`.
- Add secure cookie sessions.
- Preserve current `site_users` by migrating/attaching session profile.
- Implement `/api/auth/me` and logout.

### Phase 3: Telegram account linking

- Use Telegram initData from Mini App.
- Link Telegram identity to web account.
- Merge GOE balance/history view.
- Expose account state in `/cabinet`.

### Phase 4: Google OAuth

- Env:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `GOOGLE_OAUTH_REDIRECT_URI`
  - `AUTH_SESSION_SECRET`
- Implement state/nonce storage.
- Verify callback.
- Upsert google identity.
- Link to existing session user if present.

### Phase 5: Full cabinet and cart

- Server cart tables.
- Guest local cart -> account cart merge.
- Cabinet tabs:
  - profile
  - GOE
  - generations
  - orders
  - delivery profile
  - favorites
- Checkout with server price recalculation.

### Phase 6: Tests and operational docs

- Auth tests.
- Cart merge tests.
- Checkout ownership tests.
- OpenAPI smoke tests.
- Production docs: nginx route, env vars, rollback.

## 9. Acceptance Criteria

Docs phase is accepted when:

- `GET /api/openapi.json` returns valid JSON.
- `GET /api/docs` returns Swagger UI HTML.
- `GET /api/redoc` returns ReDoc HTML.
- `docs/openapi.json` includes Site, Shop, Mini App, Admin and Webhook routes.
- Artifact explains bot capabilities and auth gaps.

Auth/cabinet phase should not start until these decisions are approved:

- account table naming;
- Google OAuth redirect domain;
- whether site GOE demo balance should migrate into real GOE or remain demo-only;
- whether Mini App orders and shop orders should be unified into one orders table.
