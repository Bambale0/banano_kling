# TG–VK shared accounts execution ledger

## VK result absent from community chat — 07.11.2026

- Baseline 4f6387d65135b04a17c2d448ebeef793c5b08482; dedicated branch
  fix/tanyapi-vk-chat-delivery. Latest administrator task at 16:07 Moscow has one
  source/provider reference and a completed durable result, available_in_app.
  No VK send occurred: PR423 removed wrong TG delivery but added no VK sender.
- Audit: verified request context already exposes VK external/shared account IDs;
  task snapshot retains only origin_platform. Existing TG lease must keep rejecting
  VK. Native VK sender couples task/refund/block state and has unbounded download;
  native read-only HMAC cannot authorize a POST unchanged. Common deployment has
  launch secret but no community sender credential. No secret values were read out.
- Reuse common durable tasks, canonical identities/legacy links, audited preview
  policy and safe public-at-connect media downloader. Implement transport-only
  direct VK adapter/common outbox, avoiding two queues or new internal networking.
  Community credential must be configured securely before activation. No native
  task/user/financial mutations or public rollout are part of this slice.
- Plan: (1) RED signed launch/recipient and completion/outbox tests; (2) persist
  verified recipient, typed administrative delivery policy and durable CAS outbox;
  (3) bounded VK media/send adapter, permission and uncertainty handling;
  (4) authenticated status/explicit owner retry, client guidance/consent;
  (5) SQLite/PG/provider-contract/browser/regression/review/Draft CI evidence.
- Acceptance: new VK image completion reaches its verified user's community chat
  once under callback/poller races, keeps Mini App result available, never sends
  to TG, never charges/refunds again; denied permission and uncertain sends are
  visible and not silently retried. Old missing-recipient tasks require explicit
  fresh owner acceptance. Additive schema, default-disabled audited policy,
  secret-only transport configuration, no migration of wallets. Rollout hold stays.
- Applied existing diagnosing-bugs/wayfinder Research/implement/TDD/code-review,
  Claw backend integration and DDIA durable transaction guidance. Official VK
  schema was inspected; dev.vk.com was unavailable. No live send/provider call.
- Implemented recipient/account/intent snapshots for image/remix/image-trend
  launches; client-supplied identities/intent do not select the destination.
  Added a completion hook, fair recovery scan and durable per-task outbox with
  CAS leases, frozen copy/attachment and separate VK receipts. Signed negative
  random IDs avoid the native sender's positive timestamps; uniqueness and
  bounded collision recovery are tested. No native DB or financial code is used.
- The authenticated result view reports actual photo/link receipt, opens native
  VK consent without claiming permission, and supports explicit old-owner
  acceptance/retry. Unknown sends cannot be resent. New audited settings expose
  community/enable/retry/copy; enabling rejects an unbound credential. Default is
  disabled, and pre-enable launches do not silently become a message backlog.
- Independent Standards review found scan starvation and escaped result fields;
  both reproduced RED then passed GREEN. Same-lease late positive receipt was
  also reproduced RED and repaired without enabling another send. Spec review
  caught a task404 falsely labelled preview-disabled; neutral recovery regression
  passed. Both final reviewers report no remaining actionable findings.
- Local broad backend HTTP/auth/link/commerce/VK-origin/transport matrix passed
  104 tests, 70 isolated-PG cases skipped, with existing AppKey warnings. Final
  focused transport/outbox/HTTP additions are rerun separately. Full frontend
  96 suites / 717 tests passed before the isolated404 mapping; its final focused
  recovery matrix passed 19. TypeScript, changed ESLint and new-source Ruff pass.
- Telegram-path and dedicated VK-root production exports passed. Actual exported
  VK result browser scenarios passed at 320/430px on both (16 runs): permission
  dialog + explicit acceptance, old-result send, uncertain receipt/no resend and
  link-only receipt. API/provider/media were intercepted; no real message or paid
  generation was sent. Final source CI/native PG is still pending, not assumed.
- Read-only operational readiness: current task owner resolves uniquely through
  persisted legacy→shared→verified VK identity plus a committed two-sided link
  receipt. Existing native credential's token-default community matches its
  configuration; actual messages permission is true. photos.getMessagesUploadServer
  returned a valid HTTPS/public-IP upload endpoint without any upload/save/send.
  No credential, response URL or private user ID was output. Common-backend
  credential setup, activation and actual chat receipt remain release steps.
- Separate private-photo Draft425 final a0a7c4e0d985c6f39d4c62e961f7adb32207c883
  has all four main CI gates and native PG green (Linux safe 4779 passed,
  250 skipped, 76 subtests); Draft/auto-merge-off verified. It is not merged or
  deployed and is not a dependency for this chat-delivery slice.
- Rollback preflight reproduced RED: old authentication policy readers reject
  additive delivery JSON keys. Delivery now uses its own existing bot_settings
  row, with one shared revision/atomic audit transaction. The old auth JSON stays
  readable, and old-client updates preserve delivery controls. Credential storage
  remains separate. No manual SQL or production configuration change was made.

## Missing card after authentication failure — 07.11.2026

