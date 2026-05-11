# Project Audit

Last updated: 2026-05-11.

## Executive Summary

2Loop is operational in production. The bot, nginx, Mini App API, Telegram webhook, YooKassa
webhook compatibility route and watchdog are active. The main business flows are present:

- Telegram bot menu and FSM flows;
- image/video generation through several AI providers;
- GOE balance and payments;
- YooKassa and Robokassa integrations;
- catalog storefront `/shop`;
- React Telegram Mini App and admin product CRUD;
- public media uploads for AI providers.

The biggest risks are not infrastructure availability right now. The main risks are codebase
complexity, duplicated FSM handlers, split product storage, and incomplete automated coverage
for payments and generation flows.

## Production Inventory

### Runtime

```text
Domain:        https://2loop.chillcreative.ru
nginx:         active, HTTPS via Let's Encrypt
Backend:       aiohttp on 127.0.0.1:8443
Bot service:   2loop-bot.service
Watchdog:      2loop-watchdog.timer
Repo:          /root/2loop
Python venv:   /root/2loop/venv
```

### Important URLs

```text
Telegram webhook:          https://2loop.chillcreative.ru/webhook
YooKassa webhook:          https://2loop.chillcreative.ru/yookassa/webhook
YooKassa legacy alias:     https://2loop.chillcreative.ru/webhook/yookassa
Kie.ai webhook:            https://2loop.chillcreative.ru/webhook/kie_ai
Robokassa ResultURL:       https://2loop.chillcreative.ru/robokassa/result
Robokassa SuccessURL:      https://2loop.chillcreative.ru/robokassa/success
Mini App storefront:       https://2loop.chillcreative.ru/shop
Mini App API health:       https://2loop.chillcreative.ru/api/miniapp/health
Public uploads:            https://2loop.chillcreative.ru/uploads/...
```

### Data

```text
Main SQLite:       /root/2loop/bot.db
Mini App JSON:     /root/2loop/data/products.json
                   /root/2loop/data/orders.json
                   /root/2loop/data/settings.json
Catalog Excel:     /root/2loop/data/catalog.xlsx
Public uploads:    /var/www/2loop/static/uploads
Mini App build:    /var/www/2loop/static/miniapp
```

Important note: `TWOLOOP_DATA_DIR` does not control the main SQLite database. Unless
`DATABASE_PATH` is set, SQLite uses `bot.db` relative to `WorkingDirectory=/root/2loop`.

## Recent Stabilization Work

Completed during maintenance:

- configured SSH-over-443 workflow for GitHub;
- cloned and switched to `2loop_dev`;
- configured nginx and HTTPS for `2loop.chillcreative.ru`;
- installed systemd bot service;
- installed watchdog service/timer and log file;
- configured Telegram webhook;
- configured YooKassa credentials and payment provider;
- added YooKassa legacy webhook alias `/webhook/yookassa`;
- reconciled a missed YooKassa payment and credited the user;
- added post-payment action buttons;
- verified Mini App product CRUD and public image upload scenarios;
- fixed Mini App initial load for public users vs admins;
- fixed public uploads so AI providers receive real media files;
- added Seedream reference normalization to RGB JPEG;
- improved result-message UX for generated images;
- removed obsolete one-off scripts and scratch docs;
- added environment, operations, architecture and recommendation docs.

## Verified Checks

### Service Checks

```text
2loop-bot.service: active
nginx: active
2loop-watchdog.timer: active
```

### Route Checks

```text
GET  /api/miniapp/health       -> 200
POST /webhook/yookassa         -> 200 for route test
GET  /health                   -> OK from backend
```

### Mini App Scenarios

Verified earlier in the maintenance session:

- public health endpoint;
- public product list;
- non-admin product creation rejected;
- admin product create/update/delete;
- product image upload;
- uploaded image public availability;
- order create;
- admin order list;
- missing product image upload returns `404` without writing a file;
- browser `/shop` loads and product can be added to cart.

### Payment Scenarios

Observed and fixed:

- YooKassa sent webhooks to `/webhook/yookassa`;
- app previously only accepted `/yookassa/webhook`;
- old path returned `404`;
- alias now returns `200`;
- pending YooKassa transaction was reconciled;
- credits were added idempotently;
- user-facing success notification now has quick action buttons.

## Key Risks

### High: Duplicate FSM Handlers In `generation.py`

`bot/handlers/generation.py` contains 117 decorated handlers. Several groups are registered
multiple times:

```text
5x model_* callbacks
5x resolution_* callbacks
5x img_ratio_* callbacks
5x grounding_* callbacks
5x ref_* callbacks
5x custom_* callbacks
5x default_* callbacks
5x waiting_for_reference_video fallback
5x waiting_for_video_prompt photo handler
4x waiting_for_video_prompt text handler
4x reference video upload handler
3x waiting_for_input photo handler
```

