# Telegram one-click browser sign-in (2026-11-19)

## Current issue / root cause
The public /login uses the archived Telegram Login Widget (telegram-widget.js?22).
It can require a phone number and another web authorization step. The existing
server-side signed widget verifier is correct but cannot make that old widget
open a native Telegram approval prompt.

## Design
- Prefer the official Telegram Login **OIDC JavaScript library** (telegram-login.js)
  and trigger its popup *synchronously from an explicit click*. Mobile/desktop
  clients with Telegram support can accept the Telegram authorization prompt.
  Browser popup blocking prevents safe unconditional auto-launch on page load.
- **Do not request the phone scope**. Request only profile. The user has one
  explicit Telegram consent action; there is no way to bypass Telegram consent.
- Fetch the **explicitly configured BotFather Client ID** from
  TELEGRAM_OIDC_CLIENT_ID and a fresh per-browser nonce from the existing
  config API. Never assume the numeric BOT_TOKEN prefix is the OIDC Client ID.
- Bind nonce to a Secure, HttpOnly, SameSite=Lax short-lived cookie; OIDC SDK
  returns an id_token to the site; POST to existing browser-auth endpoint.
- Verify RS256 signature against Telegram JWKS with bounded network timeout,
  issuer, exact audience, expiration, issue time, numeric ID and nonce cookie.
- Mint the existing signed browser Mini App initData only after verification,
  then navigate via replace to /mini-app/ and preserve startapp context.
- Keep the legacy signed Telegram widget behind an explicit fallback link;
  when OIDC is not configured or its SDK cannot load, reveal the legacy login
  automatically rather than leaving a disabled one-tap button.
- Native Telegram WebView launches carrying tgWebAppData still bypass browser login.

## External setup requirement
In @BotFather → bot → Login Widget, add the allowed origin
https://neuromixbot.com (and the URL(s) BotFather requires for browser login).
Set TELEGRAM_OIDC_CLIENT_ID to the **Client ID displayed by BotFather**
(in the existing secret-backed deployment environment). This configuration
is required to enable OIDC; before it is set, the previous legacy widget
remains available.
Telegram's signing algorithm must be RS256 (the official default).

No Client Secret is needed for this SDK ID-token flow. Never place BotFather
secrets in frontend code. Verify production can reach
https://oauth.telegram.org/.well-known/jwks.json with a 5s timeout.

## Tests and release gates
- tests/test_browser_auth.py: legacy HMAC and WebApp signature unchanged.
- tests/test_telegram_oidc.py: valid RSA ID token, tampering, unknown key,
  wrong nonce, issuer, audience, iat/exp and empty nonce.
- frontend/miniapp-v0/e2e/landing-login.mjs: login button calls SDK, sends
  id_token, redirects with session, preserves startapp; missing BotFather
  Client ID and SDK failures automatically reveal the legacy login.
- CI: Python safe suite, Next build/type/lint, Chromium browser E2E.
- Production: confirm exact deployed SHA, /login loads new SDK with CSP,
  test a real Telegram app approval -> /mini-app/ bootstrap. Cannot claim
  the provider-side approval is verified without a real user consent.

## Risks and rollback
- Some browsers/Telegram clients still show phone login when the app is not
  installed/authorized or third-party popup is blocked. Leave a clear fallback.
- Misconfigured BotFather Allowed URLs or an outdated BotFather OIDC Client ID
  will block approval; do not conceal this with fake auth data.
- If JWKS cannot be fetched, fail closed with HTTP 503; never mint a session
  from an unverified decoded JWT.
- Revert this focused PR to return to the original signed Telegram widget.
- No schema, wallet, pricing, referral or payment changes.
