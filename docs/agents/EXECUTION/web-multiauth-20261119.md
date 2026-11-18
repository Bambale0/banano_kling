# WEB-авторизация NEUROMIX — 2026-11-19

Baseline: tanyapi SHA 31cd91ba3287056a6b9bd1eaeb443125a03d9412.
Task branch: feature/web-multiauth-20261119. Release only via PR into tanyapi.

## Implemented/changed

- Standalone /login: Google, Yandex, Telegram Login Widget and email magic-link UI; disabled providers are shown as unavailable.
- OAuth Authorization Code + S256 PKCE, server-side state with one-time consumption, SameSite Lax state cookie and fixed HTTPS redirect_uri.
- Email one-time 256-bit bearer (only hashed in DB), 10-minute expiry, TLS SMTP, bounded sending.
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
Email: WEB_AUTH_SMTP_HOST, WEB_AUTH_SMTP_PORT, WEB_AUTH_SMTP_FROM;
WEB_AUTH_SMTP_USERNAME and WEB_AUTH_SMTP_PASSWORD when required.

Telegram Login Widget domain requires BotFather configuration.

## Explicitly not yet fulfilled

Web-only accounts cannot safely run legacy Telegram-owned generations,
payments, deliveries or referral bookkeeping. They need an independent
authenticated web actor, shared wallet/task owner and media-delivery adapter;
do not manufacture Telegram numeric IDs to work around that.

Linking an unclaimed provider to the current signed-in shared account works.
If the provider belongs to a different account it is rejected and both
accounts must explicitly prove ownership before any financial merge is allowed.
Equal email must never merge balances. Legacy Telegram/VK flows remain intact.

## Acceptance checks

- /login 200, cache no-store; /mini-app and health intact.
- Providers shown as enabled only when configured.
- OAuth state+PKCE callback succeeds/replay fails; no open redirect.
- Email ticket single-use; delivery failures do not create identities.
- Telegram signed widget payload and browser Mini App launch preserved.
- Account linking only after provider verification, no takeover.
- Ref entry /?ref=CODE -> /login?ref=CODE -> /mini-app/?ref=CODE.
- Tests, lint/compile and Nginx validated in CI.
- Production exact SHA and end-to-end provider auth smoke only AFTER OAuth
  secrets have been configured. Do not claim provider login works beforehand.

## Rollback

Restore backed-up Nginx/landing, undo application changes with a revert PR;
do not delete identity tables, production users, or financial records.
