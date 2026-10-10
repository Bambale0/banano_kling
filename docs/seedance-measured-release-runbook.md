# Measured Seedance release and rollback gate

Scope: new fixed-output Seedance 2 / 2.5 and source-locked 2.5 edit/identity quotes. Free Auto, Omni and legacy Motion/Glow are not covered by this pause switch. No rates, historical ledger or old accepted quotes are rewritten.

## Before release

- Root sends the user the pre-release report before merge/deploy.
- Exact head independent review and required CI must pass.
- Verify current production SHA, working-tree status, free disk and successful pre-deploy database backup. Preserve dirty runtime price.json and unrelated files.
- Deploy only with separately reviewed maintenance gates: no implicit historical media backfill or backup deletion.
- Three feature-owned tables are created idempotently with a PostgreSQL advisory transaction lock. No historical data migration is performed.

## Stop NEW measured launches, retain recovery

These commands are documented operator actions, not executed by tests or by this change. Run only on Tanya after operator authorization:

```sh
cd /root/tanya/banano_kling
# Atomic creation; no secrets or financial writes.
: > data/seedance-launches.paused
# Verify the actual container sees the marker and disallows new claims.
docker exec banano-kling-bot python -c 'import importlib.util; s=importlib.util.spec_from_file_location("gate", "/app/bot/services/seedance_launch_gate.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print("paused=" + str(not m.launches_allowed()))'
```

The common receipt store checks the marker under the claim lock, after media checks and immediately before debit. A claim that passed the marker check before its creation may commit afterward and finish its one provider submission. Marker creation alone is not a quiescence barrier; perform the synchronized drain below. Existing submitting, unknown and accepted receipts remain replayable; callbacks, reconciliation and refunds continue. UI changes alone are not an admission stop.

After an authorized resume, remove only this marker:

```sh
cd /root/tanya/banano_kling
rm -- data/seedance-launches.paused
```

## Synchronized drain check (no data changes)

Use the established authenticated PostgreSQL operator connection; never print its connection string. After verifying the marker is active, run the following transaction (no data writes and no application database adapter import). The row lock waits for any claim that passed admission before the marker. READ COMMITTED ensures the subsequent query sees those committed receipts. The first SELECT must return id=1; a missing row or timeout makes the check inconclusive. Keep the marker in place throughout.

```sql
BEGIN ISOLATION LEVEL READ COMMITTED;
SET LOCAL lock_timeout = '30s';
SELECT id FROM wan3_prime_storage_lock WHERE id = 1 FOR UPDATE;
SELECT q.phase, q.canonical_bound, COALESCE(t.status, 'missing') AS task_status,
       COUNT(*) AS receipt_count
FROM seedance_quote_receipts q
LEFT JOIN generation_tasks t ON t.task_id = q.provider_task_id
WHERE q.phase IN ('submitting', 'outcome_unknown')
   OR (q.phase = 'accepted' AND
       (q.canonical_bound = 0 OR t.task_id IS NULL OR t.status NOT IN ('completed', 'failed')))
GROUP BY q.phase, q.canonical_bound, COALESCE(t.status, 'missing');
COMMIT;
```

Any row blocks rollback to a backend lacking the measured receipt guards. Missing canonical tasks and unknown provider outcomes are unresolved, never evidence of failure. Do not refund or resubmit them to make the drain appear empty.

## Rollback

Prefer pausing new claims while retaining the newly deployed backend recovery/refund lifecycle. A frontend rollback may then be used only if it cannot start unquoted measured requests; backend requires the frozen quote and remains authoritative. Do not automatically restore a pre-release database backup after live charges: that would discard subsequent receipts and balance operations. Preserve all backups, new tables and media leases. A backend rollback requires a separately reviewed compatibility plan even after the drain is empty; never blindly run the old watchdog over new receipts.

Tests cover blocked new debit, accepted/unknown replay during pause, fail-closed marker inspection and unchanged provider-acceptance safety. No production marker, generation, Telegram message, refund or historical migration is executed by these tests.