- Baseline `tanyapi@9eda416c861f8634b28fd94c81f634a24b7de875`; branch `fix/tanyapi-account-card-auth`.
- User screenshot shows settings 401, a permanent loading label, and no linked-account card. Production access logs confirm intermittent settings 401 with other 200 responses; no credentials were read or logged. Original smoke mocked successful settings and missed this failure path.
- RED: `node node_modules/jest/bin/jest.js --config jest.config.ts --runInBand components/__tests__/shared-account-preview.test.tsx`: 1 failed, 4 passed; exact assertion cannot find «Связанные аккаунты» after rejected settings read.
- Existing parent renders linking only when `policy.enabled` is loaded. Preserve administrator and server authorization, configured freshness, consent, financial boundaries and persisted-status truth. Never solve expiry by accepting stale signatures or fabricating linked status.
- Plan: show a persistent card on settings loading/failure, recover independently through authenticated account metadata, remove perpetual settings loading and add retry; distinguish expired login with safe diagnostics; verify failure/retry and normal states through component and browser seams, then protected PR/native squash auto-merge and exact-SHA production checks.
- No DB/schema/provider/payment/FSM or live account merge changes. Technical retry/abort deadlines remain finite. Mutable app IDs, bot name and policy come from authenticated server configuration. Rollback is a PR revert.
- Diagnosis: read-only production policy confirms `enabled=true`, `launch_max_age_seconds=600`. Ordinary Mini App validation accepts up to 86400 seconds. A signed 900-second-old launch passes the ordinary window but is rejected as `Expired launch credentials` under the preview window. Freshness remains unchanged. Production settings logs include both 200 and 401 responses; the exact rejected credential was never retrieved.
- Implementation: the card is always mounted for the existing administrator surface; it obtains destination app ID/bot name from its own authenticated metadata. Settings loading ends on failure/15s timeout and offers retry. A Telegram relaunch link uses the bootstrap-provided configured bot name even if global launch configuration is absent (caught by the new failure browser scenario). No source ID/URL hardcodes or weaker authentication were introduced.
- Independent standards/spec reviews caught a slow-settings/fast-metadata race. Removed the revision-based React key and refresh only metadata on policy changes. A real parent/real child deferred-settings regression verifies an invitation URL and consent survive settings arriving late; reviewers cleared the final change.
- Verification layers: component/API/auth-negative/browser/permissions/logging are applicable. DB schema/migration, financial/provider retry, Telegram FSM and live financial cutover are unchanged; existing HTTP/security/link matrix is rerun and PostgreSQL CI supplies native integration checks. No paid production request or live account merge is part of smoke.
- GREEN: full Jest 91 suites / 694 tests; focused actual-parent/linking and failure/deadline/retry suites 20 passed. Backend HTTP/security/link matrix 40 passed, 40 isolated-PostgreSQL cases skipped locally; expired signed HTTP request/secret-free reason test 1 passed, 1 PostgreSQL skipped. Ruff, changed-file ESLint, TypeScript/build, E2E syntax and whitespace checks passed.
- Final Telegram static export passed. Browser checks passed 10 scenarios: prior 8 ordinary/admin platform/layout paths plus expired settings + expired metadata and expired settings + independently valid metadata. Both new failure paths explicitly assert the card exists, no perpetual loading, correct configured relaunch/connection control, and no unsolicited link mutation. The first failure-browser attempt caught absent global bot config; wiring the actual bootstrap username fixed the real UI seam before final green.
- Applied `Bambale0/skills` diagnosing-bugs (RED reproduction, ranked hypotheses, actual expiry probe, regression), implement/code-review; reused `Bambale0/claw` UX error/recovery and `anthropics/skills` frontend guidance. No authentication policy/configuration or migration change. Release verification follows the PR and exact-SHA autodeploy; not yet claimed here.

## Linked accounts card — 06.11.2026

- Baseline: `tanyapi@992c9b17a05649552873c582b6ecddbd4bad163d`; branch `fix/tanyapi-linked-accounts-card`.
- Request/spec: the supplied screenshot; a compact «Связанные аккаунты» card with Telegram/VKontakte brand icons, real connection status, a green check for connected identities and «Привязать» for the other platform.
- Audit: signed platform sessions, server administrator restrictions, configurable invitation URLs/lifetime and two-sided confirmation already exist. Linking is currently a technical form nested in the administrator tools and the unlinked VK entry. Reuse those services; no prefactor required. Missing: a clean initial card and persisted VK connection status in the authenticated profile.
- Scope: preserve the administrator preview boundary and explicit consent; change the shared linking surface on both platforms. Do not enable public rollout or migrate balances. No schema, tariff, payment, generation, provider, Telegram FSM or runtime configuration changes.
- No-hardcode: IDs, bot username, policy and link destinations remain server/configuration derived. Status comes from authenticated persisted identities; failed reads must never display «Не привязан» as a fabricated fact. Brand colors and labels are presentation constants.
- Risk: opening an invitation must not accept/confirm it; one confirmation must not show success. Keep revision checks, expiry/cancel recovery, double-click protection, errors and token privacy. Existing server link/session logs remain authoritative; no credentials added to telemetry.
- Test seams: component clicks/status/error/cancel/consent; authenticated HTTP profile before/after actual two-sided merge; mocked browser at narrow mobile/desktop widths. DB schema/migrations, provider/retry/payment mutations, generation and bot FSM tests are not applicable: their implementation is unchanged. SQLite link/security regressions remain applicable because statuses expose persisted identities; PostgreSQL CI runs the existing matrix.
- Steps: (1) behavior tests and RED; (2) authenticated linked-platform metadata and reusable card; (3) both entry surfaces and clean placement; (4) component/backend/lint/types/build/browser checks; (5) independent standards/spec review; (6) protected PR to `tanyapi`, native squash auto-merge and exact-SHA release verification.
- Acceptance: screenshot structure, no initial code field, one clear action, both platform directions, no false linked status, separate explicit acceptance and consent, retry/cancel/expired paths, no overflow at 320px.
- Rollback: revert this PR via `tanyapi`; no data/config rollback needed. Local source is a separate checkout because the original OneDrive checkout has unavailable placeholders and unrelated changes. Baseline runtime/log evidence was obtained below; no deployment of this change is yet claimed.

