# Creator pricing: WAN and Genjutsu

Baseline: 3621abeb3f6228b555a6d9477f405b8acd2a4432 (tanyapi).
Scope: existing authenticated Creator membership, separate administrator-edited rates for WAN3, WAN3 Prime and each Genjutsu operation/resolution. No automatic discount, config migration, membership assignment or historical balance change.

## Audit and decisions
- Existing Seedance creator config has an all-required-quality gate. New optional prices must not invalidate an already configured Seedance tariff.
- WAN uses a shared Telegram/MiniApp/trend/repeat lifecycle. Fixed charge is rate times measured input-video seconds plus selected output seconds; Auto reserves 30 seconds and settles against the accepted rate.
- Genjutsu stores per-step rates, variants and reservations independently of published feed tasks. Personal overrides must retain original operational settings and config hashes, with a separate rate/profile revision.
- Missing new cells retain each model's ordinary rate. Genjutsu rates remain integer credits/second as required by its existing ledger.
- Existing retries return accepted receipts before repricing. Fresh admissions revalidate membership in the debit transaction; historical settlement remains frozen.
- Admin editing retains existing permissions, confirmation, stale-editor fingerprint and audit. No operational prices are supplied by this code.

## Verification seams
1. Pure pricing validation and partial fallback, legacy Seedance compatibility.
2. Actual WAN quote formula, actor-specific admission, reserve/settlement/replay and membership revocation.
3. Genjutsu quote/start and bootstrap/recipe display; multi-step/variant billing and historical replay.
4. Telegram admin edit permissions and ordinary-price preservation.
5. Official full application and PostgreSQL CI; local application imports are prohibited by task constraints.

## Progress
- Read AGENTS and existing pricing/admin/lifecycle contracts. Used local Bambale0 skills TDD/code-review, Claw README and Anthropic webapp-testing guidance. Playbook refresh was previously denied; not retried or reported as refreshed.
- Pure pricing test RED: 2 failures + 2 errors before changes; GREEN after optional registry/Genjutsu overlay.
- WAN rate snapshot test RED missing helper; GREEN after implementation.
- Actual WAN fixed/Auto quote test RED unsupported tariff keyword; GREEN after shared lifecycle integration. Current isolated pricing 6/6 and existing WAN model contract 9/9 PASS.
- Full application tests are prepared for official CI, not executed locally.

## Release gates
Independent exact-diff review, all required CI, parent pre-release report, authorized guarded merge, exact release CI/CD, runtime/version/health/config-hash verification. No paid generation smoke. No price file writes or historical backfill.
