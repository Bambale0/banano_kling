# VK app community context for public share links — 2026-11-11

## Incident evidence
- Signed VK bot open_app and browser sign-in redirect use app54880352_-239915802, but public trends and feed used app54880352 without the community suffix.
- User screenshot showed an actual share link missing the suffix and a desktop VK platform error. The URL bug is confirmed, but it does NOT prove it is the only cause of desktop refusal. VK developer-console app visibility, testing group and desktop URL need independent acceptance. The configured user API token currently returns VK code 5 (expired).
- Shared VK shell is still gated off for VK-only users until complete native actor/domain adapters are ready. This PR is link routing only.

## Fix
- Extend generic public VK link helpers with optional validated community ID; reject invalid configured ID; preserve legacy apps without community.
- Backend public feed/trend links use the server-owned preview policy community ID, not browser-provided identity.
- Frontend uses server-authenticated app/community ID only after VK profile, keeps it memory-only and clears it on logout. A different VK app ID does not inherit the stored community.
- The VK share modal accepts safely scoped prompt links, without signed launch credential, token or VK user ID.
- Telegram link routes remain unchanged.

## TDD, acceptance and remaining
- RED: Python link builder rejected community ID; four Jest tests failed without frontend verified context.
- GREEN: actual VK trend and feed endpoints, helper validation, session/logout context, share modal. Backend 78 pass / 68 isolated PG skipped. Frontend 103 suites / 787 pass. TypeScript, scoped ESLint, VK static export and Chromium 430px/1280px smoke passed.
- Release via protected CI and exact SHA smoke. VK portal availability and RU client ERR_CONNECTION_CLOSED are separate unresolved gates, not verified by localhost.