Why it matters:

- aiogram registers each decorated function object at import time;
- later Python redefinitions do not remove earlier registrations;
- a callback or message may hit more than one handler;
- debugging user reports becomes much harder;
- payment-like flows are protected better than generation flows, but duplicated generation
  handlers can still cause confusing UX, incorrect state transitions or duplicate refunds.

Recommendation: split and deduplicate `generation.py` before adding more models.

### High: Split Store Data

The project has two store layers:

- Excel plus SQLite overrides in `catalog_webapp.py`;
- JSON-backed React Mini App in `miniapp_api.py`.

This can work temporarily, but product information can drift. Any serious inventory, delivery,
discount, CRM or analytics work should first choose one source of truth.

Recommendation: move Mini App JSON storage into SQLite and make both frontends use one product
API.

### Medium: Main DB Path Is Implicit

The database path is not explicit in `.env`. The current production database works because
systemd starts the bot in `/root/2loop`.

Risk: scripts or operators may accidentally inspect or create `/root/2loop/data/bot.db`.

Recommendation: set `DATABASE_PATH=/root/2loop/bot.db` in production `.env`.

### Medium: Manual YooKassa Reconciliation Does Not Notify

`scripts/poll_yookassa_pending.py` credits pending paid payments, but does not send the same
Telegram success notification as the webhook.

Recommendation: add `--notify` or make this limitation explicit in the runbook.

### Medium: Public Upload Cleanup Is Incomplete

The runtime cleanup loop targets repo-local `static/uploads`, while production media lives
under `/var/www/2loop/static/uploads`.

Recommendation: centralize media storage and cleanup using `config.UPLOADS_ROOT`, and keep
files referenced by active tasks.

### Medium: Provider-Specific Media Rules Are Scattered

Seedream requires accepted image formats; other providers have size, duration or URL behavior
rules. These rules currently live inside handlers/services.

Recommendation: introduce one media normalization service that validates and converts per
provider.

### Low/Medium: Development Tooling Is Not Explicit

Runtime dependencies exist, but dev dependencies such as `pytest`, `ruff` and formatters are
not declared separately.

Recommendation: add `requirements-dev.txt` and a minimal CI-like check script.

## Code Health Notes

### Positive

- `Config` now has normalized webhook URL helpers.
- YooKassa webhook verification fetches the payment before crediting.
- Robokassa ResultURL and SuccessURL use separate signature verification.
- Public uploads are now served by nginx from a stable root.
- Mini App admin APIs check Telegram `initData`.
- JSON writes use temp-file replace, which is safer than direct writes.

### Needs Attention

- `bot/database.py` mixes schema creation, migrations and data access in one large file.
- `bot/main.py` contains many provider webhook handlers and large message-sending branches.
- `bot/handlers/generation.py` is the main complexity hotspot.
- Several `except:` and broad `except Exception` blocks hide operational detail.
- Some runtime logs can be noisy and some provider payload logs can become large.

## Recommended Roadmap

1. Stabilization commit:
   - commit current webhook/payment/media/docs fixes;
   - keep YooKassa alias;
   - set explicit `DATABASE_PATH`.
2. Safety tests:
   - payment idempotency;
   - YooKassa alias;
   - Seedream media normalization;
   - Mini App admin/public authorization.
3. Generation refactor:
   - deduplicate decorators;
   - split image/video/reference modules;
   - add scenario tests around FSM transitions.
4. Store unification:
   - migrate Mini App JSON to SQLite;
   - make Excel an import source only;
   - use one product/order API.
5. Media service:
   - centralize save, normalize, public URL generation, cleanup;
   - store metadata;
   - provider-specific validation.
6. Observability:
   - admin diagnostics for pending payments and failed generations;
   - structured log fields for task id/payment id/user id/model.

## Operator Checklist

Before deploy:

```bash
cd /root/2loop
venv/bin/python -m py_compile bot/main.py bot/config.py bot/handlers/*.py bot/services/*.py
nginx -t
```

After deploy:

```bash
systemctl restart 2loop-bot.service
systemctl is-active 2loop-bot.service
curl -fsS http://127.0.0.1:8443/api/miniapp/health
curl -fsS https://2loop.chillcreative.ru/api/miniapp/health
journalctl -u 2loop-bot.service -n 80 --no-pager
```

For missed YooKassa payment:

```bash
cd /root/2loop
venv/bin/python scripts/poll_yookassa_pending.py
journalctl -u 2loop-bot.service -n 100 --no-pager | rg -i yookassa
```
