# NEUROMIX — native profile web identities and truly independent web entry

Date: 2026-11-21. Baseline: `tanyapi@c806d7f329456de53395fc4ea9185e40843138a0`.

## Request and root cause

User-visible Telegram Mini App profile still rendered an obsolete «Связанные аккаунты» Telegram/VK card and a Telegram-only website entry, despite the existing OAuth and web-only product path.

Historical evidence:
- PR #419 introduced the TG/VK profile card and old two-party deep-link flow.
- PR #626 is still **Draft, mergeability dirty**, using a retired static login page. Its underlying secure email OTP, web auth, and schema have since entered `tanyapi` through PR #643 and subsequent work; do NOT merge the stale draft.
- PR #643 shipped Yandex OAuth via code+PKCE and HttpOnly sessions.
- PR #656 shipped independent browser workspace on the same Next /mini-app bundle (`?web=1`) and account-aware /login; PR #636 shipped public /login routes.
- PR #669 documents unresolved web-funds/data-loss risk in cross-account merges; protections reused and strengthened below.

## Existing APIs reused

`/mini-app/api/web-auth/config`, `start/{google|yandex}?intent=link`, `callback/{google|yandex}`, `email/start`, `email/verify`, `web_auth_sessions`, `web_auth_identities`, native verified Telegram credentials and account owner resolution. No parallel auth provider or email delivery service.

## Changes

1. Profile uses a new provider-state card with Yandex ID, Google and email only; never shows VK/TG as options to link on this surface. Legacy VK-specific account flow outside the native Telegram profile stays backward compatible.
2. Native Mini App can obtain the existing HttpOnly browser session by POSTing fresh **real Telegram-signed initData** through `/web-auth/native-session`. Strict HTTPS same-origin POST, 24-hour native signature freshness, matching existing Telegram Mini App verification, rejects synthetic browser_/webstudio_ launch credentials. A stale independent browser cookie for a different account gets HTTP 409, never overwritten.
3. Provider buttons use existing server state, and are disabled when OAuth/email delivery credentials are absent. Email form reuses verified six-digit OTP with `intent=link`, server-side expiry, rate limit and one-use check.
4. Login honours explicit `?web=1` even when linked to Telegram; other legacy Telegram launches retain existing precedence. Profile opens explicit independent website via Telegram WebApp.openLink when available, fallback `target=_blank`.
5. Financial protections adapted from PR #669: before a Telegram or web-web identity merge, inspect live funds, invoices and completed/queued web tasks, including aliases. Lock catalog then *both* relevant account rows in stable order; refuse links with open financial liabilities instead of hiding funds, orders or results. Revalidate invoice creation under account row lock to close link/checkout TOCTOU. No old balances transferred or multiplied.

## Production provider readiness (read-only, at audit time)

- Yandex OAuth client ID/secret: configured.
- Google OAuth client ID/secret: not configured.
- Resend/SMTP email sending provider: not configured.
- Public website origin: configured.

The email OTP UI can be used after a real verified sender and delivery credentials are provisioned in the existing private config. Do not fabricate successful email delivery or reveal secrets. Web-only users can still authenticate through Yandex without Telegram.

## Safety invariants / tests

- No credit, wallet claim, legacy financial cutover or payment-provider calls in this change.
- Native signed owner and any existing cookie must refer to the *same* canonical account.
- No unverified OAuth/email link, no automatic email matching/merging.
- Two funded or historically paid identities never merge until financial cutover reconciliation is approved.
- No return of another user's identity or account linking state.
- Native Telegram delivery and legacy pricing/auth remain unchanged.
- Focused backend + frontend suites, TS/ESLint/Ruff, GitHub CI and exact-SHA production deploy smoke are required before declaring release.

## Rollback

Revert the merge commit/PR for UI/native-session routing; the change does not migrate balances or add schema. Existing web login/auth and Telegram native studio continue to function. Do not revert underlying Yandex/email auth PRs.

## Verified local acceptance

- Backend subset: 95 passed, 18 skipped (web auth/native session, Yandex/Google/email identity, email OTP, payment guard, wallet/link, generation contracts). 2 existing warnings. Python Ruff and compilation succeeded.
- Frontend focused: 20 passed, TypeScript no-emit, changed-file ESLint passed.
- Optimized Next.js 16 static export compiled and generated /login and /.
- Chromium Playwright landing-login E2E: Yandex OAuth, Google OAuth, email OTP, linked Telegram entry, independent browser at 320/390/768/1440px, referral preservation, logout/history, explicit web-only link on Telegram-linked Yandex without web-auth/studio bridge all passed.
- Full Jest regression on this branch: 129 suites / 1,064 tests passed, 2 suites / 3 tests failed (Genjutsu stale price tests and Unicode trend title). The exact same 3 failures reproduced using unmodified clean detached baseline c806d7f329456de53395fc4ea9185e40843138a0 (3 fail, 55 pass in those 2 suites). They were not edited to mask failures; GitHub required CI will provide final release gate.

Important production limitation: Google OAuth and email OTP require missing provider configuration. Until configured, UI truthfully shows them unavailable, and no email has been sent. No live user money was touched. The new native-session and account-merge guard have not yet been verified by a real end-user OAuth consent.
