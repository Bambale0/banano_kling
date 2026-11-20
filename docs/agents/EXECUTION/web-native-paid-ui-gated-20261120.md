# Web native finance and generation UI (gated release)

Date: 2026-11-20. Target: tanyapi. Base fd48bcbeb9c1c1dbde51f07b214455ace1c5e366. Depends on backend PR #667 and payment PR #658. Does not authorize live financial cutover.

## Design and source of authority

- The same /mini-app/ bundle handles native Telegram and independent website accounts. Native Telegram launch and its trusted initData-based wallet continue untouched.
- The server-authenticated web-auth/actor alone determines owner. For a linked Telegram/VK account, no standalone website payment/creation controls or second balance read are mounted.
- An independent verified web account can access the native web stack ONLY after its server GET /web-generation/models returns enabled AND GET /web-payments/packages returns available. Otherwise no CREATE/checkout controls appear. No toggles are trusted from query strings.
- New server GET /web-payments/balance allows owner-only live-wallet view, available/reserved/revision without raw ledger or linked Telegram figures, even while checkout is dark following a rollback.
- The new own web history uses /web-generation/history, opaque paginated cursor and dedup, distinct from the existing linked Telegram read-only history. Completed results remain visible after pausing new purchases.
- Paid browser generation panel quotes current server prices, submits opaque owner-backed uploaded S3 references and idempotency key, polls owned task, displays durable result. Gemini Omni Audio/Character IDs share the exact owner path.
- Lava panel creates invoice with server package/pricing only, polls order status, and never fabricates/relies on Telegram IDs.
- Failed/revoked session clears visibility and does not send payments. All forms depend on the backend to re-authorize each request.
- Additional linked-account financial consent and historical wallet migration are not silently assumed.

## Verification and limitations

- RED then GREEN: owner-only balance route (3 backend tests), independent frontend paid gates (4 new tests), pagination and stale/duplicate cursor behavior (1 new test).
- Focused frontend: Web payments, web generation, Omni, owner gates, previous native actor components all passed.
- TypeScript, changed-file ESLint, Next optimized static build and existing Playwright browser login/referral/private-history/logout E2E at 320/390/768/1440 px pass.
- Full local Jest run: 126 suites passed, 3 unrelated pre-existing Genjutsu/Trend tests failed, those three also reproduced in isolation. Exact GitHub CI is a required release gate, not assumed green.
- 3 synthetic backend unittest wallet routes passed. No production invoice or provider submission was made.

## Operational checks before enabling

1. Merge backend PR #667 and UI PR, deploy matching Docker/frontend SHA and check /health.
2. Verify anonymous API 401, linked actor no second wallet, web-only account no hidden credentials in URL.
3. Verify real Lava invoice creation, provider-verified webhook and balance credit in a consenting admin test account, with authenticated S3-backed provider job, exact capture/release and temporary provider outages. Stop at first uncertainty; never create duplicate invoices.
4. Historical Telegram financial cutover requires approved per-user opening snapshots, writer fences, exact event reconciliation, and precision review. Do not merge wallets by merely linking identities.
5. Keep WEB_NATIVE_PAYMENTS_ENABLED=0 and WEB_NATIVE_GENERATION_ENABLED=0 until independent test checkout and delivery are both proven and operator explicitly approves activation.
