# Telegram and web payment separation — 2026-11-19

## Scope and invariants

User request: every wallet, balance, top-up and fiat payment entry in the NEUROMIX Telegram bot and Mini App opens the website, through `/login` when needed, and resumes the selected payment intent after login. Telegram native checkout permits Telegram Stars only. Existing funds, orders, webhook completion and reconciliation must continue working.

Baseline: production source `tanyapi`, SHA `13e926870e1df356d0e1ab3f3fb68c318f3002fa`. Backend OCI revision, frontend revision.txt and health were checked before editing. Original shared checkout has unrelated VK edits; this task uses a separate worktree.

- No schema, price, balance, ledger or existing transaction migration.
- Server trusts only the HMAC-verified, unexpired context from `_get_user_context`. Browser Login Widget sessions already receive a signed `query_id=browser_<random>` from `browser_auth`; an unsigned client `platform`, `intent` or `query_id` is never authorization.
- Every Mini App provider dispatch, including explicit Lava/FreeKassa compatibility methods, denies non-Stars Telegram sessions before invoice creation or transaction writes. VK's existing Lava policy is preserved.
- Telegram update middleware catches stale fiat callbacks, payment commands/deep links and the old Lava email state. Session middleware rewrites newly sent wallet/payment buttons to website URLs and rejects native non-XTR invoices. Existing invoice status/completion callbacks and paid notifications continue to operate.
- Mini App `openBalance` is the common wallet/top-up entry and opens external `/login?return_to=...` in Telegram. An explicit Stars entry opens a Stars-only panel. Stale frontend fiat calls are guarded as well.
- `return_to` is limited to the exact same-origin `/mini-app/` route with allowlisted intent fields. No auth credentials appear in website payment URLs. Auth is forwarded in the existing URL fragment after login.
- Login retains selected package/provider and optional promo/required credits. On successful bootstrap the web studio opens the selected package without creating a charge. Provider checkout still requires explicit action. An existing valid browser session skips repeat login; errors keep the local intent available.
- Webhook verification, atomic transaction completion, referral effects and reconciliation are retained unchanged.
- Supported requested web methods resume with an explicit Continue action. Previously retired methods keep their retirement and show a clear request to select another method; this change does not reactivate Prodamus/CryptoBot in the web catalog.
- Paid Stars updates bypass access restrictions (ban/maintenance/subscription changes after invoicing) and settle at the root Dispatcher before any generation/email FSM catchall. No new user action bypasses access restrictions.
- When external bridge navigation fails, a persistent manual external link remains available. The Telegram WebView and generation draft are retained.

## Evidence ledger

- Reproduced the pre-change API policy failure with a real runnable assertion: Telegram `lava_card` was permitted.
- Focused backend checks: 68 passed, 31 skipped (optional PostgreSQL cases); signature/login, payment method/bonus, shared wallet, new dispatch denial, keyboard redirects and native invoice currency guard.
- Full frontend Jest: 123 suites, 999 tests passed.
- ESLint: zero errors, three pre-existing warnings. TypeScript passed. Production static build/export passed. `npm audit --audit-level=high` passed (moderate findings remain); Next.js emitted an existing dependency security reminder.
- Browser login E2E passed at 320/390/768/1440 px, including selected payment return intent and auth-config failure fallback.
- Android and iOS/WebKit browser payment E2E passed, including a throwing bridge: TG wallet redirects to website with no fiat request, native Stars path, and existing web delayed checkout, one-invoice reuse and video draft preservation.
- Independent Standards and Spec reviews found the Stars service-event interception, empty command parsing, requested-method resumption and same-WebView fallback; all were corrected with regression coverage. Additional full-chain Stars/access-guard regression passed.
- Latest focused backend: 138 passed (Stars middleware/Dispatcher, access restrictions, bot eligibility and keyboards); 94 passed / 1 skipped for payment/outage/receipt and previously missing test dependencies. Full clean exact-SHA backend/CI and production verification remain release gates at document authoring.

## Verification layers / release

DB transaction logic and provider completion do not change; run existing webhook/idempotency/financial suites. API, Telegram callbacks/FSM, browser E2E, auth and native currency enforcement have dedicated regression coverage. No migration/admin/config change is required; the existing `MINI_APP_URL` determines the bot's external website origin.

Release only by PR to protected `tanyapi`, with native squash auto-merge and strict required CI gates. Verify exact merged SHA in CI, backend OCI label and frontend revision.txt, health, actual public HTTP/browser smoke and sanitized recent logs before claiming a production release. A live third-party charge or real Telegram Login Widget sign-in must be reported as untested unless actually performed.

Rollback: revert the task commit through the same protected release pipeline. Do not reset production state or balances. Production runtime has pre-existing operator edits in `data/price.json`; preserve them.

Guidance inspected: Bambale0/skills TDD/diagnosis/review flows, Bambale0/claw architecture/release discipline, anthropics/skills webapp-testing (browser evidence with controlled external calls).
