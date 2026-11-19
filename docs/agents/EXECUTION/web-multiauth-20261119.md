# WEB-авторизация NEUROMIX — 2026-11-19

Baseline: tanyapi SHA 31cd91ba3287056a6b9bd1eaeb443125a03d9412.
Task branch: feature/web-multiauth-20261119. Release only via PR into tanyapi.

## Implemented/changed

- Standalone /login: Google, Yandex, Telegram Login Widget and email six-digit OTP UI; disabled providers are shown as unavailable.
- OAuth Authorization Code + S256 PKCE, server-side state with one-time consumption, SameSite Lax state cookie and fixed HTTPS redirect_uri.
- Email one-time 6-digit code: keyed HMAC stored in DB (not the code), 10-minute expiry, five failed attempts, 60s resend cooldown, per-email and per-IP durable throttling. Code entered inline on /login; Resend HTTPS API by default, SMTP available as a fallback.
- Google/Yandex stable provider subject and separate web_auth_identities; Telegram reuses verified legacy identity, no fake Telegram ID.
- Shared-account membership for linked providers, HttpOnly Secure session cookie, bounded server-side sessions.
- Redirects only to local app/login paths. Referral context preserved from the marketing page to /login to Mini App.
- Nginx exact /login and /login/ route, release rollback and smoke.
- Backend routes are registered before legacy /mini-app/api catch-all.

## Prerequisites

At audit time none of WEB_AUTH_GOOGLE_CLIENT_ID, WEB_AUTH_GOOGLE_CLIENT_SECRET,
WEB_AUTH_YANDEX_CLIENT_ID, WEB_AUTH_YANDEX_CLIENT_SECRET, WEB_AUTH_PUBLIC_ORIGIN,
WEB_AUTH_SMTP_HOST, WEB_AUTH_SMTP_USERNAME, WEB_AUTH_SMTP_PASSWORD were set.
They MUST be configured through the secret manager, not committed.

Required public origin: WEB_AUTH_PUBLIC_ORIGIN=https://neuromixbot.com
Google callback: https://neuromixbot.com/mini-app/api/web-auth/callback/google
Yandex callback: https://neuromixbot.com/mini-app/api/web-auth/callback/yandex
Email provider (recommended): WEB_AUTH_EMAIL_PROVIDER=resend
WEB_AUTH_RESEND_API_KEY: sending-only token from Resend (secret manager)
WEB_AUTH_RESEND_FROM: verified sender on a domain you control, e.g. NEUROMIX <verify@neuromixbot.com>
WEB_AUTH_EMAIL_CODE_SECRET: dedicated long random secret for HMAC (optional when BOT_TOKEN is set, but recommended)
Verify sender domain with Resend's DNS (SPF/DKIM and preferably DMARC). Never use a sender domain belonging to another entity.

Alternative SMTP: WEB_AUTH_EMAIL_PROVIDER=smtp
WEB_AUTH_SMTP_HOST, WEB_AUTH_SMTP_PORT=587, WEB_AUTH_SMTP_FROM
WEB_AUTH_SMTP_USERNAME and WEB_AUTH_SMTP_PASSWORD when required.
No provider key or SMTP password may be stored in source control.
Provider acceptance (Resend email ID / SMTP response) does NOT guarantee delivery to a mailbox.
No automatic retries on an ambiguous HTTP timeout; Resend Idempotency-Key allows safe explicit reconciliation if necessary.

Optional bounded runtime settings (safe defaults in parentheses):
- WEB_AUTH_EMAIL_CODE_TTL_SECONDS (600)
- WEB_AUTH_EMAIL_RESEND_COOLDOWN_SECONDS (60)
- WEB_AUTH_EMAIL_RATE_WINDOW_SECONDS (900)
- WEB_AUTH_EMAIL_SENDS_PER_WINDOW (3)
- WEB_AUTH_EMAIL_IP_SENDS_PER_WINDOW (15)
- WEB_AUTH_EMAIL_MAX_CODE_ATTEMPTS (5)

All OTP challenges and request-rate counters are stored in the shared database,
not per-worker memory. Do not log or display raw codes in observability.
A provider response ID means accepted for processing, not delivered to inbox.

Telegram Login Widget domain requires BotFather configuration.

## Explicitly not yet fulfilled

Web-only accounts cannot safely run legacy Telegram-owned generations,
payments, deliveries or referral bookkeeping. They need an independent
authenticated web actor, shared wallet/task owner and media-delivery adapter;
do not manufacture Telegram numeric IDs to work around that.

Linking an unclaimed provider to the current signed-in shared account works.
If the provider belongs to a different account, a live browser session of the
source account plus a fresh verified provider identity on the target are needed.
The existing LinkService wallet-preserving transactional merge is used. Any
ambiguous legacy identity, duplicate provider identity, commercial-settings
conflict or invalid session rejects the merge without transferring funds.
Equal email must never merge balances. Legacy Telegram/VK flows remain intact.

## Acceptance checks

- /login 200, cache no-store; /mini-app and health intact.
- Providers shown as enabled only when configured.
- OAuth state+PKCE callback succeeds/replay fails; no open redirect.
- Email 6-digit code in a real message, inline field, auto-submit on sixth digit, consumed once; 5 guesses, cooldown and durable rate limits. Provider delivery errors must not authenticate.
- Telegram signed widget payload and browser Mini App launch preserved.
- Account linking only after provider verification, no takeover.
- Ref entry /?ref=CODE -> /login?ref=CODE -> /mini-app/?ref=CODE.
- Tests, lint/compile and Nginx validated in CI.
- Production exact SHA and end-to-end provider auth smoke only AFTER OAuth
  secrets have been configured. Do not claim provider login works beforehand.

## Rollback

Restore backed-up Nginx/landing, undo application changes with a revert PR;
do not delete identity tables, production users, or financial records.
