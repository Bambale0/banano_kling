# PostgreSQL + Redis migration runbook

This runbook is for moving Banano Kling from SQLite to PostgreSQL and Redis without losing the existing `bot.db`.

## Current state

- Runtime code still uses the SQLite-compatible `bot/database.py` path.
- Redis is already supported for idempotency, locks, and rate counters through `REDIS_URL`.
- PostgreSQL schema and migration tooling are prepared:
  - `migrations/postgres_schema_v2.sql`
  - `scripts/migrate_sqlite_to_postgres.py`
  - `docker-compose.infra.yml`

Do not delete `bot.db`. It remains the rollback source until PostgreSQL runtime is fully verified.

## Safety notes from migration audit

- Use `--truncate` for a clean target database during the final cutover. Without it, the script upserts by primary key only; existing PostgreSQL rows with the same unique business keys (`telegram_id`, `order_id`, `task_id`, promo `code`, etc.) but different IDs can fail the migration.
- The checksum report is a guardrail, not a full row-by-row verifier. It covers critical counts and money/credit sums, but it does not prove every text field, timestamp, conversation row, withdrawal row, or batch job is identical.
- Most migrated runtime tables intentionally do not enforce PostgreSQL foreign keys yet, matching the current SQLite data tolerance. Expect orphan checks to be a pre-cutover validation task, not a database-enforced guarantee.
- PostgreSQL uses `TIMESTAMPTZ`; SQLite stores timestamp text. Run the bot and migration host with an explicit timezone (`TZ=UTC` is preferred) and spot-check recent payment/generation timestamps after migration.
- Docker entrypoint SQL only runs on an empty `postgres_data` volume. For an existing volume, apply `migrations/postgres_schema_v2.sql` manually with `psql` before migration.

## 1. Start PostgreSQL and Redis

Set secrets in `.env`:

```env
POSTGRES_DB=banano_kling
POSTGRES_USER=banano
POSTGRES_PASSWORD=change-me
POSTGRES_PORT=5432
DATABASE_URL=postgresql://banano:change-me@127.0.0.1:5432/banano_kling
REDIS_URL=redis://127.0.0.1:6379/0
```

Start infra:

```bash
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml ps
```

If Docker is not used, create the database manually and apply:

```bash
psql "$DATABASE_URL" -f migrations/postgres_schema_v2.sql
```

## 2. Dry-run migration

Dry-run does not write rows, but it still connects to PostgreSQL and compares the current target checksum:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path bot.db \
  --postgres-url "$DATABASE_URL"
```

Expected:

- each table prints `DRY ... would migrate N rows`;
- checksum report shows source and target values;
- target values may be `0` if PostgreSQL is empty, so an empty-target dry-run can exit with `DIFF`.

Before final apply, check for data that the aggregate checksum cannot prove:

```bash
sqlite3 bot.db "SELECT COUNT(*) FROM generation_history; SELECT COUNT(*) FROM user_settings; SELECT COUNT(*) FROM promo_redemptions; SELECT COUNT(*) FROM partner_withdrawals; SELECT COUNT(*) FROM batch_jobs;"
```

## 3. Apply migration

Use a short maintenance window or stop the bot to freeze writes:

```bash
systemctl stop bot.service
```

Apply with backup:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path bot.db \
  --postgres-url "$DATABASE_URL" \
  --apply \
  --truncate
```

The script:

- creates `backups/sqlite/bot.db.<timestamp>.bak`;
- applies `postgres_schema_v2.sql`;
- transfers rows with preserved IDs;
- resets PostgreSQL sequences;
- compares row counts and important sums for selected high-value tables.

Do not continue if checksum report contains `DIFF`.

After apply, run spot checks before starting runtime:

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM users"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM transactions"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM generation_tasks"
psql "$DATABASE_URL" -c "SELECT MAX(id), COUNT(*) FROM credit_transactions"
```

## 4. Enable Redis reliability

Redis can be enabled independently before PostgreSQL runtime cutover:

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

Restart:

```bash
systemctl restart bot.service
```

Check logs:

```bash
journalctl -u bot.service -n 100 --no-pager
tail -n 100 logs/bot.log
```

## 5. PostgreSQL runtime cutover

The repository still needs the runtime repository layer before production writes should point to PostgreSQL. Use this order:

1. Keep SQLite primary.
2. Run migration into PostgreSQL.
3. Add/verify repository layer for all functions in `bot/database.py`.
4. Run dual-write or shadow-read comparison.
5. Stop bot, run final migration, compare checksums.
6. Switch `DATABASE_URL` to PostgreSQL.
7. Start bot and verify payments/generations/referrals.

## 6. Rollback

If anything is wrong before PostgreSQL runtime cutover, SQLite is still primary. Restore the backup and keep the runtime pointed at the SQLite path used by `bot/database.py`:

```bash
systemctl stop bot.service
cp backups/sqlite/bot.db.<timestamp>.bak bot.db
export DATABASE_PATH=bot.db
systemctl start bot.service
```

If Redis causes issues, clear `REDIS_URL` and restart. The bot falls back to in-memory reliability primitives, but duplicate-update/lock memory is process-local after that.

## 7. Admin feature tables added for the next implementation phase

The PostgreSQL schema already includes tables for requested admin features:

- `payment_packages` — package price, bonus, popularity, visibility, discount.
- `referral_settings` — referrer/friend bonus, trigger, daily limit, anti-fraud rules.
- `push_scenarios` and `push_scenario_events` — automated reminders/offers.
- `partner_payouts` — partner payout records and statuses.
- `antifraud_rules` — configurable anti-fraud checks.

These tables are safe additions and do not affect existing SQLite runtime until handlers/repository code is wired.
