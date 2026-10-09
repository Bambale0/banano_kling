# Referral notifications supporting test evidence

The designated execution record is docs/agents/EXECUTION.md; this file retains
the detailed verification evidence linked from that record.

Publication baseline: tanyapi 31d02d43dd0d2bb18904eea588ac90ea40e2fe1f (PR281).
Initial diagnosis used production 23b52ad9c20ef3d78434d4da9322ea9f8e66cb29 (PR280).
Follow-up baseline: 482c424c971e86404666bc7dfc04010ba7923bc9 (PR282); its deployment was cancelled before SSH.
Task: restore immediate new-referral messages and add separate bonus receipts.

## Audit and invariants
- PR279 disabled both direct attachment notification flags; accepted-generation
  credit had no notification dispatch. Registration and balance accounting worked.
- Cover all three binding paths through record_pending_invite_bonus.
- No changes to qualification, balances, admin prices, partner percentages, or
  historical claims. No real test messages and no notification backfill.
- New additive empty outbox schema through existing init/deploy mechanisms.
- Shared snapshot delivery, unique event keys, fenced claims, retry_after, receipt
  recovery and explicit uncertain states; no promise of exactly-once API delivery.

## Steps
1. Inspect baseline and exact regression: complete
2. Isolated implementation and additive schema: complete
3. SQLite, PostgreSQL CI, offline bot/Mini App/public-seam checks: pending
4. Independent review and regression fixes: complete; storage failure and log redaction fixes verified
5. Draft PR and exact-head required CI: pending
6. Protected merge, exact deployed SHA, health and bounded telemetry: pending

## Verification scope
Frontend behavior is unchanged; backend public entrypoints and worker lifecycle
need coverage. Existing full safe regression and required browser/Docker/deploy
checks remain release gates. PostgreSQL cannot run locally in this container;
the dedicated disposable CI job is required. All Bot API calls in tests are mocked.

## Current checks
- Focused referral/policy/share tests: 134 passed (new tests still being extended).
- Broad local run: 3056 passed, 22 skipped, 12 subtests passed; the bundled legal
  PDF is absent and restricted PostgreSQL adapter-dependent cases cannot collect
  or initialize here. No functional failure found in executable cases.
- New/changed runtime Python and PostgreSQL test lint: clean. Existing referral
  service has 12 unrelated legacy lint findings; changed lines are comments only.
- Exact full backend and real PostgreSQL checks will run in GitHub, without local
  environment exclusions. Independent fault-injection review passed.

## Corrective follow-up
- PR282 merged as 482c424c971e86404666bc7dfc04010ba7923bc9 after all four required
  CI gates passed; user cancelled its deployment before any SSH deploy started.
- Reproduced five failures for never-started recipients and retry-claim budgets;
  corrected both without changing financial rules or replaying old notices.
- Managed settings and templates reuse existing bot_settings and authenticated
  read/set/reset admin command, including bounded JSON document transport.
- Independent review also found and verified fixes for huge-number fallback,
  unsafe template attribute/link contexts, and retry-limit ordering changes.
- Expanded notification tests: 114 passed; exact final full backend/PostgreSQL CI
  and protected corrected release remain required. No production fix claimed.