### Implementation and verification

- Added the shared card, authenticated `linked_platforms` metadata and persisted membership query. Both entry directions reuse the existing invitation/accept/confirm/cancel services; settings are in a native disclosure. Added bounded status loading, retry, successful-state cleanup and synchronous operation deduplication.
- Focused Jest: 27/27 passed; focused SQLite HTTP/security/link tests: 39 passed, 39 PostgreSQL cases skipped because no isolated local DSN is configured. Ruff on the four changed Python files passed. TypeScript `--noEmit`, changed TypeScript/TSX ESLint, E2E syntax and diff whitespace passed.
- Full Jest: 90 suites / 688 tests passed on the fresh `--no-cache` run. The first run had one unrelated timing failure in the unchanged WAN Prime quote test; it passed in isolation (39 tests including the linking suite), then the full clean run passed. No WAN implementation or test change was made.
- Telegram production static export compiled, type-checked and patched head assets. Browser preview passed ordinary/admin Telegram at 320/430/1280px and ordinary/admin VK at 430px (8 scenarios), with all APIs mocked. Verified real actions through configured URL generation and cancellation, disabled premature confirmation, no unsolicited invitation mutation, no token storage, and no name/button collision or card overflow. Local browser uses installed Chrome via optional test-only `E2E_BROWSER_CHANNEL`; CI defaults to its pinned Playwright Chromium. Final icon-radius polish was rebuilt and all eight browser scenarios passed again; 320/430px screenshots were visually inspected.
- Local dependencies were installed from the existing manifest's semver ranges because npm is absent; committed package/lock files are unchanged and CI verifies the locked dependency set. Native PostgreSQL, both locked exports, required production gates and deployment are verified separately in CI.
- Independent Standards review found and then cleared the missing status timeout and stale error after commit; independent Spec review found no confirmed violation and requested narrow-screen verification, which passed. Applied `Bambale0/skills` implement/code-review, `Bambale0/claw` UX/frontend audit, and `anthropics/skills` frontend-design guidance.
- Read-only production baseline via SentinelX: image revision `992c9b17a05649552873c582b6ecddbd4bad163d`, healthy container; latest bounded 1,000-log-line sample had zero shared-account failure events and zero tracebacks. `tanyapi` protection is verified `strict=true` with all four required contexts. No production writes or paid calls were made.

## Opening-balance readiness audit — 06.11.2026

Baseline PR415 f1e8b32e873dd27dc36daa6cfa6c0ea54340ea04; VK master
cbbfb48ab494591b60ab06fd81a76a3cee69c08e. No production access or writes.
Existing exact wallet/link/reconciliation services are reused. Missing: opening
claims, precision approval, writer fencing, legacy event/settlement bridge.
Public test seams authorized by this task: import rehearsal service, wallet
commands, confirmed linking API, read-only migration diagnostics. No UI change.
Plan: (1) inventory financial writers and evidence; (2) test-first sandbox-only
one-time opening claims incl. zero, identity ownership and merge/replay races;
(3) regression diagnostics for invalid/ambiguous balances; (4) focused DB tests
and review; (5) publish to the existing Draft branch without merge/deploy.
No mutable economic settings added. Exact currency precision remains 10,000;
historical float normalization is an explicit release decision, never automatic.
PostgreSQL unavailable locally: no service/Docker; package-backed server also
could not initialize due restricted user creation. No production fallback used.
Real provider/bot/browser smoke is inapplicable to this offline sandbox slice.

Implemented sandbox-only opening rehearsal on the existing wallet, immutable
identity-scoped claims (including zero), exact amount/evidence binding and
atomic rollback. No live switch/route/CLI. Read-only preflight now reports
exact/review/invalid balances in consistent read snapshots. Full writer audit,
precision/history caveats and checkable cutover rules are in
docs/adr/20261106-opening-balance-readiness.md. Production remains NOT READY.

RED/GREEN: missing rehearsal module; diagnostic readiness keys absent; tiny
scientific amount incorrectly exact-zero before lower-bound fix. Independent
standards review reproduced that Decimal underflow; fixed with public audit
regression. Spec review requested equal TG/VK numeric IDs and conflicting
concurrent snapshot claims; added, then tightened exact expected balances.
No unresolved review blockers in this sandbox slice.

Final combined account/wallet/opening/link/commerce/audit/browser-auth matrix:
109 passed, 102 skipped (PostgreSQL not configured). Focused opening/audit:
24 passed, 21 PostgreSQL skipped. Ruff and diff whitespace passed. The existing
Shared accounts preview CI explicitly includes opening tests on SQLite + isolated
PostgreSQL; exact published SHA CI is checked separately, not assumed green.
Synthetic actual VK Database-method reproduction passed for both legacy and
extracted classes: start10 +2.5 -1.125 +refund =12.5; units stayed0, transaction
sum2.5 excludes starting10; duplicate refund rejected. No VK production code
changed. All real writer conversion, legacy event/refund bridge, freeze protocol,
normalization approval and production migration remain release blockers.

