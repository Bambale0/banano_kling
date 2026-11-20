# NEUROMIX — read-only financial cutover readiness: operational evidence

Date: 2026-11-20. Target: tanyapi. This is a reporting-only expansion of scripts/audit_shared_account_migration.py; not a wallet import, payment change, new source of truth, or approval to activate the shared ledger.

## Confirmed root cause and safety boundary

The existing Telegram legacy balance is users.credits (double precision), while the new shared_wallets ledger is a separate authority. Existing transactions do not form a complete balance journal; some historical events are already reflected in users.credits. A snapshot with only user counts and balance precision cannot prove whether jobs, provider callbacks, payment reconciliation, admin credits, bonus or refunds may still mutate the legacy source.

The expanded audit runs inside one PostgreSQL REPEATABLE READ READ ONLY transaction with a 15-second statement timeout. It performs fixed SELECT/status aggregates and queries only group-level shared-wallet counts and totals. There are no UPDATE/INSERT/DDL, per-user rows, account IDs, payment identifiers, private prompts, tokens or provider secrets in its operational output. The pre-existing streamed balance classifier remains unchanged.

## New operational_readiness fields

- legacy_generation_status_counts and legacy_transaction_status_counts: exact aggregate counts by stored status. Unknown/new statuses are conservatively nonterminal, not assumed successful.
- nonterminal_generations and unreconciled_transaction_statuses: diagnostics requiring per-event investigation, not amounts owed or confirmed outstanding purchases.
- wallet_scopes: group-level shared-wallet count and available/reserved units, or null if schema is missing.
- opening_claims_by_scope: group count of opening claims, no identities/amounts; absent schema is a hard blocker.
- production_cutover_authorized is always false. Cutover blockers always include unfenced writers, unapproved immutable opening snapshot, unverified event watermarks and historical refund mapping. Additional blockers include unresolved jobs/payments, missing schema and non-exact balances. No automatic approval can be inferred from zero pending records.

## Real production read-only preflight, 2026-11-20

- Legacy users: 94,524; generation_tasks: 392,420; transactions: 36,043.
- Generation statuses: completed 357,052; failed 35,362; pending 2; processing 4. Thus 6 nonterminal jobs needing provider/task settlement checks.
- Transaction statuses: completed 18,354; failed 5,529; pending 12,160. Pending is an internal stored status, NOT evidence that 12,160 external provider payments are waiting, paid or owed.
- Balance classification: 93,670 exact at four decimals; 854 precision_review; 0 invalid. Exact subtotal excludes the 854 blocked rows and MUST NOT be described as total customer liability.
- Shared wallet groups: 45 live and 45 sandbox wallets, each aggregate available/reserved 0 units; zero opening claims. This means the live financial cutover has NOT happened.
- The report explicitly says production_cutover_authorized=false. Executed in the running application's environment by passing the audited script over stdin to Python, using configured DATABASE_URL only inside the container. No credentials were printed, exported or changed.

## Approval gates before any live wallet switch

1. Inventory and fence all legacy payment/admin/bonus/referral/charge/retry/timeout/refund writers, including direct SQL; produce runtime evidence every writer is disabled for the selected cohort.
2. Produce an immutable manifest and event watermark: source DB lineage, raw balance/type, identity mapping, approved versioned precision decision and signed delta; zero unexplained differences. Resolve 854 precision-review cases without silent rounding.
3. Reconcile six currently nonterminal tasks to provider task status, outstanding captures/refunds and delivery. Do not double-reserve or double-refund a job already charged in legacy.
4. Investigate each pending transaction *by provider event identity*, age, idempotency key, webhook outcome and legacy balance inclusion; a status count alone is not a payment reconciliation.
5. Implement and test a durable cross-DB writer fence, one-time opening claim, old-event dedup/replay, missing webhook recovery, late refund mapping, rollback, account merge and concurrent spends in PostgreSQL. Existing sandbox opening rehearsal cannot authorize live claims.
6. Only then approve a controlled cohort cutover with exact counts and sums, signed operator evidence and production smoke. Never flip a live financial flag based on this script output.

## Test evidence

Three new TDD tests first failed because the operational summarizer did not exist. They now verify pending/nonterminal/unknown statuses, no write SQL, zero-pending still blocked, and fail-closed behavior when shared-wallet schema is absent. Existing VK precision/read-only tests remain unchanged. Actual running production PostgreSQL audit confirmed read-only execution and the aggregate status figures above. Full protected-branch CI and review are required before merging.

Rollback: revert this reporting-only addition. It creates no schema, money entry, user/task mutation or payment call.

## Extended read-only provider/age preflight — later snapshot on 2026-11-20

The exact same READ ONLY REPEATABLE READ PostgreSQL transaction now additionally produces:

- pending_transactions_by_provider_age: count of internally pending payment attempts by provider, including entries older than 1/7/30 days, aggregated without provider invoice IDs or user data. These are not confirmed external payments.
- unresolved_generations_by_model_age: incomplete task counts by model/status and entries older than one day; no prompts or task IDs.
- A fail-closed consistency check: total pending-provider groups must exactly equal the pending transaction status count in the same DB snapshot, and grouped unresolved generation counts must exactly equal nonterminal generation status counts. A mismatch raises an error instead of printing a misleading readiness result.

Real later snapshot (numbers change with live traffic): 94,528 Telegram users, 392,424 tasks, 36,057 transaction records, 12,173 pending-status transactions, 6 nonterminal tasks, 854 balances requiring precision review, zero opening claims and 45 live/45 sandbox wallets (both zero aggregate funds).

Pending by provider: Robokassa 6,070 (6,070 older than 7d); FreeKassa 3,571 (3,100 older than 7d); Telegram Stars 2,423 (2,271 older than 7d); Lava 52 (34 older than 7d); Prodamus 52 (52 older than 7d); CryptoBot 5 (0 older than 7d). These are stored transaction statuses; no decision about money or actual provider settlement was made.

Unresolved generation model counts: Wan 3 processing 4 (all older than 1 day); Banana Pro pending 1; Seedream 5 Pro pending 1. The Wan 3 entries require targeted provider reconciliation. There is no retry or refund initiated by this audit.

Regression after extension: 124 backend tests passed, 21 skipped (payment, audit, wallet opening rehearsal, webhook paths and provider outage); Ruff, compilation and diff checks pass. TDD also tests that an inconsistent aggregate fails closed.

Cutover remains explicitly NOT AUTHORIZED. The correct remediation is provider-level payment reconciliation by immutable event identity, followed by a writer-fenced signed opening manifest and exactly-once balance migration, not bulk marking pending records failed.
