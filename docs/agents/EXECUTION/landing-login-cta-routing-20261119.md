# Landing entrypoint routing → /login (2026-11-19)

- **Baseline**: `tanyapi` at `3e853e1e974a9456049bfe039bc297e67bab21a1`.
- **Goal**: Public landing entry CTAs ("Войти", "Войти в студию", mobile actions and text links) lead first to `/login`, then after successful verified browser authentication redirect to `/mini-app/`.
- **Current state**: 9 landing links jumped to `/mini-app/` while the existing login button already used `/login`. The existing `LoginPanel` verifies Telegram via `/mini-app/api/browser-auth` and redirects with signed `tgWebAppData` in the fragment, preserving `startapp`.
- **Decision**: Reuse the existing login route. Do not change the OAuth/backend/session contract or force an authentication round trip for Telegram WebView launches containing signed init data.
- **Changes**:
  1. Route all 9 direct landing `href="/mini-app/"` CTAs to `/login`.
  2. Add Python landing regression coverage for desktop and mobile CTAs, forbidding direct public Mini App links.
  3. Expand Playwright to click the landing entry controls on desktop/mobile and assert the `/login` destination; retain the existing signed-login → `/mini-app/` scenario.
- **Scope**: No database migration; no payment, pricing, account-merging, or environment variable changes. Existing auth and Telegram launch redirects remain unchanged.
- **Verification plan**: `python -m pytest tests/test_public_landing.py -q`; frontend static build and `node e2e/landing-login.mjs`; PR CI including browser E2E; production smoke for root → /login and signed auth → /mini-app/ after deployment.
- **Security / edge cases**: Client-side links are not an authorization boundary; Mini App backend must continue authenticating requests. Preserve signed Telegram launch data and `startapp`; avoid logging auth payloads.
- **Release**: PR into `tanyapi`, required checks + auto-merge, production deployment only after CI, verify exact deployed SHA. Mark production verified only after smoke.