Parent plan #408; E1 #409. Isolated branch:
feature/tg-vk-identity-preview-20261105.
Baseline tanyapi@03a9918db303b8ac075115fde8cbccecf6d10aeb.

## Constraints

- Implementation authorized 05.11.2026; no production merge or deployment until
  the complete feature is finished. Draft PR, auto-merge off.
- New behavior must be restricted to administrators on the server. Defaults off.
- Production balances, references, existing runtime price configuration and
  provider routing are untouched. No production schema migration.

## Preflight

- Re-read project instructions, release workflow, browser auth, Mini App
  bootstrap/profile, shared DB adapter and tests. Origin tanyapi equals baseline.
- Existing Telegram/VK account/wallet architecture audited in #408. Separate
  identity/session/wallet tables absent; schema drift must precede money cutover.
- Reuse bot_settings for typed administrator controls; exact HTTP routes before
  the existing catch-all; existing own-profile screen for admin-only UI.
- Source identity is platform-scoped. Existing Terraform/cloud/admin security
  is not relaxed, and no fake Telegram user is created for VK.
- Guidance: Bambale0/skills implement/tdd; prior Bambale0/claw QA checklist;
  anthropics/skills inspected, browser UI verification applies to later E2E.

## Steps and evidence

1. [x] Pin baseline and create isolated worktree; preserve production checkout.
2. [x] RED admin-only HTTP tests: missing module on baseline. Initial guard GREEN:
   3 passed; signed-session/VK tests RED: 5 failed, 4 passed before implementation.
3. [x] Implement typed preview policy, source-scoped auth, accounts and revocable
   hashed sessions; legacy credits untouched. Initial signed-session GREEN: 9 passed.
4. [x] Add admin UI controls and exact route wiring. UI RED on absent API/component.
5. [x] SQLite + isolated PostgreSQL HTTP/security/concurrency matrix and adjacent
   browser-auth/audit checks: final 57 passed. Policy revision binds sessions;
   disable/re-enable regression RED on both engines, GREEN after fix. Review
   follow-up adds tamper/stale/future/duplicate/unsigned Telegram launches on both
   session and settings routes, plus equal cross-platform IDs.
6. [x] Full backend safe suite before final narrow security additions: 4641 passed,
   121 skipped, 76 subtests. Full frontend: 82 suites / 647 tests passed; final new
   UI/API focused checks: 8 passed. Ruff, ESLint, TypeScript, compileall, diff
   whitespace and final production build passed. New Chromium browser check
   passes ordinary/admin at mobile 430px and desktop 1280px. General critical-flows
   attempt timed out at 210s and is NOT counted as passed. Its existing CI remains
   required; the new browser scenario is also wired into Mini App Browser E2E.
7. [x] Independent Standards review: no blocking findings. Spec review: missing
   negative Telegram launch tests; added and reviewer confirmed resolved. Initial
   implementation committed as 15084a0e; follow-up regression/CI commit pending.
   Draft PR and no production merge/deploy remain mandatory.
8. [x] Push initial branch, open Draft PR, verify auto-merge remains off, and record
   exact SHA/check status in #408/#409. All epic descriptions now reflect the user
   restriction: implementation allowed, production merge/deploy held until complete.

## Risk and rollback

Preview schema is additive and lazy. Default-off leaves existing routes alone.
Rollback removes branch code; preview data can remain isolated. Do not deploy to
test it in production. General wallet/account-merge rollback is a separate E8
concern and must not restore independent writable legacy wallets after cutover.

## Remaining work

The isolated administrator preview now has a wallet and two-sided magic-link
merge. Live financial cutover, complete VK Mini App generation parity, payments,
delivery, referrals and production rollout remain incomplete.
App-cabinet credentials/settings and migration policy decisions remain external
prerequisites. Complete feature acceptance follows #408, not this initial PR.

## Draft publication and CI follow-up

Draft PR #415 opened, not merged. Initial exact-head CI found an import-order
error in the existing browser_auth import block; corrected without behavior
changes and reproduced the repository changed-line gate. Full production
release hold is unchanged.

## E2 wallet implementation started

User reconfirmed: finish the entire product, no deployment; merge only the
finished product. PR #415 remains Draft. All seven CI workflows for 653cb41e
passed, including Mini App Browser E2E. Next seam: common wallet operations
(credit/reserve/capture/release/refund), exact minor units and immutable ledger,
validated on SQLite and PostgreSQL with concurrent/replayed operations.
Administrator HTTP preview uses a separate sandbox namespace: synthetic funds
can never be promoted/imported as live money. Production wallets and real
provider submissions remain untouched while the new authority is built.

### E2 wallet foundation evidence

Exact 4-place minor-unit wallet, credit/reserve/partial capture/release/refund,
request-bound idempotency and immutable journal implemented. API is admin-only
and sandbox-scoped. HTTP/domain SQLite/PostgreSQL wallet checks: 52 passed;
combined account/wallet/adjacent matrix: 109 passed. Frontend focused UI/API:
11 passed; TypeScript passed. Regression caught and fixed PostgreSQL Mapping
row iteration and Decimal context rounding on long coefficients. Live balances
and legacy writers are still not switched; production release remains held.


## E2/E4 wallet and two-sided linking checkpoint

- Exact minor-unit wallet and append-only ledger; atomic credit/reserve/partial
  capture/release/refund. Paired merge transfers preserve active reservations.
  Aliases preserve late callback idempotency and historical partial refunds.
