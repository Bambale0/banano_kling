# TG–VK legacy settlement preflight (read-only)

Scope: financial migration gates #408, #410, #414. This tool reports **why**
existing balances cannot yet be imported. It does not change either database,
perform provider calls, normalize decimals, fund a wallet or authorize cutover.

## Running on the trusted production host

Run with the same, freshly checked script version in both processes:

```bash
set -o pipefail
SCRIPT=/root/tanya/banano_kling/scripts/audit_linked_balance_preflight.py
cat "$SCRIPT" \
  | docker exec -i banano-kling-bot python - --emit-telegram \
  | python3 "$SCRIPT" --vk-sqlite /root/vktanya/vkbanana.db
```

The producer reads linked Telegram users, task and payment statuses in **one
REPEATABLE READ READ ONLY PostgreSQL transaction**. The consumer opens SQLite in
read-only mode and aggregates VK balances/tasks/payments in one VK read snapshot.
The two snapshots are **not** atomic with respect to each other. Production
financial writers remain live, so repeating this command can produce different
counts even seconds later.

The sensitive row stream is piped directly between programs; do not redirect
it to logs, shell history or report files. Normal output contains **no
user IDs, order IDs, payment IDs, balances per user, DSN or secrets**.
Unrecognized payment providers or statuses are counted as `other` rather than
reported verbatim. If a source table disappears, summary fields are missing,
counts contradict each other, VK IDs repeat or the source stream truncates, the
tool fails closed.

## Interpretation and required next steps

- `snapshot_exception_count`: unsupported precision, negative/unusable
  balances and VK users missing from local SQLite. **Do not round or clamp**.
  Review raw source values in an approved, access-controlled manifest; reconcile
  source lineage and obtain explicit conversion decisions.
- `settlement_review.telegram_unsettled_payments`: historical Telegram
  transactions that are not in known terminal states. The
  `telegram_unsettled_payment_providers` breakdown identifies the owner of the
  next **read-only provider verification**. A `pending` row does **not** prove
  payment happened. Do not auto-mark it paid, failed or give credits.
- `settlement_review.vk_unsettled_payments`: pending/unknown VK payments. A
  VK Lava webhook may arrive late or repeat; record original provider IDs and
  the legacy transaction's settlement lineage in the migration manifest.
- `telegram_nonterminal_tasks` / `vk_nonterminal_tasks`: tasks that need
  provider completion, capture/refund and delivery reconciliation **before**
  release; absent active tasks do not prove absence of late callbacks.
- `vk_status_tables_missing`: missing native tables prevent a reliable
  settlement audit.
- `source.live_wallets_with_funds=0` is **not** evidence the balances have
  merged. The sandbox ledger is separate from live money.
- `financial_cutover_allowed=false` is unconditional: this tool **cannot**
  certify writer fencing, a durable checkpoint/epoch, cross-source snapshot,
  idempotent late-event bridge or live openings. These are separate mandatory
  release requirements.

For a real financial cutover, require a consistent source proof signed by the
operator, tested per-user TG and VK writer fences, an exact 1e-4 conversion
policy for every exception, provider settlement reconciliation with original
event IDs, a crash-resumable cross-database checkpoint, and verified wallet
opening/recovery paths. Preserve old writes until all flows are cut over under
a stable authority epoch. Never enable an independent dual-write period.

Implementation and regression test:
`scripts/audit_linked_balance_preflight.py` and
`tests/test_linked_balance_preflight_unittest.py`.
