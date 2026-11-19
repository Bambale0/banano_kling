# Yandex ID browser login — staged NEUROMIX activation (2026-11-20)

## Baseline and scope
- Starting branch: tanyapi SHA acc70099b4a0ffeba9724e054d203368f52d7b30.
- Yandex OAuth credentials were verified present (nonempty) in production .env on 2026-11-19; existing Docker container was not restarted.
- PR #626 contained provider back end but an outdated standalone static login and no web-native actor.
- This branch uses existing Next /login, keeps Telegram OIDC and signed login, and registers provider API before legacy API catch-all.

## Server-side identity guarantees
- Authorization code + PKCE S256, bounded state flow and same-site secure HttpOnly browser cookie.
- Verify Yandex stable subject using https://login.yandex.ru/info and `Authorization: OAuth <access_token>` per official Yandex ID docs (never log token).
- Never merge web identities on equal email.
- Existing Telegram wallets and generation ownership remain tied to real verified Telegram user IDs.
- Yandex-only sessions are explicitly forbidden from minting Telegram Mini App credentials: 409 needs_telegram_link.
- With verified account linking via a fresh signed Telegram widget payload plus live web session, Yandex can later sign into the same Telegram-owned studio without redoing Telegram approval.
- Explicit linking uses existing transactional wallet-preserving identity merge and replay/ownership protection.
- CSRF origin check, account session validation, and db-owned user lookup apply to studio credential exchange.

## User experience and limitation
- Yandex button only appears when the server reports that provider credentials are configured.
- A new Yandex-only account sees a truthful link-Telegram prompt, not a broken /mini-app/ or a fabricated Telegram actor.
- Previously verified linked account signs in via Yandex, then opens the existing Mini App.
- Independent Yandex-only generation, payment, delivery and referral support remains NOT implemented. Requires a first-class web-native actor and money ledger; do not describe this release as full independent website support.
- Google/email methods remain disabled until separately configured.

## Validation
- Python tests: tests/test_web_auth_contract.py, test_web_auth_identity.py, test_email_otp.py, test_browser_auth.py, test_telegram_oidc.py, test_public_landing.py.
- Next production static export build and React lint.
- Browser E2E: responsive page, Yandex provider enabled/referral, Yandex-only -> verified Telegram link, linked -> existing Mini App, auth error fallback and existing payment return-to.
- Production acceptance: exact deployed SHA, /login 200, web-auth/config 200 with yandex enabled, /start/yandex redirects to Yandex with correct callback, studio 401 for unauthenticated, linked and unlinked behaviors, Telegram auth works.
- Live Yandex user-consent authorization requires an actual user login; cannot be simulated with just Client ID/Secret.

## Deployment
- Normal PR to protected tanyapi with native squash auto-merge after all required CI gates.
- No direct edit of production database, account credits, or secrets; production .env already contains credentials.
- Do not touch happy-fox.online or any unrelated domain.
- Rollback by reverting PR and redeploying previously verified SHA; preserve identity database tables rather than deleting user data.
