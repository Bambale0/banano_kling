# TG/VK opening balances: readiness and rehearsal

Status: **NOT READY for production financial cutover**. Extends #408/#410/#414
and the existing Draft #415 wallet; no competing wallet implementation.
Audit: 2026-11-06. TG baseline `f1e8b32e873dd27dc36daa6cfa6c0ea54340ea04`;
VK master `cbbfb48ab494591b60ab06fd81a76a3cee69c08e`.

This is a source audit and isolated synthetic testing. Production logs, databases,
deployed SHAs and individual historical corrections were not re-read. The
6092/7241 discrepancy is the 05 November observation in #408, not a fresh count.

## Operational sources

| Platform | Source confirmed in code | Evidence |
|---|---|---|
| Telegram | `users.credits`, mapped by internal users.id and verified telegram_id | `bot/database.py`: get_user_credits, add_credits, deduct_credits, complete_payment_atomic, plus lifecycle SQL below. Production double precision was observed in #408. Bootstrap upgrades integer credits to NUMERIC(12,4) but leaves existing double precision unchanged. Schema files cannot establish deployed precision. |
| VK | `users.balance`, keyed by user_id | Both `vk_bot_lp.py::Database` and `vktanya/repositories/database.py::Database` read/write balance. Legacy entrypoint uses its own class; extracted repository must also be fenced if enabled. Modular PostgreSQL infrastructure is not proof of a financial migration. |
| VK units | **Not authority or additional money** | Initializers add balance_units, transaction amount_units and task cost_units with DEFAULT 0, without backfill. Audited financial methods do not maintain them. Never sum them with balance, take max, or fallback automatically. |

## Writer inventory and execution paths

| Mutation | Telegram -> storage | VK -> storage |
|---|---|---|
| Payment | webhook/pending reconciliation -> handlers/payments._complete_transaction -> database.complete_payment_atomic: conditional payment transition, credit/promo/partner work in one transaction | Lava/legacy confirmation -> complete_payment_once or complete_payment_with_rewards_once: status CAS and balance credit in BEGIN IMMEDIATE |
| Ordinary generation / analysis | Mini App, trend_api, generation/common/batch handlers -> deduct_credits; photo/video_prompt_billing refund with add_credits | _charge_task -> update_balance, or create_task_and_charge_atomic -> debit + transaction + task |
| Specialized jobs | genjutsu/repository, services/kling4_lifecycle, motion_launch_receipts, wan3_prime_lifecycle: direct credits SQL and own receipt/settlement states | create_task_and_charge_atomic; provider callbacks/polling -> task state and refund_task_once |
| Failure/timeout/recovery | main.py, miniapp.py and handlers -> add_credits; task_watchdog.force_fail_task, database.cleanup_stale_local_generation_tasks, Seedance compatibility and specialized lifecycles also write directly | refund_task_once credits stored cost and atomically marks refunded=1 |
| Admin | handlers/admin -> add/deduct; internal_admin_user_commands and internal_admin_operations refunds -> direct SQL with separate idempotency/partial refund records | admin handler -> update_balance with reason; no source-event idempotency key on generic adjustment |
| Starting/promo/invite | creation/start bonus, attach_referral_code, promo redemption, partner_policy.activate_inviter_bonus_once -> credits | get_or_create_user inserts starting balance without transaction; promo and invite methods change balance + transaction |
| Partner conversion/rewards | exchange_partner_balance_to_credits debits partner RUB, credits whole bananas; repeat rewards/withdrawals use separate RUB state | referral_earnings_rub is separate, but historical transactions.amount also contains RUB referral entries; not a single-currency banana ledger |

Changing add/deduct alone misses lifecycle/admin/recovery SQL. Every listed
writer, worker, webhook and external administrative script must obey cutover.
TG payment transactions are not a complete balance journal; VK transaction SUM
also omits starting money and mixes currencies. Neither can reconstruct opening.

## VK discrepancy: evidence and limits

Hypotheses considered: (1) incomplete units migration/stale shadow; (2) scale or
rounding mismatch between active writers; (3) restores/manual scripts/uninspected
deployed writer. Source supports (1): zero-default columns, no backfill, balance-only
mutations. Rounding alone cannot explain a shadow untouched by positive credits.
(3) remains possible for individual rows until production history is reviewed.

Synthetic SQLite reproduction executed the actual AST-extracted Database class
from both files without importing the bot/network runtime: start 10 / units 0;
admin +2.5; charge 1.125; refund once; repeated refund rejected. End **12.5 / units
0**, transaction SUM **2.5**. This proves stale units and incomplete journal in
a clean DB, not the cause of each historical user discrepancy.

Additional source risks requiring conversion/fencing: VK negative update_balance
prechecks without BEGIN IMMEDIATE/conditional UPDATE; invite bonus reads before
an unguarded claim. TG generic add_credits has no source-event key; photo/video
analysis refund helpers can credit again when invoked twice. The rehearsal does
not fix these legacy paths or claim they caused a particular production incident.

