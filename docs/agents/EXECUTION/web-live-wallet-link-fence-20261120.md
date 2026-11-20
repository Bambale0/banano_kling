# Shared web account identity linking vs independently paid web liabilities

Date: 2026-11-20. Baseline tanyapi dfc650e211c5a515a3676f258e3779abbfd035d7. Scope: auth linking + owner invoice creation, not wallet data migration.

## Critical bug reproduced

When an independent browser owner with a live wallet balance (or a pending web invoice / completed S3 web result) linked an existing Telegram identity, the owner was moved into a linked legacy state. The current UI then rightfully hides the independent live checkout and web history, inadvertently making earlier web funds and media inaccessible.

Both independent balance and pending-invoice cases reproduced RED in synthetic SQLite web-auth integration tests. A third scenario proved that even linking via a different provider (Yandex subject already owned by a Telegram identity) can trigger the same financial authority change.

## Fix and defensive concurrency

- Reject legacy-bound identity linking *before commit*, with a stable "financial-cutover-required" redirect, if either account has available/reserved live wallet value, any web invoice (including creating/pending and retroactive callbacks), or any archived/in-flight web task. No client-supplied account IDs select the ledger.
- Original user identity and its wallet, invoice, S3 history remain unchanged. Linking clean web accounts without live liabilities remains functional.
- PostgreSQL link transaction obtains catalog lock before account-row FOR UPDATE (same lock order as LinkService._merge), preventing merge deadlocks. SQLite transaction remains BEGIN IMMEDIATE. Wallet operations already lock the shared account row.
- New web invoice creation re-verifies the account active status and absence of Telegram/VK identities under the exact same row FOR UPDATE before writing any order. This closes the time-of-check/time-of-use gap if a link completed after the initial HTTP cookie check; never calls provider after a linked-state rejection.
- No new external payment, no live wallet migration and no changes to existing Telegram credits.

## Tests

- TDD RED 2 failures (linked despite prior credit or invoice) then GREEN.
- Added provider-ownership merge variant, clean linking variant and invoice auth TOCTOU test.
- Offline production-image Docker integration run, no real API credentials/network/DB: 66 passed, 18 skipped across web-auth, payment settlement, shared account link and quick link suites.
- Ruff I/F, Python compile and diff checks pass.
- Full GitHub protected CI and exact-SHA production deploy remain release gates.

## Financial cutover restrictions

The guard can be relaxed ONLY after a versioned verified wallet-merger cutover with provider invoice reconciliation, immutable legacy opening claims, live shared wallet writer fence, pending task S3 persistence, and explicit operator approval. Do NOT bypass this safeguard with a feature flag just to enable a new OAuth button. Keep live checkout/global web generation flags off until tests with the real provider in a consenting admin account are proven.

Rollback: revert guarded auth and invoice modifications, retain the live wallet and all invoices. After activation, rollback alone can reintroduce hidden funds; prefer retaining the guard.
