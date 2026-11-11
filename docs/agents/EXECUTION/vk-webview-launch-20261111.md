# VK signed launch recovery, community-safe redirect and pre-hydration telemetry (2026-11-11)

## Evidence and root cause

- VK bot native `open_app` keyboard now emits `app_id=54880352`, `owner_id=-239915802` (tanyavk #76 is in production). The corresponding `w=app54880352_-239915802` URL format is *not* itself an error.
- Production Nginx access logs (reviewed **without printing any signed query, VK user ID, IP or token**) contain five GET `/` launches with VK query, all cryptographically valid under the configured VK app secure key. Two early launches reached session + profile HTTP 200; two 11:56 UTC loads fetched JS assets after a ~60-second gap but did not call the session endpoint. The latter failure is not conclusively attributable to JavaScript, VK browser behaviour or client network without stage telemetry; do not claim the SDK or provider is broken.
- Confirmed frontend bug: `app/layout.tsx` captures the signed initial VK query to `window.__BANANO_INITIAL_LAUNCH__`, but `accountLaunch()` and `AccountPlatformEntry` previously ignored it and read only mutable `window.location.search`. When VK host rewrites navigation before React, login never starts; RED tests reproduced this. The first-load signed snapshot is **memory-only**, never localStorage/sessionStorage.
- Confirmed backend bug: `/account-preview/vk-login` redirected to `https://vk.com/app{app_id}` even though the server-owned preview policy configures the community ID. On failure/re-entry this could silently lose the negative community owner context.

## Changes

- `vkLaunchData()` prefers the complete current VK signed launch; if missing/incomplete, it accepts only the initial in-memory shape containing app ID, user ID, timestamp and signature, then sends **exactly that original string** to the unchanged HMAC/TTL backend verifier. No trust is placed in frontend IDs, and no signed launch is stored persistently.
- Account entry and share URL generation use the same original signed snapshot when VK changes the location; a legitimate Telegram launch remains unchanged.
- VK login redirect preserves `https://vk.com/app{server_policy_app_id}_-{server_policy_community_id}`; query-supplied overrides are ignored. If no community is configured, the legacy generic app redirect remains intact.
- Add minimal stage markers `vk-html-ready`, `vk-react-mounted`, `vk-session-start`, `vk-session-ok`, `vk-session-failed` to the existing sanitized client log endpoint. Payload is only `{event, href: pathname}` with **no signed query, hashes, actor IDs, tokens or storage**. Stage logging cannot prevent authentication and is best-effort.

## Tests and release constraints

- RED→GREEN: one frontend test for dropped signed VK query; one for entry flow; one backend test proving community context; additional partial-query / current-query-priority / unsigned-snapshot / data-leak tests.
- Backend: 70 passed, 66 isolated-PG cases skipped; Ruff/compileall passed.
- Frontend: all 100 Jest suites / 771 tests passed, TypeScript and targeted ESLint passed, VK optimized export passed, four early VK/Telegram handshake tests passed.
- Real Chromium browser test passed on 430px and 1280px; injected a host-like location rewrite *between the inline early boot and React hydration* and confirmed the exact original credential reaches the mocked session endpoint, with no sessionStorage persistence. Real VK client click and billing E2E are still external acceptance gates.
- These changes do **not** provide the missing ten VK-owned domain adapters. `VK_FULL_APP_PARITY_ENABLED` remains OFF; no payments, credits, provider calls, schema migrations, Telegram routes, or native VK ledger were modified. Full independent seven-tab acceptance #451 remains open.
- Release only through protected `tanyapi` checks, exact-SHA deployment and production smoke; do not bypass CI failures caused by GitHub runner apt DNS failures. If re-entry telemetry indicates no `vk-html-ready`, suspect VK host/HTTPS/app settings; if only `vk-html-ready`, suspect JS/static load; if mounted but no session, inspect frontend; if session failed, inspect the redacted auth reason.
