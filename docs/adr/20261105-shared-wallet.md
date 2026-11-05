# Shared wallet foundation

Status: E2 implementation, no production release. Parent #408, E2 #410.

The wallet uses integer units (10,000 units per banana), never binary floating
point. The four-place precision follows the intended existing schema, not a
price or conversion rate. Exact input strings/integers/Decimal are accepted;
floats, non-finite numbers, negative/zero values, excessive precision and overflow
are rejected. Long fractional coefficients cannot be silently rounded by the
ambient Decimal context. Migration of legacy floats requires separate explicit
normalization evidence, not automatic import through this endpoint.

## Operations

| Operation | Available | Reserved | Preconditions |
|---|---|---|---|
| credit | +amount | unchanged | Unique source operation |
| reserve | -amount | +amount | Sufficient available funds |
| capture | unchanged | -amount | Remaining owned reservation |
| release | +amount | -amount | Remaining owned reservation |
| refund | +amount | unchanged | Owned capture, cumulative refund <= capture |

Partial capture/release is supported. Reservations never automatically expire
into a refund: uncertain provider acceptance must be reconciled before release.
All changes and the append-only journal entry commit together. Ledger INSERT
failure rolls back the wallet and reservation. PostgreSQL and SQLite triggers
reject journal UPDATE/DELETE; PostgreSQL also rejects TRUNCATE.

Each request has a global key within its scope, bound to account, operation,
canonical exact units and reference. Same key/same request returns its receipt;
different request or owner is a conflict. PostgreSQL advisory locks serialize
key claims, account row locks serialize balance changes; SQLite uses an immediate
transaction. Reserved amounts cannot be captured/released twice; changing the
refund key cannot exceed the original captured amount.

## Administrator test surface

GET/POST `/api/account-preview/wallet` uses the existing current administrator
session and hard-codes the **sandbox namespace** as an immutable security
boundary. Client scope/account fields cannot select real money or another owner.
The internal service also defines a separate live namespace for later adapters;
no production opening balances or legacy writers are switched in this slice.

The admin UI shows exact strings, an operation form and recent journal entries.
It retains the operation key after an uncertain response so retry cannot mint or
spend twice. Session credentials stay in operation-local memory and are revoked
after the request. A successful operation with failed delivery can be retried
using the same key and returns the existing receipt.

## Verified behavior

HTTP/domain tests run on SQLite and an isolated PostgreSQL schema: exact credit,
idempotency conflict/replay, parallel credits/reservations, capture/release races,
bounded refunds, invalid precision/exponents, append-only journal, rollback after
journal failure and admin-only/sandbox isolation. Browser fixtures are synthetic
and do not call payment or generation providers.

Remaining integration: explicit opening snapshots/authority barriers, all legacy
payment/credit/debit/refund writers, both bot adapters, account merge transfers
and provider acceptance/outbox/reconciliation. These are release blockers for
the complete product. Sandbox balances must never be imported into live scope.