- Invites store only token hashes; configurable expiry, revisioned consent,
  explicit accept plus independent confirmations; GET never consumes consent.
  Parties see verified counterpart IDs; conflicts/overflow roll back atomically.
- VK preview has a signed entry independent of TG bootstrap; ordinary VK users
  cannot mount wallet/link controls. TG ordinary users make no preview requests.
- New tokens never enter browser storage, including signed startapp launches.
  Normal referral launch caching retains its existing behavior.
- Latest backend combined matrix before the last 6 added cases: 127 passed.
  Final link-only SQLite/PostgreSQL suite: 24 passed (includes those 6 cases).
  Full frontend before credential-cache additions: 86 suites / 661 tests passed;
  final focused sources incl. credential caches: 7 suites / 24 passed.
  Ruff, ESLint, TypeScript/build and all 6 browser scenarios passed.
- Independent spec/standards reviewers found internal key namespace collision,
  hidden counterpart identity, VK UI reachability and expired-link recovery;
  all fixed with regressions and reviewers confirmed no open findings.
- No production migrations, deploys, provider submissions or real-money writes.
  This checkpoint is NOT the finished #408 product; live writer conversion,
  legacy opening reconciliation, VK generation parity and payment/delivery/
  referral adapters still require implementation and acceptance.


### Reconciliation checkpoint

Added administrator-only sandbox reconciliation and explicit balance refresh.
Review caught orphan reservations on merged aliases and operation/delta semantic
mismatches; both now have regressions and reviewers confirmed resolution.
Final combined SQLite/PostgreSQL/account/audit/browser-auth suite: 145 passed.
The initial final run was interrupted by OOM in the disposable PostgreSQL tmpfs
container (256MiB includes WAL/tmpfs); replaced only that task-owned container
with bounded disk-backed disposable data, then the exact checks passed. No
production databases or runtime configuration were changed. Focused wallet UI
4 tests, TypeScript, ESLint, build and 6 Chromium scenarios passed.


## Commercial requirements update — 06.11.2026

Recorded customer steering in #408/#413 and ADR 20261106-tg-vk-commercial-requirements:
shared editable prices, independent tariff/collaboration/commission settings,
preserve individual terms (40% must not become generic30%), VK Lava-only with
verified-origin backend restriction, immutable accepted snapshots. Offer/feed
wording remains a clarification; no visibility behavior inferred. Source audit
confirmed VK global rate and TG per-recipient policy/creator seams. No runtime
prices, percentages, merchant registrations, live databases or deployment changed.


## Commercial control-plane implementation — 06.11.2026

Customer clarified: do not change the offer document. Continue implementation
without production merge/deploy. Scope of this slice: one administrator-managed
preview catalog and account-specific tariff/partner terms, visible in both TG
and VK preview; exact strings, audited CAS, explicit merge conflicts, VK Lava
ceiling based on verified session platform. Legacy generation prices, wallets,
merchant credentials and historical orders remain untouched until their adapters
and cutover gates are complete. Pending source-state conflict prevents a silent
rate downgrade or privilege escalation. Tests first on isolated SQLite/Postgres.


### Commercial preview verification

Implemented one shared administrator catalog, independent tariff/partner-group
assignment, individual exact rates and repeat rewards, identity lookup, immutable
self-quote snapshots and verified VK-origin Lava ceiling. Shared structured editor
is mounted in TG/VK preview. Does not mutate legacy production price/referral
settings or create invoices/debits. The offer is explicitly unchanged.

RED missing commerce route; catalog tracer GREEN, then RED quote/terms routes
on SQLite/PostgreSQL and GREEN after implementation. Combined final account/
wallet/link/commerce/audit/browser-auth matrix: 167 passed. Full frontend: 89
suites/673 tests passed; focused commercial/account UI 20 passed. Initial full
UI attempt exceeded its capture timeout and only task-owned Jest processes were
stopped; bounded streaming rerun completed exit0 in58.246s. Ruff, ESLint,
TypeScript/build and all6 browser TG/VK ordinary/admin scenarios passed. Browser
selector diagnostic caught ambiguous native select labels; explicit ARIA labels
now expose the correct controls, and the complete smoke passed.

Independent Standards review caught a stale-alias CAS hole; every merge now
bumps canonical terms revision even when incoming assignment is empty. Regression
proves stale default PUT cannot replace40%with30%. Spec review caught stale
effective terms after group edits; editor refreshes saved effective values while
preserving unsaved form and originalCASrevision. Regression covers inheritance
and individual override. Both reviewers confirmed no remaining findings.

Remaining integration gates: production financial authority/writers and opening
balances, checkout/order and recipient reward snapshots, legacy assignment import,
full VK generation/history/feed parity and real cabinet/client acceptance. The
preview quote's account terms are not a recipient payout calculation. PR remains
Draft; no production migration, deployment, real-money operation or provider call.


## VK domain root build and fresh read-only financial audit — 06.11.2026

Baseline b5cfdf67. User requested finishing and deployment; initial visibility remains administrator-only, offer unchanged. Pre-agreed test seams: browser entry and shared-account HTTP/DB contracts. No new production application or database writes.

Implemented `build:vk` at root /, shared build-prefix normalization, prefix-aware export patch, no Telegram SDK/ready bootstrap or cached Telegram credential fallback on VK profile, unsigned direct-entry hint. Default Telegram build retains /mini-app. Added Node export checks, public API/entry regressions and Chromium root-export smoke (430/1280 widths, direct/ordinary/admin flows; API mocked). CI builds both profiles and runs Chromium smoke. Independent spec/standards review requested docs reality and browser launch-failure cleanup; both fixed. Generated tsconfig.tsbuildinfo excluded.

