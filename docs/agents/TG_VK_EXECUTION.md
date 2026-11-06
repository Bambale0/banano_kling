# TG–VK shared accounts execution ledger

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
