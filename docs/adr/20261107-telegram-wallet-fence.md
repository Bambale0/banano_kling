# Explicit legacy Telegram credit freeze (Draft preparation)

Baseline: tanyapi@b9834c795707dc3037340ea553f41c1ea50f0f9b. Extends the
opening-readiness ADR and #408/#410/#414. No production installation or freeze.

The owner confirmed a common account and balance after voluntary Telegram/VK
linking. Existing writers update legacy credits directly in payments, specialized
generation, watchdog/recovery and administration. Guarding add/deduct helpers
alone cannot prevent a late legacy write after an opening snapshot.

Explicit internal schema preparation installs a nullable marker on `users` and
an immutable freeze receipt table. It is separate from the freeze transaction:
repeating ALTER TABLE while freezing would wait for an older reader, preventing
the required PostgreSQL stale-snapshot concurrency check. Neither preparation nor
freeze is called by startup, a route, admin UI or CLI. No live opening is enabled.

The internal freeze locks the verified Telegram identity and legacy user, checks
account ownership, saves the raw credits value/storage type/lineage/operation key
and guard digest, and sets the marker in one transaction. The raw value is not
rounded, normalized, credited to another wallet or printed in logs. Identical
requests replay the receipt; conflicting freezes cannot replace it. There is no
thaw command. Fresh connections retain the fence after commit.

Changing the protected users row gives PostgreSQL REPEATABLE READ writers a
serialization failure when they attempt to update an older version. A new row in
a separate fence table alone would not establish that guarantee. Row triggers
reject changes to frozen credits, ID, Telegram identity or marker and deletion.
Nonfinancial profile updates remain possible. PostgreSQL TRUNCATE is denied;
receipt UPDATE/DELETE/TRUNCATE is denied. SQLite also guards replacement through
all current users unique keys (ID, Telegram ID, referral code) on INSERT and
UPDATE, even with recursive triggers and foreign keys disabled. Receipt replacement
is denied. RAISE(ROLLBACK) prevents a caught error from committing earlier changes
in the same transaction. PostgreSQL's adapter already rolls back on SQL errors.

Freeze checks exact expected SQLite trigger definitions or PostgreSQL trigger
scope/enabled state/function bodies/search path. A same-named stale or disabled
guard is a conflict, not a successful freeze. These checks do not defend against
a privileged operator deliberately disabling protection after commit; production
DDL/role access and deployment attestation remain operational requirements.

Acceptance seams: real credit/debit and payment-completion functions, direct SQL,
same-key concurrent freezes, concurrent credit, receipt/identity replacement,
rollback of an interrupted transition, stale guard and native PG old snapshot.
The existing isolated SQLite/PG shared-account workflow runs these tests. No
frontend, provider, Telegram FSM or external messaging change: browser/provider
submission checks do not apply to this unwired internal preparation.

This proves only one legacy Telegram credits row is frozen. It does not prove
provider launches are drained or blocked, partner RUB is migrated, late events are
durably queued, VK writers are fenced, or a shared wallet is authoritative. Pending
payments and refunds fail closed here; a settlement bridge/drain is mandatory
before any live use. Full dual-platform migration/rollout remains held. Do not
freeze real users merely to test this module or promote the sandbox importer.

Rollback before installation is discarding this Draft. Once any real freeze exists,
do not remove markers/guards or resume legacy writers as a UI rollback. A reviewed
authority/compensation/reconciliation protocol is required first.
