# Architecture

2Loop is a Telegram bot plus an aiohttp web server.

## Runtime Flow

```text
Telegram / browser / payment provider / AI provider
        |
        v
nginx :443
        |
        v
aiohttp in bot/main.py on 127.0.0.1:8443
        |
        +-- aiogram Dispatcher and routers
        +-- payment webhooks
        +-- AI provider webhooks
        +-- Mini App API
        +-- catalog storefront API
```

## Main Components

### `bot/main.py`

- loads `.env`;
- initializes the database;
- registers aiogram routers;
- starts aiohttp routes;
- handles Telegram, Kie.ai, Kling, Replicate, YooKassa and Robokassa webhooks;
- serves local static routes for the backend process.

### `bot/handlers`

- `common.py`: `/start`, menu, settings, AI assistant, motion control helper flow;
- `generation.py`: image/video generation flows;
- `payments.py`: balance top-up, YooKassa/Robokassa callbacks;
- `admin.py`: Telegram admin panel;
- `catalog.py`: bot-side catalog and Mini App order handoff;
- `batch_generation.py`: batch/reference editing;
- `image_analyzer.py`: photo-to-prompt.

### `bot/services`

Provider/service clients:

- `nano_banana_2_service.py`
- `nano_banana_pro_service.py`
- `seedream_service.py`
- `kling_service.py`
- `grok_service.py`
- `runway_service.py`
- `aleph_service.py`
- `yookassa_service.py`
- `robokassa_service.py`

### Storefront Layers

There are two shop layers:

1. `bot/catalog_webapp.py` and `static/shop/`
   - Uses `data/catalog.xlsx`.
   - Stores overrides and orders in SQLite.

2. `bot/miniapp_api.py` and `miniapp/`
   - Uses JSON files:
     - `data/products.json`
     - `data/orders.json`
     - `data/settings.json`
   - Verifies Telegram Mini App `initData`.
   - Provides admin product CRUD.

This split is intentional for now, but it is a source of product-data drift.

## HTTP Route Inventory

### Webhooks And Health

```text
POST /webhook              Telegram updates
POST /yookassa/webhook     YooKassa canonical webhook
POST /webhook/yookassa     YooKassa legacy compatibility alias
POST /robokassa/result     Robokassa ResultURL
GET  /robokassa/result     Robokassa ResultURL fallback
GET  /robokassa/success    Robokassa SuccessURL
POST /webhook/kling        Kling/provider webhook
POST /webhook/kie_ai       Kie.ai webhook, path configurable
GET  /health               backend liveness
```

### Storefront And Mini App

```text
GET    /shop
GET    /api/catalog
POST   /api/shop/order

GET    /api/miniapp/health
GET    /api/miniapp/me
GET    /api/miniapp/products
GET    /api/miniapp/products/{id}
POST   /api/miniapp/products
PUT    /api/miniapp/products/{id}
DELETE /api/miniapp/products/{id}
POST   /api/miniapp/products/{id}/images
GET    /api/miniapp/settings
PUT    /api/miniapp/settings
POST   /api/miniapp/promo
POST   /api/miniapp/orders
GET    /api/miniapp/orders
```

## Data Stores

```text
SQLite:
  users
  transactions
  generation_tasks
  generation_history
  user_settings
  referrals
  analytics_events
  shop_* tables

JSON:
  data/products.json
  data/orders.json
  data/settings.json

Excel:
  data/catalog.xlsx

Public static:
  /var/www/2loop/static
  /var/www/2loop/static/uploads
```

The main SQLite path is controlled by `DATABASE_PATH`. If it is unset, `bot/database.py`
defaults to `bot.db` in the process working directory. Production currently runs from
`/root/2loop`, so the effective path is `/root/2loop/bot.db`.

## Generated Media

AI input/reference files are saved into the public uploads root and returned as:

```text
https://2loop.chillcreative.ru/uploads/<date>/<file>
```

This path must be served by nginx as real media files. If nginx falls back to Mini App HTML,
AI providers reject inputs with validation errors.

Seedream reference images are normalized to RGB JPEG before API submission because the
provider rejects some image formats that Telegram can accept.

## Payment Safety

YooKassa webhooks are not trusted blindly. The handler fetches the payment from YooKassa and
checks:

- payment status;
- paid flag;
- metadata order id when present;
- amount against the local transaction.

Robokassa handlers verify signatures separately for ResultURL and SuccessURL.
