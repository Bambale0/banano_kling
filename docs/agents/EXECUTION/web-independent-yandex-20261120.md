# Independent browser identities — web studio foundation (2026-11-20)

## Scope / baseline

- Repository: Bambale0/banano_kling, production line: tanyapi.
- Base: 0aac0576fe1f403b391957dd802d1c45af8ff327 (#644).
- User journey: log in with Yandex ID from /login, land in /mini-app/ without having to log in through Telegram; optionally connect a previously existing Telegram identity.
- No work on dev, main, or other projects.

## Preflight facts / root cause

1. OAuth callback already creates an authenticated web_auth_sessions cookie attached to shared_accounts.id.
2. landing-login-panel.tsx previously allowed entry to the studio only when studio_ready meant a legacy Telegram link was present; Yandex-only identity received the Telegram link prompt.
3. Core Mini App bootstrap and generation (bot/miniapp.py) validate Telegram initData, access users.telegram_id, charge the legacy Telegram wallet, and deliver outputs through Telegram. Injecting a fabricated Telegram ID would create unsafe cross-account access, wrong charges and lost delivery.
4. Shared-account WalletService('live') is transactional but is **not wired to the current Mini App payment/generation/receipt pipeline**. The independent wallet must never be represented as or merged with legacy Telegram credits.
5. Existing WEB_AUTH_PUBLIC_ORIGIN, nm_web_session, same-site cookies, typed identity provider proofs, account linking, and logout revocation are retained.

## Implemented safe vertical slice

- Authenticated GET /mini-app/api/web-auth/account resolves the existing revocable cookie; returns a separate account ID, verified login methods, dedicated shared-account live-ledger snapshot and explicit can_generate:false. Anonymous and revoked requests return 401.
- Browser /mini-app/ selects independent Yandex-only web workspace via the server session and avoids Telegram widget gating. Explicit native Telegram launch still takes precedence. Linked users still use a fresh server-issued real Telegram initData via /web-auth/studio.
- /login redirects a verified Yandex-only visitor to the web workspace; voluntary ?link=telegram keeps an opt-in account-linking UI.
- Independent workspace displays the authenticated identity and distinct web wallet, allows a server-revoked logout, and explains that paid generation/top-ups are not available yet. It never charges or starts a paid task in this incomplete mode.
- No schema migration, provider secret, identity assignment, payment, or legacy wallet mutation.

## Verification (isolated worktree; no production data)

- Python (Docker image with isolated temp SQLite and network disabled): tests/test_web_auth_identity.py + tests/test_web_auth_native_entry.py — **22 passed**.
- Jest: web-account-entry.test.ts, web-account-workspace.test.tsx, browser-account-signout.test.ts — **17 passed**.
- TypeScript: tsc --noEmit — 0 errors.
- Next.js: CI=1 npm run build (static export, compile and production TypeScript) — success.
- Production deployment not attempted for this incomplete feature.

## Invariants and remaining work (blocks full release)

1. Introduce first-class web actor through the generation queue and callback/reconciliation layers, keyed by immutable shared_account_id, never by a fabricated Telegram ID. Persist jobs, owner checks, retries, terminal states and output links; no Telegram delivery assumption.
2. Connect web payments to this account's production ledger using a dedicated invoice/account-id mapping, signed webhooks, idempotent credit/capture/refund and exactly-once semantics. Never silently transfer funds from Telegram or VK.
3. Integrate configurable model tariff quotes, photo/video providers, reference uploads, history/detail, profile/feed, ownership and referrer attribution with explicit account scopes.
4. Verify identity linking (two fresh proofs), account merge semantics, reconciliation, existing legacy wallets, duplicate callbacks, provider outage, crash recovery, delayed expiry and real browser E2E.
5. Add migration/integration tests for both PostgreSQL and SQLite, full native Telegram regression and production rollback/smoke before enabling can_generate in any environment.

**Release gate:** this foundation should remain a draft PR until a separately validated independent generation/payment path exists or the operator explicitly accepts an account-only first release. Do not describe Yandex-only photo/video generation as working.


## Extension: cross-platform login, voluntary linking, independent referrals and history

Changes added after the first PR commit:

- Google OAuth and Email OTP are visible in the browser login UI only if
  the backend configuration enables those providers. Email OTP stays
  browser-memory-only, rate-limited and HMAC verified; OAuth PKCE/state remains.
- Telegram OIDC and the verified legacy signed Login Widget both use the
  shared-account namespace. Linking requires both an existing authenticated
  session and fresh proof of the secondary provider. OIDC nonce cookie scope
  is preserved at /mini-app/api/browser-auth; old incompatible Telegram
  mappings fall back to verified legacy browser-auth without forced merges.
- Account management is available at /account/ even when Telegram is linked.
  Explicit native Telegram launches retain priority over browser cookies.
- GET /web-auth/referral issues a stable messenger-independent
  /login?ref=NW... URL. Attribution is recorded only for first-time verified
  registrations. No credit/reward is given merely for a registration.
- GET /web-auth/history and /web-auth/task/{task_id} use a separate
  web_generation_tasks store and account ownership checks. The web UI
  supports read-only history, 20-item pagination with tied timestamp handling,
  and safe HTTPS media results. Provider task producer is NOT yet connected.
- Playwright E2E regression changed from an obsolete forced Telegram-link
  expectation to mandatory Yandex-only web access plus separate voluntary
  Telegram linking and existing linked-user handling.

Latest verification:
- Backend isolated Docker: 22 tests passed.
- Frontend Jest: 17 tests passed.
- Next.js production static export: success including /account/ page.
- Local browser Playwright landing-login E2E: all tested flows passed.

Verified anonymous production auth-config:
Yandex enabled, Telegram enabled, Google disabled, email disabled.
The latter two require provider credentials/configuration before go-live.

### Critical unimplemented paid lifecycle — blocking full release

- Immutable web invoice ownership, amount/currency verification and unique
  ledger credit after authenticated provider webhook, with replay and crash
  recovery. Legacy Telegram payment transactions cannot be reused blindly.
- Web-native provider queue: pricing from live settings, account-scoped
  reservation/capture/release/refund, idempotency, provider retries and
  reconciliation. Never create a synthetic Telegram ID.
- Full photo/video model support, reference uploads, history writes, web
  delivery, durable S3 output, entitlement checks, account merge/reconciliation,
  paid referral rewards and end-to-end regression/smoke tests.
- No independent web-paid generation or web topup endpoint is registered.
  Web-only can_generate remains false. Keep draft and do not merge into
  production until the entire paid lifecycle is independently tested.