RED: root basePath returned /, root asset version/CSS processing absent, direct VK build mounted TG. GREEN: 3 Node checks, 18 focused Jest tests, both builds and root browser scenarios. Full first run picked Node scripts as Jest suites; renamed standalone checks to check-*.mjs. Two reference suites also failed with cached compilation and attempted localhost API; fresh --no-cache focused run and entire suite passed (89 suites, 676 tests, 59.134s). No production source change was made to suppress these failures. ESLint and TypeScript passed. Real VK acceptance remains blocked on configured app ID/secret/admin allowlist; no fake identity or trust in query parameters introduced.

Fresh live read-only snapshots (not simultaneous, not a migration manifest): TG 87,877 users, 790 precision-review balances, 0 invalid; 87,087 exact balances subtotal 6,662,460,000 units. VK 7,248 users, 214 precision-review balances, 1 invalid negative balance (-5); 7,033 exact balances subtotal 250,949,000 units; 6,098 legacy unit mismatches, 1 uncomparable. Subtotals exclude blocked rows and are not total liability. No balances normalized, cleared or imported. Snapshot moves as live activity continues; these counts cannot be used as a writer fence or final import manifest.

Production financial cutover remains blocked: legacy writer fencing/event/refund bridge, approved precision handling and negative-balance resolution, live importer and reconciliation. Native cabinet configuration and full generation/history/feed parity also remain incomplete. Maintenance HTTPS vhost stays in place. This slice is preparation for the requested release, not a claim that the complete product is finished.


Final shared-account matrix including opening rehearsals now verified locally on SQLite and isolated PostgreSQL17: 211 passed in87.75s. Test database removed. Fresh nearest-four-decimal diagnostic: all precision-review differences <=2.121e-11 TG /1.4e-13 VK bananas, no HALF_UP/HALF_EVEN disagreement; no rounding applied. Details added to opening-balance ADR. Independent final spec/standards reviews confirmed no remaining findings in the root-build slice. Release of the complete product remains blocked for the reasons above.


06.11 clarification: text VK bot needs only the native launch button, no new text flows or text-bot feature parity. Common app/server synchronization remains required. Requested immediate full-screen launch; VK entry surfaces now fill the available viewport (min-height100dvh,width100%, bounded readable content). Official VK Bridge contract inspected: resizeWindow only sizes iframe; view settings only control appearance; no invented fullscreen method added. CSS viewport fill is not acceptance of client-level fullscreen. Actual native launch/button enablement remains blocked on registered app_id and client acceptance, and shared app authentication requires its real secret.


## Admin-only production preview authorization — 06.11.2026

The owner explicitly authorized merge and production deployment of the current administrator preview. This supersedes the earlier no-deploy hold only for the signed, server-enforced admin surface. Ordinary VK and Telegram users remain denied; the sandbox wallet cannot become live funds. Public rollout, live financial cutover, payments, generation/history/feed parity and offer changes remain out of scope and blocked.

Release additions after exact-head review: magic-link launch data is removed from the application cache, launch snapshot and Telegram SDK session key; the authenticated `/me` response supplies the configured Telegram bot username so the standalone VK root can create a VK→Telegram invitation without a hardcoded client value. Production requires `VK_MINI_APP_SECRET` and `TELEGRAM_BOT_USERNAME` in secret/runtime configuration. Rollback is the isolated PR revert plus restoration of the maintenance vhost; preview policy can be disabled independently.


## Common Mini App parity — 06.11.2026

- Baseline: production `tanyapi` SHA
  `398a503856308736e9eb57f7dd9e43ec79c7772f`; isolated branch
  `feature/vk-full-miniapp-parity-20261106`.
- User-visible result: a linked administrator entering from VK mounts the same
  `MiniAppShell` and backend routes as Telegram, with the linked Telegram
  legacy owner as the only balance/task/history/generation authority. No shadow
  user or second balance is created. Unlinked VK actors stop at the mandatory
  two-sided link gate.
- Root cause of the earlier maintenance/preview screen: the VK entry component
  routed every signed VK launch to the account-preview cabinet instead of the
  common application shell, even though most product APIs already shared one
  authenticated actor boundary.
- Security: the signed VK session is kept only in browser memory; every request
  revalidates the preview-policy revision and server administrator allowlist.
  Telegram authentication behavior is unchanged. VK does not execute Telegram
  subscription, referral or text-bot side effects.
- Payments: verified VK sessions are restricted to the existing Lava route on
  both UI and server boundaries. Prices, Creator terms, balance mutations and
  the offer are not changed. The text VK bot is unchanged.
- Compatibility fixes: the regression-safety, ban, partner and Kling 4 wrappers
  now resolve the same linked legacy actor for VK instead of requiring Telegram
  init data directly. Telegram early-rejection and no-side-effect behavior is
  preserved.
- RED/GREEN evidence: VK failed the regression-safety wrappers and Kling 4
  actor seam before the adapters. After the fixes the selected backend matrix
  is **93 passed, 26 skipped**. Full Mini App Jest is **90 suites / 682 tests
  passed**; ESLint has no errors (one pre-existing hooks warning); both VK-root
  and Telegram production exports pass. The VK Chromium journey passes at
  430px and 1280px and proves common navigation, memory-only VK credentials,
  no Telegram SDK request and no Telegram write gate.
