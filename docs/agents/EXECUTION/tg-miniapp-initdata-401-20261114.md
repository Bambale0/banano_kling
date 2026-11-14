# Telegram Mini App bootstrap 401 / stale initData regression — 2026-11-14

## Baseline and observed incident

- Baseline: `tanyapi@7f63fb5a81a85fc13cd9e633f27268874f36b44b`.
- User reports Telegram Mini App at `https://neuromixbot.com/mini-app/` is unusable; no symptom screenshot or real signed `tgWebAppData` attached for this incident.
- Read-only production on 2026-11-14: frontend HTML HTTP 200, Telegram SDK HTTP 200, eight HTML-referenced JS/CSS files all HTTP 200. `/health` HTTP 200 with S3 media. Container `banano-kling-bot` healthy, 0 restarts, image revision exact baseline. Frontend revision matched baseline. Runtime `config.mini_app_url` points to the same URL.
- For a recent 20-minute log window the last 5000 lines contain **87 POST /mini-app/api/bootstrap status=401**, **zero 200**. Some are operator's deliberately unsigned probes. The source of every failed request cannot be attributed without correlation, so this is evidence of broad auth failure traffic, **not** proof all 87 are genuine clients.
- Browser login `/mini-app/api/browser-auth` also returns 200 for some calls. Read-only synthetic Python probe in the production container confirms `_build_browser_init_data` signs payloads which `_validate_init_data` accepts under the same `config.BOT_TOKEN`. The callback-to-client navigation still requires authenticated browser testing.
- Telegram Bot API `getChatMenuButton` without a chat ID returned `type=commands`. This does not prove which per-chat/inline button or startapp URL an end user clicked.

## Root cause found in frontend source (specific stale-token failure class)

- `frontend/miniapp-v0/lib/api.ts:getInitData()` preferred the first URL/prehydration/storage snapshot and later stored raw initData in `__BANANO_TG_INIT_DATA__` and `sessionStorage` **without freshness checks**.
- `getInitDataFromLocation()` also accepted prior `__banano_initial_hash`/`__banano_initial_search` snapshots unconditionally. A stale signed launch could shadow fresh `window.Telegram.WebApp.initData`; backend then rejects its `auth_date` after 24 hours, leaving the app locked on Telegram login.
- This is a demonstrable code path, not yet a proven unique cause of the user's exact device failure. Other possibilities remain: expired/invalid bot signature, unsupported WebView link, wrong launch URL, blocked SDK in specific network.

## Fix and invariants

1. Add nine regression cases covering SDK fresh vs stale snapshot, newer signed SDK vs still-valid older snapshot, expired/malformed persisted credentials, fresh cache recovery for browser login, URL hash login and SDK delay.
2. Prefer the candidate with the newest `auth_date` when both live URL and Telegram SDK credentials are available; never let older cached tokens shadow a fresh signed launch.
3. Reject expired persisted sessionStorage, memory and stored location snapshots using the same 24-hour window as backend `_validate_init_data`. Expired and malformed cache is cleared rather than triggering continuous rejected bootstrap requests.
4. Preserve the native VK memory token precedence exactly as before and preserve the normal Telegram, direct URL and browser-login flows.
5. The frontend only selects likely-fresh tokens. It **never validates an actor, treats unsigned data as authenticated, or replaces the backend HMAC/user/authorization checks**.
6. Update existing platform-session test to use a structurally valid fresh cached Telegram launch while preserving its original VK-first/TG-restoration assertion; new dedicated regression explicitly rejects the old malformed token.
7. Add both test suites to the explicit protected Mini App workflow Jest list, away from concurrent VK #521 changes.

## Release and acceptance

- Code and tests committed test-first to feature branch. No local failing test execution was possible before edits; **do not claim measured RED**. Protected CI must run Jest, build TS, both TG/VK static exports, browser E2E, backend/regression/Docker release checks on latest head.
- Protected squash auto-merge only when current required GitHub CI is green. Check image + TG/VK frontend exact merge SHA and health after deployment.
- Real Telegram WebView acceptance requires actual fresh signed Telegram-only startapp launch, verify user, balance, tabs and task history, and that the 401 rate subsides; optional browser-login fallback and Telegram open gate regression.
- Do not modify bot token, payment provider, prices, DB, VK feature flags or any user identity. No production mutation before CI/release.
