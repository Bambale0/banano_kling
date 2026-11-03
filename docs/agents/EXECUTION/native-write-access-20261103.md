# Native Telegram write permission — 2026-11-03
Baseline: a982765cf1112461bc2982b672a72c373260ac52, tanyapi.

User revised acceptance: match screenshots: Allow → native Telegram permission → remain at exact Mini App source video/trend/form; retain referral attribution. Opening text chat is explicit recovery only. This supersedes the earlier primary /start navigation request. Account deletion is a separate blocked task and is not part of this implementation.

Preflight: BotWriteAccessGate currently opens a real t.me /start link, retains start_param and defers competing Radix layers. requestWriteAccess is available in bundled Telegram SDK (6.9+). confirmTelegramWriteAccess and authenticated /api/write-access already exist. Capability-only context refresh retains form DOM. Backend currently marks delivery available before proof and returns true on transient send failure: fix this while wiring native flow.

No schema/config/price/provider changes. Reuse existing API and bot getMe identity. No real bot sends or generations in automated tests. Preserve optional Skip and unsupported-client chat recovery, positive new-user eligibility, modal ownership and safe referral-only /start URLs.

1. Add regressions for native allow, denial, unsupported SDK, throw, missing callback, duplicate callback, confirmation network error/cancellation, late responses, source/referral preservation. Backend transient failure must not grant access.
2. Implement synchronous native request from tap and bounded confirmation/refresh; no navigation/reload or global loading state on success. Confirm server delivery only on successful send (signed initData proof remains existing).
3. Keep legacy browser tests as explicit unsupported-client recovery coverage; add native Chromium/WebKit user journeys.
4. Focused unit/backend/browser checks, lint/build, review, exact-head CI → PR tanyapi → standard release → public revision/health/focused smoke. Physical Telegram permission sheet cannot be rendered by mocked browser fixtures; document this limitation.

Guidance reused: evidence-first diagnosing-bugs; existing frontend audit and webapp testing guidance from project playbooks. Official Telegram WebApp requestWriteAccess callback contract verified.

Progress: regression command initially failed with backend transient chat_available=True and six missing native Allow tests. After implementation: native request is synchronous from the tap; duplicate/late callbacks ignored; native request deadline 60s and confirmation deadline reuses existing 12s check window; confirmation requests carry AbortSignal and original start_param_fallback; only capability refresh updates delivery state and never toggles global loading. Backend persists available only after successful Telegram send; denial/terminal/transient failures remain recoverable.

Browser: eight existing fallback entry scenarios passed; eight native entry/referral scenarios passed on Chromium, asserting denial never posts consent, positive callback confirms once, source DOM and exact URL remain, and no popup/chat/navigation occurs. Legacy browser suites now explicitly declare unsupported SDK version and retain manual /start recovery coverage. Added native media/referral cases to both CI gates; dedicated Mini App gate also runs them on WebKit.

Verification: 48 frontend/API tests passed; 78 backend permission/lifecycle/referral/link tests passed; Ruff and diff checks passed; ESLint has zero errors and one existing Kling4 hook dependency warning. Four-width fallback suite and four Genjutsu entry cases passed. Eight native source/referral cases passed with zero popup/navigation and exact DOM retained. Added strict boolean callback/response validation. Initial fallback browser failure exposed stale checking copy; corrected loading status so UI reports the in-flight check and fixture synchronizes on its completed false result.

Review follow-up: separate successful Telegram send from availability persistence. A classified transient PostgreSQL connection error retries only the idempotent DB write once, without replaying send. Exhaustion returns existing database_unavailable/503 rather than misreporting denied permission; no memory cache or second capability source is added. New regression tests reproduce the original P2 and verify single-send recovery and persistent-outage handling.
