# Recommendations

Last updated: 2026-05-11.

This document prioritizes the next engineering work for 2Loop. It is intentionally practical:
each item describes the problem, the risk, and the recommended direction.

## Priority 0: Keep Production Stable

### Keep YooKassa Webhook Alias For Now

Production accepts both:

```text
https://2loop.chillcreative.ru/yookassa/webhook
https://2loop.chillcreative.ru/webhook/yookassa
```

The dashboard should use `/yookassa/webhook`, but the old `/webhook/yookassa` alias should
stay until logs show no more retries to the legacy URL for at least several days.

### Make `DATABASE_PATH` Explicit

Current runtime uses `/root/2loop/bot.db` because `DATABASE_PATH` is unset and
`2loop-bot.service` starts in `/root/2loop`.

Recommendation:

```env
DATABASE_PATH=/root/2loop/bot.db
```

This removes ambiguity between the main SQLite database and `TWOLOOP_DATA_DIR`.

### Add A Payment Reconcile Runbook

`scripts/poll_yookassa_pending.py` can reconcile pending YooKassa transactions, but it does
not send user-facing Telegram success messages. Keep it as an operator tool and document that
manual notification may be needed after reconciliation.

Recommended future improvement: add an optional `--notify` flag that sends the same
post-payment keyboard used by webhooks.

## Priority 1: Deduplicate `bot/handlers/generation.py`

`bot/handlers/generation.py` has 117 decorated handlers, with many duplicate decorator groups.
The duplicate groups found during audit:

```text
5x model_*
5x resolution_*
5x img_ratio_*
5x grounding_*
5x ref_*
5x custom_*
5x default_*
5x waiting_for_reference_video fallback
5x waiting_for_video_prompt photo handler
4x waiting_for_video_prompt text handler
4x reference video upload handler
3x waiting_for_input photo handler
```

Risk:

- aiogram registers decorated function objects when the module is imported;
- redefining a Python function name later does not unregister the old handler;
- this can cause duplicated processing, shadowed callbacks, confusing state transitions, and
  accidental double credit refunds or task creation.

Recommended refactor:

1. Freeze current behavior with scenario tests for:
   - image with no refs;
   - image with refs;
   - Seedream edit with refs;
   - text-to-video;
   - image-to-video;
   - video motion/reference flow.
2. Split the file by domain:
   - `handlers/image_generation.py`;
   - `handlers/video_generation.py`;
   - `handlers/reference_uploads.py`;
   - `handlers/video_edit.py`.
3. Register every callback prefix exactly once.
4. Keep generic fallback handlers at the bottom of each router and constrain them with
   `StateFilter` and explicit content filters.

## Priority 2: Unify Store Data

There are two storefront data models:

```text
Excel/SQLite catalog:
  bot/catalog_webapp.py
  data/catalog.xlsx
  shop_* SQLite tables

JSON Mini App:
  bot/miniapp_api.py
  miniapp/
  data/products.json
  data/orders.json
  data/settings.json
```

Risk:

- product names, prices, stock, images and active flags can drift;
- admin changes in one layer do not automatically update the other;
- JSON writes are atomic at file level but not transactional across concurrent requests.

Recommendation:

- choose SQLite as the source of truth for products, images, settings and orders;
- keep Excel only as an import source;
- migrate `products.json`, `orders.json`, and `settings.json` into SQLite tables;
- expose one product API that both `/shop` and the React Mini App use.

## Priority 3: Harden Media Handling

Recent incidents came from public upload URLs and provider format requirements.

Current safeguards:

- nginx serves `/uploads/` from `/var/www/2loop/static/uploads/`;
- generated/reference media uses public URLs;
- Seedream references are converted to RGB JPEG before API calls.

Recommended next steps:

- centralize all media save/convert logic in one module, for example `bot/services/media_store.py`;
- store metadata: original mime, normalized mime, size, width, height, public URL;
- enforce max dimensions and file size per provider;
- make cleanup target the public uploads root, not only repo-local `static/uploads`;
- avoid deleting files referenced by active `generation_tasks`.

## Priority 4: Payment Tests And Idempotency

YooKassa is now verified by fetching the payment from YooKassa before crediting.
Robokassa verifies ResultURL and SuccessURL separately.

Recommended tests:

- YooKassa `payment.succeeded` credits once;
- repeated YooKassa webhook returns 200 and does not double-credit;
- wrong amount is ignored;
- wrong payment id is logged and does not silently credit when API verification fails;
- legacy `/webhook/yookassa` route works;
- Robokassa ResultURL signature succeeds/fails correctly;
- SuccessURL cannot credit by itself.

## Priority 5: Add Developer Tooling

The production venv currently supports runtime, but the project lacks explicit dev tooling.

Recommendation:

```text
requirements-dev.txt
  pytest
  ruff
  black or ruff-format
  pytest-asyncio
```

Minimal checks:

```bash
venv/bin/python -m py_compile bot/main.py bot/config.py bot/handlers/*.py bot/services/*.py
venv/bin/python -m pytest tests/test_config.py tests/test_database.py tests/test_keyboards.py
cd miniapp && npm run build
```

## Priority 6: Improve Observability

Current logs are useful but spread across journald, `logs/bot.log`, nginx and watchdog.

Recommendation:

- add structured event ids for payments and generation tasks;
- log provider task id, local task id, user id and model in one line on start and finish;
- reduce raw webhook body logging for provider payloads that can be large;
- add a small admin command for:
  - recent failed generation tasks;
  - pending payments;
  - last YooKassa webhook status;
  - public upload URL check.

## Suggested Sequence

1. Commit the current stabilization and docs.
2. Add `DATABASE_PATH=/root/2loop/bot.db` to production `.env` during a maintenance window.
3. Add payment idempotency tests.
4. Deduplicate `generation.py`.
5. Move Mini App JSON storage to SQLite.
6. Centralize media handling and cleanup.
