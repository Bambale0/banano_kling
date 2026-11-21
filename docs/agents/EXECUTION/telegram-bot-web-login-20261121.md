# Telegram bot confirmation for NEUROMIX browser login — 2026-11-21

## Scope and baseline
- Production branch: `tanyapi`; audited starting head: `380a70c5350431c2229f9fc9d65eb8101530d894`.
- User requirement: on `/login`, click Telegram, open **existing** NEUROMIX bot, display **Confirm / Decline** in a private chat, return to browser and open the existing web studio.
- No VK changes; Yandex, Google, email, OIDC fallback, Telegram Mini App, financial ledgers and provider integrations must continue working.

## Verified preflight
- `bot/web_auth.py` already provides `nm_web_session` HttpOnly cookies, `shared_account_identities`, legacy Telegram links and `_complete_identity()` with conflict controls.
- `bot/browser_auth.py` provides Telegram OIDC and old signed login widget. Neither presents buttons from the product bot. `_browser_bot_username()` obtains the bot username via the Bot API; no hardcoded bot name.
- `bot/handlers/common.py` is the aiogram `/start` and callback flow; it is also used for referral and payment deep links.
- `/login` is a statically exported Next frontend in `frontend/miniapp-v0/components/landing-login-panel.tsx`.
- `.github/workflows/ci.yml` runs `pytest tests/` and changed Python Ruff; Mini App workflows run frontend checks and Playwright on PRs to `tanyapi`.
- No new Telegram actor, wallet migration, money credit or user-provided Telegram ID is needed.

## Implementation contracts
1. POST `/mini-app/api/web-auth/telegram-approval/start` with same-origin browser request initiates the request, creates opaque 43-char Telegram deep-link secret, stores **hash only** and request/browser binding. A short-lived HttpOnly/Secure/SameSite=Lax path-scoped cookie identifies the initiating browser. A 6-digit comparison code is rendered on both screens.
2. `/start auth_<secret>` in private bot chat shows `Подтвердить` / `Отклонить`. Callback sender comes only from authenticated Telegram update, never the website. No generation/FSM state is cleared.
3. The browser polls `GET .../status?id=<opaque id>`; only the matching browser cookie can read it.
4. POST `.../claim` must have same-origin header, matching browser cookie, an unexpired `approved` record and atomic compare-and-swap to `consumed`; then reuses `web_auth._complete_identity()` for the established Telegram shared account. There is no balance mutation.
5. POST `.../cancel` denies the request. New start invalidates any pending or approved challenge for the same browser. Expired and reused requests do not mint web sessions.
6. Backend stores five-minute requests and purges challenges older than 24 hours beyond expiration upon new issuance. Browser-specific issue limit is five per ten-minute window; production edge IP rate limiting is separately recommended.
7. Existing Telegram OIDC login stays accessible as an explicit backup; Yandex, Google and email unchanged.
8. Logs include the opaque request ID and decision, not the deep-link secret or web-session token.

## Acceptance tests
- Existing TG owner signs in through button -> bot callback -> browser creates original owner session -> `/login` enters studio.
- Existing and new TG users: correct shared-account binding, no synthetic TG ID and no wallet modification.
- Request rejected without same-origin browser request, wrong cookie, unknown ID, expired token, repeated callback, denied or canceled request, other browser, simultaneous two claims.
- Bot buttons only work from their authenticated sender in a private chat. Revoked old web sessions unaffected.
- Native Telegram Mini App and other browser providers continue working.
- No callback, popup or browser polling loops on network errors, stale requests or cancellation.
- Frontend and backend CI required; live end-to-end Telegram device confirmation and exact SHA production smoke still required before claiming deployment.

## Execution
- [x] Audit current `tanyapi` GitHub code and repo AGENTS/README; inspect relevant `Bambale0/skills`, `Bambale0/claw`, and `anthropics/skills` guides.
- [x] Add persistent challenge+cookie endpoints and reuse verified existing identity.
- [x] Add `/start auth_` and private callback handlers, preserving existing /start behavior.
- [x] Add primary website UI with comparison code, bounded polling and cancellation; preserve OIDC fallback.
- [x] Add backend HTTP/Telegram mock regression matrix and frontend component tests.
- [ ] Run exact-head protected GitHub CI, Ruff, full relevant Python tests, TypeScript, Jest and browser E2E; fix any failures.
- [ ] Verify native PostgreSQL concurrency and production-safe migration.
- [ ] Merge into `tanyapi` only with green protected checks.
- [ ] Confirm exact SHA backend/frontend deploy, endpoint responses, actual Telegram confirmation and logs on production.

## Status / limitations
- The connector supports source review and GitHub commits. It does not provide local Git repository checkout or direct production browser/device smoke in this session.
- This document is an implementation ledger, **not** proof that any unrun test or production deployment passed.
- Telegram callback button phishing remains a social-engineering possibility: the 6-digit code must match the user's browser; never approve unsolicited messages. The cookie prevents remote claim of the challenge in another browser, not an approved challenge deliberately initiated by an attacker with a cooperating Telegram user.
- No destructive changes, new payment/generation calls, or production credential changes are required.