## Precision

VK parse_price and TG Credits use binary float. SQLite INTEGER affinity permits
REAL fractional balance. VK has round-to-two and :g display variants; TG Credits
formats one decimal and response helpers may round four. Never snapshot displays.
Current price/admin role must not reconstruct a historical debit; cost_units is
stale too. Partner conversion explicitly rounds RUB to 2 places and truncates
banana quantity with int; keep that historical result, do not replay conversion.

Shared precision is 10,000 units/banana: 1.125 -> 11250 units. Values such as
0.30000000000000004 and 1.00005 require review, never silent rounding. NULL,
negative, non-finite and overflow balances block import; negative is not zero.
No float normalization policy is approved. Preserve raw value/type, proposed
exact amount, signed difference, normalization rule/version and approval. Classify
float residuals separately from economically meaningful fractions. Rehearsal
rejects excess precision; no HALF_UP/HALF_EVEN/tolerance is silently chosen.

Read-only preflight classifies exact/review/invalid and exact-unit subtotal.
Subtotal excludes blocked rows; it is not total liability. VK uses an explicit
read transaction; PG uses REPEATABLE READ READ ONLY. Legacy mismatch tolerance
is diagnostic only, never import policy. Invalid/NULL unit comparisons are reported.

## Checkable one-time import rules

1. Establish immutable source DB lineage per platform. Export verified identity
   and legacy mapping, raw balance/type, source version/epoch, normalization
   evidence and event watermarks in a hashed manifest. TG/VK numeric IDs are scoped.
2. Freeze every legacy writer and callback consumer for the cohort; queue late
   events, block new jobs, persist authority state/epoch and fence acknowledgements.
   Timestamp or caller Boolean is not proof. VK SQLite + shared PG require durable
   frozen state/reconciliation, not an assumed cross-database atomic transaction.
3. Record payment/promo/referral/admin event IDs already included in opening and
   partial-refund state. Replayed pre-snapshot events must not credit again. Keys
   include platform/provider/legacy event ID, not a fresh request UUID.
4. Drain/reconcile uncertain launches and accepted jobs for the first cohort, or
   build a legacy settlement bridge first. Pending-job debits are already removed
   from available: do not subtract again as new reserves or restore as free funds.
   Map captured/refunded amounts and reserve liabilities explicitly. New refund
   requires a capture; a legacy refund cannot simply point to an opening entry.
5. Claim once by (scope, platform, external_id), independent of snapshot version
   and canonical account. Same manifest/amount replays; changed amount/evidence/
   snapshot conflicts. Zero also consumes a claim. Claim + opening journal commit
   together; failure/overflow rolls back both. Claims remain append-only.
6. Merge only verified identities with both confirmations. Retain claims on aliases
   and move reserves with paired transfers; no starting bonus on merge. Use existing
   canonical wallet locks for import/merge/concurrent spending.
7. Per identity/cohort reconcile counts/claims/events and exact money: approved
   openings + new credits + refunds - captures = available + reserved. Transfers
   net to zero. Require zero unexplained deltas and explicit reserve liabilities.
8. Activate shared-only writes after import verification; consume queued events
   through durable source-ID dedup/settlement mapping. Outage fails closed; no local
   VK spending fallback. Rollback after activation uses compensating shared entries,
   not old writable balances.

## Delivered boundary and remaining gates

OpeningImportRehearsal is internal, sandbox-only, built on WalletService locks,
append and canonicalization. No route, CLI, live reader or import switch exists;
claims table only permits sandbox. Evidence SHA identifies a synthetic manifest,
not a verified writer fence. API cannot submit opening. Positive/zero claims,
replay/conflict, ownership, merge aliases, races, overflow and rollback are covered.
Historical payment/capture/reserve/event watermark import is deliberately absent.

| Release blocker | Required evidence |
|---|---|
| Legacy writers remain authoritative | Convert full inventory; prove old mutations rejected at DB/service boundary, including admin/recovery |
| Live snapshot unverified | Confirm deployed source, fresh read-only report, manifest counts/totals, resolve every exception |
| Precision policy unresolved | Approved versioned normalization; raw values and signed differences retained |
| Old events already reflected in balance | Durable event watermark/mapping; replay before/after barrier credits once |
| Late legacy refunds lack shared capture | Drain jobs or implement historical paid/settlement mapping; no second reserve or fabricated credit |
| Cross-DB authority protocol missing | Crash/retry tests at freeze/import/activate; outage fail closed; no dual writers |
| Production runner absent | Approved dry-run manifests, resumable batches, exact cohort reconciliation; no sandbox promotion |
| PostgreSQL not available locally | Existing isolated PG CI job must pass new opening cases for exact published SHA |

No real balances, production schema/config, offer, provider requests or deployment
changed. PR remains Draft; auto-merge off.
