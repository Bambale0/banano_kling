# NEUROMIX /login — shadcn landing entry (2026-11-19)

## Goal and baseline
- Production source: `Bambale0/banano_kling:tanyapi`, preflight SHA `31cd91ba3287056a6b9bd1eaeb443125a03d9412`.
- User intent: the existing grunge **marketing** landing should have a dedicated public `https://neuromixbot.com/login` page built with the shadcn/ui component library already used by the Mini App.
- Before change `GET /login` returned 404; `/` and `/mini-app/` were separate working routes. The existing browser Telegram auth uses `GET /mini-app/api/browser-auth/config` and `POST /mini-app/api/browser-auth`, returning signed `init_data` upon server-side Telegram signature verification.
- Existing Next.js 16/React 19 static export is built with `basePath=/mini-app`. The app already has shadcn `Button`, `Card`, `Badge` and `Separator`. Installing a second React/shadcn build for the marketing root would duplicate dependencies and routes.

## Design and integration decisions
- Create `frontend/miniapp-v0/app/login/page.tsx` and scoped `login.css`. Import real shadcn components from `@/components/ui/*`. Grunge design uses existing brand textures and `/grunge-mobile-art-v1.webp` (already served at marketing root), warm-gold tape and bold display typography.
- Nginx exposes exact `/login` and `/login/` with `try_files /mini-app/login/index.html =404`. The actual static export exists at `out/login/index.html`; scripts/styles continue loading from the existing `/mini-app/_next/static`. No new Node production runtime.
- Telegram widget reads bot username from the existing authenticated-config endpoint; no hardcoded username, credentials or fake Telegram IDs. Signed widget data is sent through the unchanged `/mini-app/api/browser-auth`, then the backend's `init_data` is forwarded **only in the hash** of `/mini-app/`, not the query. The relative destination rules out an external redirect.
- Preserve the `startapp` referral launch parameter after login and pass signed Telegram Mini App launch hashes straight through. Include a persistent fallback to the existing Mini App if widget/config fetch fails; errors are localized. No auto-linking accounts by matching email.
- Root landing's explicit "Войти" entry points now link to `/login`; generation and studio CTAs continue to `/mini-app/`. Email, Google, Yandex ID are clearly "скоро": no fake OAuth flows.
- Auth routes are served only via exact Nginx locations; Mini App, fallback, business logic, payments, wallet, VK and S3 remain untouched.

## Verification completed before PR
- Baseline smoke: `GET /login` 404, confirming missing route; read production Nginx, Next basePath, static export, existing Telegram widget/browser-auth code.
- Isolated production build from a scratch clone with new files overlaid: `npm run lint` **0 errors** (3 pre-existing warnings elsewhere), `npm run build` succeeded, and `out/login/index.html` exists.
- `python3 -m unittest discover -s tests -p test_public_landing.py -v`: **18/18 passed**.
- `bash -n` for both updated deploy scripts: passed.
- Dry-run of the publisher's real Python Nginx patch against a copy of the live vhost: only `/login` and `/login/` were added, second run idempotent, existing Mini App routes preserved.
- Manual Chromium Playwright using the actual Next static export and simulated Nginx routes: **320, 390, 768 and 1440 px**; no JS/hydration exceptions or horizontal overflow, actual shadcn `data-slot` elements and JS/CSS assets detected.
- Mocked Telegram Login Widget callback → a single POST carrying `telegram_auth` to the existing API route → init_data in `/mini-app/` hash, with `startapp` preserved; 503 config error → localized retry/fallback to `/mini-app/`. The widget payload is a **test fixture**, not real Telegram authentication.
- Repeatable E2E added as `frontend/miniapp-v0/e2e/landing-login.mjs` and wired into the strict protected `ci.yml` browser gate; the script passed locally against the production export.
- UX screenshot review exposed collateral overlap from an absolute collage; corrected to in-flow art on desktop and hidden illustration on small screens so Telegram form is reached earlier.

## Production gate (not completed at document authoring)
1. Open PR targeting protected `tanyapi`, arm native squash auto-merge; four required CI checks must pass.
2. Production autodeploy from exact merge SHA. Fail closed if Next static export misses `login/index.html`.
3. Verify `https://neuromixbot.com/login` and `/login/` return HTML 200 with `id="login-page-title"` and Next bundles; public root remains correct grunge page.
4. Test `/mini-app/` and `/mini-app/api/browser-auth/config` 200, production Docker health, exact SHA of Mini App, `nginx -t`; report real login with a signed user as untested unless separately performed.
5. Inspect frontend logs and browser console; no destructive rollback of unrelated routes. Do not claim released without the above evidence.
