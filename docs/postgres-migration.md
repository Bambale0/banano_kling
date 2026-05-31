# PostgreSQL migration notes for banano_kling

## Current state

- Production runtime still uses SQLite (`bot.db`).
- Redis is only used for FSM/cache, not as the primary business database.
- PostgreSQL migration is prepared in a safe staged mode to avoid breaking the watchdog-managed service.

## Prepared assets

- `.env.postgres` — local Postgres connection settings (root-only, not committed)
- `scripts/migrate_sqlite_to_postgres.py` — schema + data migration from SQLite to Postgres
- `scripts/verify_postgres_migration.py` — row-count verification

## Recommended cutover path

1. Stop writes briefly or enable maintenance window.
2. Run final SQLite backup.
3. Run `scripts/migrate_sqlite_to_postgres.py --drop-existing`.
4. Verify counts with `scripts/verify_postgres_migration.py`.
5. Refactor runtime DB layer away from direct `aiosqlite` usage before switching `DATABASE_URL`.
6. Restart `banano-kling.service` and confirm watchdog stays healthy.

## Important blocker

The app is still strongly coupled to `aiosqlite` and SQLite SQL syntax. Do **not** switch production `DATABASE_URL` to Postgres yet until runtime DB compatibility is implemented.