- No migration or mutable price/config update is required. Rollback is a normal
  reviewed revert; disabling the existing preview policy immediately blocks new
  VK sessions. Ordinary users stay denied until a separate public-rollout
  decision.
- Remaining release gates at this checkpoint: protected PR to `tanyapi`,
  exact-head required CI/autodeploy, exact deployed SHA and real signed VK
  administrator acceptance. Public rollout remains a separate decision.

Release-candidate verification: full backend **4722 passed, 223 skipped, 826 warnings, 76 subtests passed** in 405.51s. Deployment-contract matrix **27 passed, 6 subtests passed**. A first frontend rerun reused stale Jest compilation for two unrelated reference suites; the clean `--no-cache` regression rerun passed **90/90 suites, 682/682 tests** in 56.351s. ESLint completed with only the pre-existing Kling 4 hooks warning. Telegram and VK production exports and the VK Chromium root smoke (430px/1280px) passed. The production deploy now builds and publishes both origins from the exact same expected SHA, writes and verifies both `revision.txt` files, retains prior VK releases and atomically replaces only the VK `current` symlink.

## Native VK journey and missing reference — 07.11.2026

- Baseline `00b40366c40b4684e23d8dfde0c3fc2c188bfbfb`; dedicated task branch
  `feature/tanyapi-vk-native-journey`. Original OneDrive checkout is untouched.
- User clarified Integer screenshots are examples; the incident is NEUROMIX.
  Requested native VK entry without required Telegram, preserved reference input
  and delivery on the originating platform, with optional explicit linking.
- Fresh read-only administrator task/log audit confirms the 11:33:38 Moscow
  Banana Pro task had zero source/provider references and Telegram delivery.
  Current shared-app code requires a linked Telegram legacy actor and drops the
  launch platform before task persistence. No live account/balance mutation.
- Execution/preflight and local wayfinder map:
  [Independent VK journey](VK_NATIVE_JOURNEY_MAP.md). Existing signed identity,
  upload/library/provider snapshots and delivery state are reusable; account
  and finance compatibility require evidence before enabling public access.
- Planned seams: actual form/library -> submitted reference URLs; signed VK HTTP
  -> native actor; task creation -> provider snapshot and delivery destination;
  completion/retry -> correct platform; both browser journeys. Configuration,
  schema and migration decisions remain pending the backend research.
- Progress: project/playbook/docs/contracts and current exact production baseline
  inspected; administrator diagnostics are aggregate/metadata only. No provider
  call, message send, migration or production release performed for this task.
- Reference slice RED: actual ImageGeneratorForm + UploadArea + personal library,
  category upload then generation submitted `references: []` instead of the
  uploaded URL. Minimal fix selects the completed upload only in selection mode;
  separate library management still saves without selecting. The mode label now
  distinguishes text-only from photo input. Focused regression matrix: 14 passed.
  Initial type check caught a missing filename in the synthetic test fixture;
  fixture corrected to the existing API contract. No provider contract changed.
- Full clean Jest: 93 suites / 701 tests passed. TypeScript and changed-file
  ESLint passed. Added a browser regression for both signed-platform fixture
  entries that asserts the actual generation HTTP request carries the uploaded
  URL and retains the reference after a rejected request; every API is intercepted.
  Browser/export verification is in progress, not yet claimed.
- External read-only Research completed: active VK checkout tree matches remote
  master, native workers/SQLite/VK delivery exist but there is no browser API.
  Existing GET-only HMAC cannot authorize financial writes unchanged. Current
  balance precision/shadow divergence confirms the existing financial readiness
  barriers. Owner financial-scope question is pending; native activation, migration
  and result-channel parity remain unimplemented and are not claimed by this slice.
- Additional RED/GREEN: uploading while editing categories inside the picker
  also omitted selection. Any upload initiated from a picker now selects; the
  standalone management screen remains save-only. The action says «Загрузить и
  выбрать». Focused matrix now 15 passed; TypeScript passed again.
- Browser export seam passed Telegram and linked-VK fixtures through the actual
  HTTP generation payload, with failed-request reference retention. The first
  harness expected a synthetic English error that the existing UI intentionally
  redacts; switched the fixture to a valid short localized validation message.
- Unchanged backend reference/privacy matrix on Windows: 84 passed / 16 failed.
  Failing owned-upload cases are caused by existing `os.path.normpath` returning
  backslashes before a POSIX-prefix ownership check. No backend/tests changed;
  this is not a production Linux reproduction. The exact-baseline production
  Linux suite passed previously; this PR still requires its own full Linux gate.
  Do not weaken the ownership tests or change backend behavior for this UI slice.
- Final local verification: 93 Jest suites / 702 tests, focused 15 tests,
  TypeScript, changed-file ESLint, Node syntax, workflow YAML and whitespace
  checks passed. Both Telegram and VK production exports passed. Browser checks
  passed Telegram + linked VK against the Telegram export and linked VK against
  the dedicated VK-root export (three journeys). Independent Standards and Spec
  reviews of e5e7af9 report no actionable findings. No native public activation,
  real provider generation, live message send or financial migration is claimed.

## Image generation origin and cross-platform delivery — 07.11.2026

- Baseline `tanyapi@00b40366c40b4684e23d8dfde0c3fc2c188bfbfb`; independent
  branch `fix/tanyapi-vk-result-origin`. Reference-picker fix is tracked by #422.
