# Verified VK-only native model catalog into independent Mini App — 2026-11-11

## Production dependency
Native VK /root/vktanya master SHA a5b66bada77d3344649ab033a72164ed27256e14:
- HMAC-only signed GET /internal/v1/miniapp/users/{actor}/models.
- Registered, unblocked owner; no store, no mutable SQLite or provider secrets.
- Native worker-supported image models and video modes only; references/ratio/resolution sourced from actual native config, never Telegram price.
- Native 488 tests passed / 3 skipped; live HMAC signed 200 for registered VK actor with 3 photo and 15 video model capabilities; unsigned 401. Callback API active after service restart.

## Main Mini App native adapter
- GET /mini-app/api/account-preview/vk-models only accepts signed VK-only revocable bearer. Browser user_id query never defines actor. TG bearer -> 403, unsigned ->401.
- Backend signs exact loopback GET with HMAC, checks shape, strips any extra private/provider fields before sending.
- VK image form loads true native capabilities, renders only worker-compatible supported choices, quality ratios and per-model reference caps. No hardcoded model list, admin price or fake models.
- Failure/empty catalog fail CLOSED: no quote and no debit. Actual price always confirmed via authoritative native quote, then charge via existing idempotent native SQLite ledger. User still sees one VK wallet.
- Telegram UI, payment/partner funds and existing video flags unaffected.

## Test gate
- TDD red: signed VK models route absent (404), frontend showed hardcoded models and allowed unsupported ref count.
- GREEN: backend 77 pass / 70 isolated PG skipped, target auth cross-actor/Telegram denied; frontend 104 Jest suites / 790 tests pass; TypeScript, ESLint, Next VK export, Chromium mobile 430px and desktop 1280px smoke pass.
- Known scope: full shared MiniAppShell and all ten domain adapters #451 NOT complete. Video inputs requiring video references, paid video activation, services and financial E2E need separate acceptance. Do not flip full app parity flag.
