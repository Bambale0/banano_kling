# Reference-loss verification and adapter regression - 2026-10-19

## Scope and baseline

Only NEUROMIX/Tanya, branch `tanyapi`, worktree `/root/tanya/banano_kling`, container `banano-kling-bot`. The running image revision and critical source hashes matched `63d6e8b2164de223f80ca950460c697e123237c1`. KSU is a separate application and is not part of this incident.

## Why previously available references disappeared

See [the October 18 incident](2026-10-18-reference-recovery.md). Before `6ce4197`, generic 24-hour upload expiry also traversed durable `trend-assets`. Before #326, removing/pruning a recent-upload shortcut physically removed its file without checking historical generation ownership. Those are distinct deletion paths. Missing bytes did not remove template rows, so an apparently intact trend could retain dead references.

October 11 deletion evidence is preserved in the earlier incident record; the current rolling application log set no longer contains that date. Do not present today's inspection as a fresh read of that old log.

## Fresh recovery results

- All twelve previously recovered asset rows still resolve to eleven originals with exact SHA-256 and byte size. All eleven public media HEAD checks returned 200; all six affected template payload preflights passed without starting a paid generation.
- Five asset rows still lack four originals (one shared video and three images). The set is unchanged from the October 18 recovery. This does not prove that every historical user reference is healthy, but it is not a new loss of the restored template files.
- Two ordinary-file scans covered 510,298 files; none had a target byte size, so no exact-byte candidate proceeded to hashing. Thirteen additional source/release archives contained 3,076 members, also without a target-size candidate. Database-only deployment backups cannot recreate absent media bytes.
- The uploader's 139 retained non-PNG image originals were normalized in memory by the current image conversion algorithm; none reproduced the missing image hashes. No approximate replacement was published.
- A private, independently verified same-host rescue tar of all eleven surviving originals plus manifest was created outside uploads, under `backups/reference-rescue-20261019`. It protects against another upload cleanup, not loss of the server. Receipts stay in ignored `data/diagnostics/reference-recovery-20261019`; do not commit originals, credentials or customer snapshots.

## Newly reproduced PostgreSQL adapter defect

The ownership query introduced in #326 used a JSONPath filter containing a question mark. The application's SQLite-to-PostgreSQL adapter unconditionally translates question marks to bind placeholders, including inside quoted JSONPath. Through the real `PostgresConnection.execute` this raises a JSONPath `OperationalError`. Running the original query directly with raw psycopg misses the defect.

The cleanup is fail-closed on this error: it aborts before deletion. Therefore this defect must not be misreported as the cause of a new deletion. It does prevent the intended ownership-aware maintenance from completing.

### Narrow fix

Keep `strict $.**` recursive traversal and move the string-type predicate to `WHERE jsonb_typeof(ref.value) = 'string'`. Do not alter the global SQL translator, ownership policy, retention durations, billing, permissions or model routing. Malformed owner JSON still raises before deletion.

### Verification

- No-bind query regression: both variants failed before the fix, then passed.
- 37 focused safe tests passed, covering typed inputs, all task statuses, template ownership, restoration, missing-reference preflight and malformed-document fail-closed behavior.
- Nine focused tests passed against a new disposable PostgreSQL 17 instance. New tests execute through the runtime adapter, not raw SQL. An unrelated baseline migration test was reproduced failing because its nonempty video grant fixture lacked the existing version-1 contract; only that fixture was corrected, with all persistence/no-backfill assertions retained.
- Real-data candidate dry-run used the real PostgreSQL adapter over a server-enforced read-only connection and intercepted every remove/unlink/rmdir call. It protected 72,503 owned upload paths and 54,869 generation-reference paths; none of the restored asset paths were deletion candidates. All twelve restored rows remained hash-valid; zero physical deletions.
- Three isolated real-runtime generic-cleanup tests passed using synthetic temporary files. The first naturally scheduled cleanup after the October 18 deployment was not observed at the time of this audit; the candidate dry-run is not a claim that that scheduled iteration already ran.

## Release and remaining work

Release only through a protected PR to `tanyapi`, all required checks, exact-SHA deployment and post-deploy read-only verification. Full safe suite and CI results are recorded in the PR and private execution receipts. Do not describe missing originals as restored: recovery still requires a retained exact source or an explicit author-supplied replacement. A same-host rescue archive is not an off-host backup; add verified media backup coverage before treating disaster recovery as complete.