- Intended result: an ordinary image launched through a verified VK session stays
  available in that Mini App and is not silently sent to the linked Telegram chat.
  Native VK messaging/public onboarding remains a separate pending product slice.
- Current audit: VK launch context already has a verified platform; ordinary image,
  remix and image-trend launch paths discard it. Persisted tasks retain the linked
  legacy Telegram ownership ID; direct and queued notifications and provider
  callback/poller deliveries therefore assume Telegram. Existing request metadata,
  atomic completion and delivery leases can be reused; no financial prefactor.
- Plan: (1) RED public completion/lease and launch-origin tests; (2) persist server-
  derived origin at image creation; (3) gate direct/queued/callback/poller Telegram
  delivery while keeping result completion/repeat rewards intact; (4) API/ownership,
  DB/lease/retry/legacy regressions, review, protected PR/exact-SHA release checks.
- Technical contract: optional additive origin metadata and a terminal in-app
  availability state; old tasks and Telegram launches keep existing behavior.
  Client-supplied platform cannot select a destination. No new external messaging
  API, secret, price, mutable business setting, schema or balance migration.
- Risks/seams: direct and asynchronous provider paths, duplicate callbacks, task ID
  aliases and completion rewards; verify the owner can read the completed result
  and no Telegram send/lease is performed for persisted VK origin. Existing signed
  auth/admin limits stay enforced. Native VK delivery capability is not fabricated.
- Rollout: first let #422 finish normal CI/autodeploy; rebase this branch onto the
  then-current tanyapi, run required checks and use native squash auto-merge. No
  production result replay, live chat send or paid generation is authorized by tests.
- RED/GREEN: VK completion originally acquired a Telegram lease; the Mini App
  HTTP path dropped the verified origin; real queued/direct notification helpers
  sent to Telegram; poll completion returned failure for an app-only result.
  Added the saved origin, non-Telegram lease guard and an in-app completion path.
- Public callback regression covers success/failure plus a repeated callback,
  retaining normal completion bookkeeping and a single refund while sending no
  Telegram message. Replayed in-app completion initially replaced a terminal URL;
  fixed by using the durable saved URL. Provider-ID replacement preserves origin.
  Current focused matrix: 8 passed on SQLite; unrelated Linux resource diagnostics
  are isolated in the Windows test fixture. Native PostgreSQL and larger regression
  verification, legacy callback variants, image-trend propagation and review remain
  in progress. No source from this branch is deployed.
- Rebased onto #422 merge `b9834c795707dc3037340ea553f41c1ea50f0f9b`;
  both ledger sections were preserved. Broader collection revealed the installed
  generation-start UX replacement also needed the new origin argument/guard.
  Added that real runtime installer to the regression fixture and fixed the
  notifier. The callback fixture now binds watchdog storage to its isolated DB.
- Expanded SQLite matrix: 139 passed (HTTP, result polling, KIE verification,
  provider IDs, creator pricing/debit guards and image trends). Final focused
  origin matrix: 14 passed, including Telegram/default compatibility and both
  legacy image callbacks. An earlier wider run also exposed two unchanged Windows
  POSIX-path ownership failures; those are not weakened or fixed by this slice.
- Ruff changed-line gate passed in UTF-8 mode (0 relevant findings, 407 legacy
  findings ignored by the repository's existing gate); full new-test/delivery-
  state Ruff and syntax checks passed. Added native PG durability cases to the
  existing Runtime PostgreSQL workflow's test module; native execution is pending
  CI, not claimed locally. Design/rollback: ADR 20261107-image-launch-platform.
- Independent review found missed no-result and watchdog failure notifications,
  plus a stale-URL rewrite race in the first in-app completion helper. Reproduced
  all three RED: empty-result callback sent twice to Telegram, watchdog failure
  sent twice despite a one-time refund, and controlled interleaving overwrote an
  already-terminal URL. Guards now cover both notifications. Completion runs the
  existing shared acceptance/repeat hooks without another unconditional result
  rewrite; the controlled race is GREEN. Final focused origin matrix: 17 passed;
  the expanded callback/poller/pricing/refund matrix passed 148 tests.
- #422 release recovery: first autodeploy attempt stopped at the backup free-space
  gate (about 35 MiB below its 10-GiB reserve); running release stayed healthy at
  00b40366. Read-only Docker disk audit identified unused builder cache. Pruned
  only cache older than 24 hours with explicit retained-cache/free-space bounds,
  reclaiming 4.275 GB; available root space verified at 14,882,099,200 bytes.
  Failed GitHub deploy jobs for exact b9834c7 were rerun normally; no manual deploy,
  backup deletion, volume/image/container prune or financial mutation.
- Owner financial-scope answer on 07 November: common account/common balance
  after voluntary linking, with independently usable VK entry. The separate-wallet
  interim alternative is rejected. Precision exceptions, writer fencing and live
  cutover remain explicit engineering/accounting gates; no real money was moved.
- Both independent reviewers rechecked 193d9e1: no remaining actionable findings.
- #422 exact merge/release b9834c795707dc3037340ea553f41c1ea50f0f9b:
  main CI and autodeploy attempt 2 succeeded; Docker revision/healthy state,
  Telegram and VK revision endpoints, backend health and unauthenticated 401
  checked. Published Telegram and VK category-upload/reference HTTP browser
  smokes passed with all API/media/provider actions intercepted. Post-release
  12-minute log sample: zero tracebacks/preview failures; three GPT Image 2 task
  failures observed separately, not attributed to this frontend-only change.
