# TG–VK shared accounts execution ledger

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
