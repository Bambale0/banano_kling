# Mini App audit and Codex porting instruction

Дата аудита: 2026-08-21.

Используй этот документ как:

1. Аудит текущей NEUROMIX Telegram Mini App.
2. Рабочую инструкцию для Codex, чтобы реализовать приложение с тем же функционалом в другом проекте.

## Executive summary

Mini App реализована как статический Next.js frontend в `frontend/miniapp-v0` и backend API в `bot/miniapp.py`. Production frontend не требует Node.js runtime: он собирается в `out/` и обслуживается Nginx по `/mini-app/`. API проксируется на backend `/mini-app/api/*`.

Функционально покрыты ключевые сценарии: Telegram auth/bootstrap, модели и баланс, загрузка media, image/video/motion generation, история и task detail, feed/profile/trends/prompt library, публикации, платежи, AI assistant, browser-auth fallback и admin-only affordances.

Вердикт: архитектура годится как источник для переноса, но в новом проекте нельзя копировать её буквально. Нужно вынести auth, billing, media access, generation orchestration и feed/prompt domain logic в отдельные сервисы. В текущей реализации есть P1/P2 риски, которые надо закрыть перед переносом как обязательные acceptance criteria.

## Project map

Source of truth:

- `frontend/miniapp-v0/README.md` - frontend runtime, build, deployment and state-machine notes.
- `docs/architecture.md` - production topology and component overview.
- `docs/miniapp-frontend-deployment.md` - deployment, cache and Nginx expectations.
- `bot/miniapp.py` - Mini App backend API and route registration.
- `bot/browser_auth.py` - Telegram Login Widget browser fallback and trend/privacy middleware.
- `frontend/miniapp-v0/lib/api.ts` - frontend API client and Telegram initData extraction.
- `frontend/miniapp-v0/lib/app-context.tsx` - bootstrap, live/locked state, task sync and deep-link orchestration.
- `frontend/miniapp-v0/lib/start-params.ts` - supported deep link formats.
- `frontend/miniapp-v0/components/mini-app-shell.tsx` - loader/gate/live UI shell.
- `frontend/miniapp-v0/components/telegram-open-gate.tsx` - browser auth fallback.
- `frontend/miniapp-v0/components/balance-sheet.tsx` - payment UI.

Runtime topology:

```text
Telegram WebView
  -> https://cdn.chillcreative.ru/mini-app/
  -> static Next.js export
  -> /mini-app/api/* proxy
  -> aiohttp backend
  -> bot/database.py, provider services, payment services, Telegram bot
```

Frontend stack:

- Next.js 16, React 19, TypeScript.
- Tailwind CSS 4, Radix UI primitives, Framer Motion, lucide-react.
- Static export with `NEXT_EXPORT=1`, `basePath=/mini-app`, `assetPrefix=/mini-app`.
- Jest + Testing Library and focused Playwright/browser scripts.

Backend stack:

- Python aiohttp + aiogram in one runtime.
- Telegram initData HMAC validation.
- SQLite/PostgreSQL-compatible database layer.
- Provider/payment services called through backend only.

## Defect register

### P1: Public media gateway can expose private generation result by task_id

Evidence:

- `bot/miniapp.py:4885` defines `miniapp_media`.
- `bot/miniapp.py:4896` selects by `task_id` only.
- `bot/miniapp.py:4904` serves result URLs without validating `init_data`, owner, feed visibility, or a signed media token.
- `frontend/miniapp-v0/lib/api.ts:334` builds `/media/{task_id}/{index}` URLs for temporary provider media.

Risk:

If a private `task_id` leaks through logs, screenshots, Telegram messages or predictable provider IDs, another user can request `/mini-app/api/media/{task_id}/0` without auth and fetch a private result.

Expected:

Media gateway requires either:

- valid `init_data` and owner/public visibility check; or
- short-lived signed media token scoped to `task_id`, `index`, user and expiry.

Fix:

Make `miniapp_media` authenticated by default. For public feed media, resolve visibility through feed/profile publication records. For private task detail, require owner. If auth in image/video tags is impractical, issue signed URLs from `task-detail`/`bootstrap`.

