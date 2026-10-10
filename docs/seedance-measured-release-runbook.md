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
docker exec banano-kling-bot python -c 'from pathlib import Path; p=Path("/app/data/seedance-launches.paused"); print("paused=" + str(p.exists()))'
```

The common receipt store checks the marker under the claim lock, after media checks and immediately before debit. Quotes already claimed before the marker may finish their one provider submission. Existing submitting, unknown and accepted receipts remain replayable; callbacks, reconciliation and refunds continue. UI changes alone are not an admission stop.

After an authorized resume, remove only this marker:

```sh
cd /root/tanya/banano_kling
rm -- data/seedance-launches.paused
```

## Read-only drain check

Use the established authenticated PostgreSQL operator connection; never print its connection string. Run the following read-only SQL (no application database adapter import):

```sql
SELECT q.phase, q.canonical_bound, COALESCE(t.status, 'missing') AS task_status,
       COUNT(*) AS receipt_count
FROM seedance_quote_receipts q
LEFT JOIN generation_tasks t ON t.task_id = q.provider_task_id
WHERE q.phase IN ('submitting', 'outcome_unknown')
   OR (q.phase = 'accepted' AND
       (q.canonical_bound = 0 OR t.task_id IS NULL OR t.status NOT IN ('completed', 'failed')))
GROUP BY q.phase, q.canonical_bound, COALESCE(t.status, 'missing');
```

Any row blocks rollback to a backend lacking the measured receipt guards. Missing canonical tasks and unknown provider outcomes are unresolved, never evidence of failure. Do not refund or resubmit them to make the drain appear empty.

## Rollback

Prefer pausing new claims while retaining the newly deployed backend recovery/refund lifecycle. A frontend rollback may then be used only if it cannot start unquoted measured requests; backend requires the frozen quote and remains authoritative. Do not automatically restore a pre-release database backup after live charges: that would discard subsequent receipts and balance operations. Preserve all backups, new tables and media leases. A backend rollback requires a separately reviewed compatibility plan even after the drain is empty; never blindly run the old watchdog over new receipts.

Tests cover blocked new debit, accepted/unknown replay during pause, fail-closed marker inspection and unchanged provider-acceptance safety. No production marker, generation, Telegram message, refund or historical migration is executed by these tests.
