# Web finance boundary: dark, provider-verified, idempotent checkout

Date: 2026-11-20. Target: tanyapi, baseline 15ea1667185c4a3194ee2aecbdefcceeb7d8a9b8. Related: #646 draft, #652 financial preflight, #656 read-only website.

## Confirmed source of truth and current blockers

- Legacy Telegram users.credits is float; shared_wallets live is independent exact integer ledger. Opening claims are sandbox-only. No live financial cutover has taken place.
- Read-only production preflight observed 854 balances needing approved precision, 12k+ pending-status payment records, six nonterminal tasks, and zero live opening claims. These counts do not prove external provider status, and MUST NOT be bulk mutated.
- Draft #646 contains web generation and payment handlers but remains unverified with real provider callbacks, media/S3 results and transaction end-to-end checks. It must not be merged to production as a whole.

## Implemented safe part of independent web finance

1. Owner is derived only from a revocable HttpOnly website session. Client-supplied account IDs never select a wallet.
2. Non-Stars website Lava checkout creates immutable account/request-key orders. For each invoice, amount in RUB minor units, purchased credits and provider contract are snapshotted. The public client never selects payable credits or price.
3. Web callback is considered ONLY after existing provider webhook IP or configured credential verification. Callback and periodic reconciliation re-query provider invoice ID, contract, currency and amount. A signed external event alone cannot mint money.
4. Same durable live-wallet journal operation (web:topup:order_id) for webhook, retries and reconciliation. Repeated payment delivery has no extra credit.
5. Linked legacy Telegram/VK users get 409 FINANCIAL_CUTOVER_REQUIRED; browser-only identities alone may eventually use this separate ledger.
6. Checkout is strictly disabled unless WEB_NATIVE_PAYMENTS_ENABLED and WEB_NATIVE_GENERATION_ENABLED are both true AND the generation backend handler exists and says ready. It is NOT shipped in this slice, so real money cannot be accepted via these routes.
7. Rollback disables new invoices, not recovery of an existing paid invoice. Read-only table presence probes avoid DDL for old Telegram callbacks.
8. Uncertain provider-create outcomes are not blindly retried. S3, prices, legacy balances and existing generation tasks are not mutated by rollout.

## Test evidence

- Six Python unittest guards pass on host: no generation path means no sales; linked actor cannot create second wallet; anonymous actor rejected; exact currency/amount verification.
- Three backend pytest integrations prepared for isolated GitHub CI: concurrent same-key idempotency, forged amount rejection and recovery after provider lookup failure even after checkout flag rollback.
- Python compileall and diff check pass. No live payment/provider call or production migration was performed.

## Not yet production-authorized

THIS PR DOES NOT DELIVER 100% FINANCIAL PARITY. Full release still requires generation adapters; verified S3 delivery and balance capture/release; real provider invoice and webhook smoke; legacy writer fencing and signed opening manifest; 854 precision cases reviewed; historical payment/refund event reconciliation; partner payouts; linked account merging. Keep both feature flags disabled. Never run an unreviewed live balance import.

Rollback: revert additive guarded endpoints/worker hooks while no real orders were created. Once orders exist in a later release, preserve ledger and continue reconciliation; do not delete them.