Test:

Add backend tests:

- unauthenticated `/mini-app/api/media/{private_task_id}/0` returns `401/403`;
- owner can fetch;
- non-owner cannot fetch;
- public feed media can fetch only when publication scope allows it.

### P1: Generation billing can continue if atomic deduction fails after pre-check

Evidence:

- `bot/miniapp.py:4125` checks affordability for image generation.
- `bot/miniapp.py:4136` calls `deduct_credits(...)` but does not inspect the boolean result.
- `bot/miniapp.py:4544` and `bot/miniapp.py:4554` repeat the same pattern for video generation.
- `bot/miniapp.py:4693` and `bot/miniapp.py:4704` repeat it for Motion Control.
- `bot/database.py:4723` returns `False` when atomic deduction fails.

Risk:

Two concurrent requests can both pass `check_can_afford`. One deducts successfully, the other can receive `False` from `deduct_credits`, but the endpoint still launches a paid provider task. This creates free generation and inconsistent transaction history.

Expected:

The launch path must proceed only if the atomic debit succeeds. The pre-check can remain for UX, but the debit result is authoritative.

Fix:

Replace:

```python
if not is_admin:
    await deduct_credits(telegram_id, cost)
```

with:

```python
if not is_admin and not await deduct_credits(telegram_id, cost):
    return web.json_response(
        {"ok": False, "error": f"Недостаточно бананов. Нужно {cost}🍌"},
        status=400,
    )
```

Test:

Add concurrency tests where two paid generation requests race against a balance that can cover only one. Exactly one request may reach provider launch.

### P2: Lava payment email collected in UI is ignored by backend

Evidence:

- `frontend/miniapp-v0/components/balance-sheet.tsx:120` sends `customerEmail` for Lava.
- `frontend/miniapp-v0/lib/payment-api.ts:27` serializes it as `customer_email`.
- `bot/miniapp.py:2938` calls `lava_service.create_invoice`.
- `bot/miniapp.py:2939` passes `email=config.LAVA_DEFAULT_EMAIL` instead of request `customer_email`.

Risk:

User sees a promise that email will be saved/reused, but provider receives a default email. This can break receipt/accounting flows and create support issues.

Expected:

Backend validates `customer_email` for card/SBP providers when required, stores it if product requires reuse, and passes it to Lava.

Fix:

Read and validate `customer_email` in `miniapp_create_payment`, persist it on user profile if intended, and pass it to Lava. If Lava does not require email, remove/adjust the UI copy.

Test:

Add frontend unit test for Lava payload and backend test asserting `lava_service.create_invoice(email=customer_email)`.

### P2: CORS middleware echoes arbitrary Origin with credentials

Evidence:

- `bot/miniapp.py:5097` reads any `Origin`.
- `bot/miniapp.py:5099` and `bot/miniapp.py:5111` echo it into `Access-Control-Allow-Origin`.
- `bot/miniapp.py:5100` and `bot/miniapp.py:5112` set `Access-Control-Allow-Credentials: true`.

Risk:

The API mostly uses explicit Telegram `init_data` rather than cookies, so this is not a classic cookie CSRF by itself. Still, an arbitrary website should not be granted credentialed CORS to the Mini App API surface.

Expected:

Allow only configured frontend origins, Telegram WebView origins if needed, and local development origins. Reject or omit CORS headers for everything else.

Fix:

Introduce `MINIAPP_ALLOWED_ORIGINS` derived from `config.mini_app_url`, development URLs and explicit env entries. Echo only allowlisted origins.

Test:

Add middleware tests:

- production origin gets CORS headers;
- unknown origin does not;
- preflight unknown origin does not get credentialed allow headers.

### P2: Unexpected backend errors can leak raw exception text

Evidence:

- `bot/miniapp.py:246` logs unexpected errors.
- `bot/miniapp.py:247` returns JSON with `default_error or str(error)`.

Risk:

Provider errors, filesystem errors or integration exceptions can expose implementation details to users.

Expected:

Unexpected 500 responses return stable user-safe text and a correlation/request ID. Detailed exception text remains in logs only.

Fix:

For unexpected errors, return `{"ok": false, "error": "Не удалось выполнить действие. Попробуйте позже.", "request_id": ...}` unless a handler passes a known safe `default_error`.

Test:

Unit test `_miniapp_error_response(RuntimeError("secret"))` does not include `secret`.

## API matrix

Core frontend routes:

```text
POST /mini-app/api/bootstrap
POST /mini-app/api/upload
POST /mini-app/api/generate-image
POST /mini-app/api/generate-video
POST /mini-app/api/generate-motion
POST /mini-app/api/task-detail
POST /mini-app/api/create-payment
POST /mini-app/api/ai-assistant
POST /mini-app/api/photo-to-prompt
POST /mini-app/api/action
POST /mini-app/api/client-log
GET  /mini-app/api/media/{task_id}/{index}
GET  /mini-app/api/browser-auth/config
POST /mini-app/api/browser-auth
```

Prompt/trends/feed/profile routes:

```text
POST /mini-app/api/prompts
POST /mini-app/api/prompts/detail
POST /mini-app/api/prompts/like
POST /mini-app/api/prompts/use
POST /mini-app/api/prompts/link
POST /mini-app/api/prompts/submit
POST /mini-app/api/prompts/deactivate
POST /mini-app/api/admin/prompts/update-preview
POST /mini-app/api/admin/prompts/moderate
POST /mini-app/api/feed
POST /mini-app/api/feed/item
POST /mini-app/api/feed/my
GET/POST /mini-app/api/feed/profile
POST /mini-app/api/profile/channel
POST /mini-app/api/feed/like
POST /mini-app/api/feed/share
GET/POST /mini-app/api/feed/comments
POST /mini-app/api/feed/comment
POST /mini-app/api/feed/blur
POST /mini-app/api/feed/remove
POST /mini-app/api/feed/remix
POST /mini-app/api/generations/share
POST /mini-app/api/generations/publish
POST /mini-app/api/generations/share-library
POST /mini-app/api/generations/remove-library
```

Public v1 compatibility surface exists under `/api/v1/*` for feed/profile/prompts/generation compatibility and must be treated as a separate public API contract.

## Business invariants

Implement and test these invariants in the new project:

- Every mutating Mini App API call validates Telegram auth server-side.
- Frontend never trusts `isAdmin` alone; backend rechecks admin role for every admin action.
- User can read only own private tasks.
- Public feed/profile visibility is resolved server-side.
- Balance cannot go negative.
- A generation is launched only after successful atomic debit.
- Failed immediate provider launch refunds exactly once.
- Provider async failure has a clear refund/status policy.
- Payment webhook is idempotent.
- Payment amount/package/currency are verified before crediting.
- Duplicate webhooks do not double-credit.
- Uploads are owner-bound and MIME/size-validated.
- Provider/temp media is cached only from allowlisted hosts.
- Deep-link params cannot override signed Telegram identity.
- Browser auth fallback is short-lived and cannot bypass normal initData validation.

## Codex porting instruction

Use this section verbatim in the target project.

### Role

You are implementing a Telegram Mini App with NEUROMIX capability parity in a different project. Do not copy files blindly. Recreate the capabilities, contracts, security boundaries and UX state machine using the target project's architecture.

### First read in the source project

Read these source files before coding:

- `docs/architecture.md`
- `frontend/miniapp-v0/README.md`
- `docs/miniapp-frontend-deployment.md`
- `bot/miniapp.py`
- `bot/browser_auth.py`
- `frontend/miniapp-v0/lib/api.ts`
- `frontend/miniapp-v0/lib/app-context.tsx`
- `frontend/miniapp-v0/lib/start-params.ts`
- `frontend/miniapp-v0/lib/types.ts`
- `frontend/miniapp-v0/components/mini-app-shell.tsx`
- `frontend/miniapp-v0/components/telegram-open-gate.tsx`
- `frontend/miniapp-v0/components/tabs/*`
- `frontend/miniapp-v0/components/forms/*`
- existing tests under `frontend/miniapp-v0/__tests__`, `frontend/miniapp-v0/lib/__tests__`, `frontend/miniapp-v0/components/**/__tests__`, and `frontend/miniapp-v0/e2e`.

