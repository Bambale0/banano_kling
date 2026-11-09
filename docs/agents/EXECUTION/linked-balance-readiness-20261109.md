# TG ↔ VK linked legacy balances — production read-only preflight

**State:** financial cutover **BLOCKED**; no user money changed.
**Baseline:** tanyapi@65d7b585d8f63ee57406286bf5a5732081014509.
Related: [Epic #408](https://github.com/Bambale0/banano_kling/issues/408),
[Migration #414](https://github.com/Bambale0/banano_kling/issues/414),
[Telegram writer fence #424](https://github.com/Bambale0/banano_kling/pull/424),
[VK writer fence #67](https://github.com/Bambale0/tanyavk/pull/67).

The linked-account identity flow works, but VK Mini App financial reads
resolve to Telegram legacy users. The independent VK text bot still uses
its SQLite legacy users.balance; Telegram uses PostgreSQL users.credits.
Shared live wallets have not been populated with these legacy sources.
The shared wallet merge only transfers *existing shared-wallet* entries.

## Safe operator probe

From the trusted tanyapi host (do not send source rows to log collectors):

    set -euo pipefail
    cd /root/tanya/banano_kling
    cat scripts/audit_linked_balance_preflight.py \
      | docker exec -i banano-kling-bot python - --emit-telegram \
      | python3 scripts/audit_linked_balance_preflight.py \
          --vk-sqlite /root/vktanya/vkbanana.db

The producer runs within the existing TG container with its configured
PostgreSQL DSN. The source rows remain only in a local pipe and the report
prints aggregate counts, no per-person identity or money data. PostgreSQL
uses READ ONLY REPEATABLE READ; the VK SQLite reader uses query_only and a
separate transaction. This is *not* an atomic snapshot across both
databases; legacy writers may change data during the run. It is never
authorization to move balances. A partial pipe/missing end fails closed.

## Observations — 9 November 2026

- 16 committed link operations and 13 linked VK/TG identity pairs.
- 12 VK legacy user rows among the pairs; one missing VK user row.
- In the paired cohort: 7 Telegram precision-review balances, 1 VK
  precision-review balance and 9 readiness exceptions including the
  missing VK user row.
- 0 shared live wallets with funds and 0 live-wallet link transfers.
- VK paired-cohort statuses: 13 pending payments, 1 confirmed, 4 failed,
  13 cancelled; 559 completed and 82 failed generation tasks.
- Overall legacy databases: Telegram 89,497 users (806 precision review);
  VK 7,304 users (215 precision review, 1 invalid).
- VK balance_units is a stale derived column, not additional funds.

The statuses/totals are a moving observation, not migration manifest.
Pending does not establish whether a provider actually charged the payer.
Precision exceptions must not be silently rounded.

## Remaining hard financial release gates

1. Reconcile previously linked accounts including missing VK rows,
   historical refunds/bonuses and any identity conflicts.
2. Approve an exact monetary precision/negative-balance policy, preserve
   raw evidence and hash in immutable receipts.
3. Roll out and verify durable fences for *every* TG and VK legacy writer
   including admin, provider, payment, refund and queued jobs.
4. Drain/settle pending payments, late callbacks and tasks, then capture
   immutable backups and verify PostgreSQL + SQLite restore rehearsal.
5. Take consistent writer-fenced opening manifests; implement idempotent
   one-time live source claims, zero claims, crash/restart/checkpoint
   reconciliation and correct reserved funds/late settlement mapping.
6. Migrate all reads/writers, including native VK text bot, to a single
   authoritative money ledger without invented Telegram IDs.
7. Pass SQLite + native PostgreSQL integration, concurrent payment/spend,
   webhook replay and failover tests, then real signed VK/TG device smoke,
   exact deployed SHA and post-release drift monitoring.

The existing OpeningImportRehearsal is sandbox only. Do not use it for
live balances or modify linked balances by ad hoc SQL.

## Change/test record

- scripts/audit_linked_balance_preflight.py: read-only producer and
  consumer with strict stream completion and aggregate diagnostics.
- tests/test_linked_balance_preflight_unittest.py: isolated tests,
  reproducible without bot runtime or production credentials.
- Live read-only preflight and six standalone regressions passed.
- No schema, financial, provider, authentication or pricing edits.
- Guidance applied: Bambale0/skills diagnosing-bugs/TDD;
  Bambale0/claw backend-integration; reviewed anthropics/skills
  webapp-testing for the pending browser acceptance phase.
