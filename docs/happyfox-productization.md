# HappyFox productization

HappyFox reuses the proven `tanyapi` runtime instead of maintaining a second generation/billing backend.

## Branch contract

- `tanyapi` remains the NEUROMIX production source of truth.
- `happyfox` is the HappyFox release branch.
- Feature work targets `happyfox` through pull requests.
- HappyFox CI must never deploy with NEUROMIX production credentials or write into NEUROMIX database/Redis/media roots.

## Product configuration

Backend product identity is selected by:

```env
PRODUCT_ID=happyfox
```

Frontend product identity is selected at build time by:

```env
NEXT_PUBLIC_PRODUCT_ID=happyfox
```

The HappyFox branch defaults to `happyfox`, but both product configurations remain explicit so the shared-core boundary stays testable.

Canonical sources:

- `bot/product.py` — backend brand and bot copy;
- `frontend/miniapp-v0/lib/product.ts` — frontend product identity;
- `frontend/miniapp-v0/lib/brand.ts` — compatibility exports for existing components.

## Reuse, do not rewrite

HappyFox inherits unchanged unless a concrete requirement is missing:

- Telegram initData validation;
- users and profiles;
- balance/ledger;
- payment settlement and idempotency;
- generation tasks and provider callbacks;
- retries/watchdogs;
- uploads/media delivery;
- feed/history/reference infrastructure;
- partner/support/admin services;
- provider adapters and model capability registry;
- Docker/CI production validation.

Provider/model/internal identifiers such as `banano_*`, `banana_*`, database enum values, callback IDs and Redis keys are technical compatibility contracts and are not branding targets.

## Isolation before production

Before HappyFox deployment is enabled, configure dedicated:

- Telegram bot token and webhook;
- public Mini App domain;
- backend domain;
- database/schema or isolated database;
- Redis namespace/database;
- media root/domain;
- payment credentials/webhook routes;
- deployment environment/secrets;
- monitoring and backups.

There must be no fallback from missing `HAPPYFOX_*` deployment secrets to NEUROMIX production secrets.

## Release gates

The `happyfox` branch must pass:

1. full safe Python regression suite;
2. locked frontend install and dependency audit;
3. Next.js production static export;
4. browser critical-flow E2E;
5. production Docker image build/import smoke.

Only after those gates are green do we add a separate HappyFox deployment workflow and production smoke.