### Target architecture

Create these modules or equivalents:

1. `miniapp_auth`
   Telegram initData validation, browser Telegram Login validation, start_param handling, auth expiry and error mapping.

2. `miniapp_api`
   Thin HTTP routes. Routes parse request, call domain services, return stable JSON. No provider or billing business logic inside handlers.

3. `miniapp_billing`
   Atomic debit/refund, package lookup, transaction ledger, idempotency keys, payment provider integration and webhook application.

4. `generation_orchestrator`
   Creates generation tasks, validates model/scenario payloads, launches provider tasks, stores external IDs, handles immediate failures, polling/webhook updates and stuck task recovery.

5. `media_service`
   Owner-bound upload storage, MIME sniffing, max size validation, durable references, temp media cache, signed/private media URLs.

6. `feed_prompt_service`
   Feed/profile publication, prompt library, trend cards, likes/comments/shares, remix/repeat lineage and author payout/credit tracking.

7. `miniapp_frontend`
   Static Telegram Mini App UI with loader/gate/live state machine, no mock live data after failed auth, and typed API client.

8. `admin_policy`
   Server-side admin checks for trend moderation, feed moderation and admin-only generation forms.

### Required frontend behavior

Implement:

- Fullscreen loader while Telegram initData/bootstrap is unresolved.
- Locked/browser gate when initData is unavailable after timeout.
- Telegram WebApp `ready()` and `expand()` on mount plus early-ready bridge for Telegram WebView reliability.
- Live state after successful bootstrap: user, balance, image models, video models, saved references, recent tasks, notifications.
- Dynamic heavy tabs with skeleton fallback.
- Bottom tab navigation for Studio, Photo, Video, Motion, Services, Trends, Feed and Profile or equivalent.
- Balance sheet with packages, Stars and card/SBP provider support as configured by backend.
- Upload controls for image/video/audio references.
- Image generation form with model, prompt, ratio, quality, NSFW controls where supported.
- Video generation form with text/image/video/audio/avatar/character/provider-specific settings.
- Motion Control form.
- Seedance 2.5 dedicated flow if the target product supports it, including chunked large video upload.
- Task history and task detail panel with polling/focus/visibility refresh.
- Feed grid with comments, likes, share, remix/repeat, profile deep links.
- Prompt/trend library with admin-only creation/moderation controls.
- Profile tab with own feed, viewed profile feed, referral/partner stats and channel URL.
- AI assistant workspace with text/audio input if supported by backend.

### Required backend behavior

Implement:

- `POST /mini-app/api/bootstrap`
  Validate auth, create/update user, apply referral start_param, return user, balance, packages, models, history, saved references, notifications and server-confirmed roles.

- `POST /mini-app/api/upload`
  Accept multipart and JSON/base64 fallback, validate auth, file kind, MIME and size, persist owner-bound file/reference, return durable URL and reference metadata.

- `POST /mini-app/api/generate-image`
  Validate auth, model, prompt, references, source feed/prompt IDs, cost and balance. Debit atomically, create task, launch provider, refund on immediate failure.

- `POST /mini-app/api/generate-video`
  Same as image, plus model-specific duration/ratio/scenario/reference validation.

- `POST /mini-app/api/generate-motion`
  Validate image/video references, quality, duration and cost. Debit atomically and launch provider.

- `POST /mini-app/api/task-detail`
  Validate auth and owner/public visibility. Return complete task detail without leaking hidden prompt/trend data to unauthorized viewers.

- `POST /mini-app/api/create-payment`
  Validate package/provider/promo/email, create transaction before/with provider invoice, return payment URL or Telegram Stars invoice URL.

- `POST /mini-app/api/ai-assistant`
  Validate auth, message/audio limits and supported formats. Return safe assistant response.

