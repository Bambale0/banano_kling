# Publication schema DDL lock convoy — 2026-11-13

## Production evidence

Following the PR #488 backend restart, PostgreSQL had 23 sessions waiting
on a relation lock of `generation_tasks`; SELECTs and task history were
blocked behind `DO $$ BEGIN ALTER TABLE generation_tasks ADD COLUMN ...`.
The first DDL was itself blocked by a long running query. Several concurrent
requests had entered `bot.handlers.publication_scope_compat._ensure_publication_scope_schema`
before its process-local readiness flag was set.

The four required columns were confirmed to exist in production:
`is_profile_visible`, `profile_published_at`,
`feed_reference_selection`, `feed_repeat_reference_selection`.

## Fix

Protect lazy schema initialization with a per-event-loop lock and a second
readiness check. On PostgreSQL, inspect `information_schema.columns` first:
if all four columns exist, mark initialized and return without DDL, data
backfill or index creation. Only run the migration for missing columns;
SQLite legacy behavior is unchanged.

This removes unnecessary exclusive relation locks and full-table backfills
from concurrent authenticated requests while preserving fresh PostgreSQL
schema initialization. The database remains the source of truth; no
production data or schema was edited manually.

## Regression / release

The new tests first failed against the previous implementation, then both
passed after the fix. They prove that concurrent existing-schema requests
perform one read-only check and that a missing column still migrates.
Use strict CI, exact-SHA auto-deploy and production verification. During
post-deploy smoke, inspect pg_stat_activity relation waits, bootstrap and
Telegram handler p50/p95, and the revision of both TG/VK Mini Apps.