- Feed/profile/prompt routes with server-side authorization and visibility checks.

- Admin routes with repeated server-side admin checks.

### Deep-link contract

Support these start params unless the target product intentionally changes them and updates both bot links and frontend parsing:

```text
ref_{REFERRAL_CODE}
profile_{REFERRAL_CODE}
posts_{REFERRAL_CODE}
feed_{GENERATION_ID}
remix_{GENERATION_ID}
prompt_{PROMPT_ID}
task_{TASK_ID}
{payload}_ref_{REFERRAL_CODE}
```

Backend link builders and frontend parser must share tests for every format.

### Security requirements

Mandatory:

- Validate Telegram initData HMAC server-side for every private/mutating endpoint.
- Enforce `auth_date` expiry.
- Never accept `telegram_id`, `user_id`, `is_admin`, `credits` or price from frontend as authority.
- CORS allowlist only; do not echo arbitrary origins with credentials.
- Media gateway must require auth or signed short-lived URLs.
- Store task ownership and check it for detail/media/private actions.
- Atomic debit is the only permission to launch paid generation.
- Payment webhooks must validate provider signature and be idempotent.
- Uploads must be owner-bound, size-limited and MIME-sniffed.
- SSRF protection for all server-side URL fetches.
- Logs must redact tokens, initData, provider secrets and full user media URLs when sensitive.
- Browser auth fallback must verify Telegram Login signature and create short-lived session/initData representation only.

### Tests and quality gate

Minimum frontend tests:

- loader before bootstrap;
- locked gate after auth timeout;
- live state after bootstrap;
- no fake balance/history after failed bootstrap;
- deep-link parsing;
- payment payload;
- task detail polling/update;
- feed/remix/prompt privacy contracts;
- upload validation UX.

Minimum backend tests:

- valid/invalid/expired initData;
- bootstrap response shape;
- upload MIME/size/owner binding;
- image/video/motion validation failures;
- atomic debit race;
- immediate provider failure refund;
- task detail owner/non-owner;
- media gateway owner/non-owner/public;
- payment create and webhook idempotency;
- admin endpoint denial for non-admin;
- CORS allowlist.

Minimum E2E/smoke:

```text
[ ] Static app opens under /mini-app/
[ ] Telegram initData bootstrap succeeds
[ ] Browser gate appears outside Telegram
[ ] Upload reference succeeds
[ ] Image generation queues and balance updates
[ ] Video generation queues and balance updates
[ ] Payment link/invoice opens
[ ] Task detail refreshes from queued to done
[ ] Feed opens and only allowed actions are visible
[ ] Non-admin cannot call admin actions
```

Quality commands for a Next.js/Python target should be equivalent to:

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm test
npm run build
test -f out/index.html

cd /path/to/backend
python -m pytest
python -m compileall -q bot scripts
```

### Deployment requirements

- Serve frontend as static export.
- Configure `basePath` and `assetPrefix` if hosted under `/mini-app`.
- HTML must be `no-store/no-cache`.
- Hashed chunks can be immutable.
- Do not delete old chunks immediately after deploy; Telegram WebView can keep old HTML.
- Proxy `/mini-app/api/*` to backend over HTTPS or trusted private network.
- Keep backend runtime behind Nginx/firewall; do not expose raw app port publicly.
- Ensure upload/proxy timeouts fit large media uploads.

## Smoke commands for this repository

Frontend:

```bash
cd /root/tanya/banano_kling/frontend/miniapp-v0
npm run lint
npm test
npm run build
test -f out/index.html
```

Backend:

```bash
cd /root/tanya/banano_kling
python -m compileall -q bot scripts
pytest tests/ --ignore=tests/live -m "not live_smoke" --tb=short
```

Production API proxy auth boundary:

```bash
curl -i -X POST \
  https://cdn.chillcreative.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Expected: auth error (`401/403`) with JSON body, not proxy/HTML error.

## Final recommendation

For a new project, implement parity around capabilities and invariants, not file structure. The most important design change is to make billing, media authorization and generation launch transactional service boundaries instead of endpoint-local logic.

