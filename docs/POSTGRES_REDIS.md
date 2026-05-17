# PostgreSQL And Redis

Redis and PostgreSQL are mandatory infrastructure for the bot.

Redis is used by aiogram FSM. The bot fails startup when `FSM_STORAGE=redis` or
`REDIS_URL` is missing.

PostgreSQL must be reachable through `POSTGRES_DSN` or `DATABASE_URL`. The bot
performs a startup connectivity check and refuses to serve traffic if Postgres is
unavailable. While legacy SQLite helpers still exist during the backend migration,
production must run the Postgres service and keep the migration path validated.

## Environment

```env
REDIS_URL=redis://127.0.0.1:6379/0
FSM_STORAGE=redis
FSM_REDIS_PREFIX=2loop:fsm

POSTGRES_DSN=postgresql://2loop:change-me@127.0.0.1:5432/2loop
DATABASE_URL=postgresql://2loop:change-me@127.0.0.1:5432/2loop
REQUIRE_POSTGRES_REDIS=1
DATABASE_PATH=/root/2loop/bot.db
```

## Local Infra

With Docker:

```bash
docker compose -f docker-compose.infra.yml up -d
```

With system packages:

```bash
apt-get update
apt-get install -y redis-server postgresql
systemctl enable --now redis-server postgresql
```

## Migration

```bash
venv/bin/python scripts/migrate_sqlite_to_postgres.py
```

The script loads `/root/2loop/.env` automatically. Override `DATABASE_PATH` only
when migrating a copy:

```bash
DATABASE_PATH=/root/2loop/bot.db venv/bin/python scripts/migrate_sqlite_to_postgres.py
```

After migration, validate counts in PostgreSQL before switching runtime database
queries from SQLite to PostgreSQL.

## Verification

```bash
redis-cli ping
venv/bin/python - <<'PY'
import asyncio, os
from dotenv import load_dotenv
import asyncpg

load_dotenv('/root/2loop/.env')

async def main():
    conn = await asyncpg.connect(os.environ['POSTGRES_DSN'])
    print(await conn.fetchval('select 1'))
    await conn.close()

asyncio.run(main())
PY
journalctl -u 2loop-bot --since '5 minutes ago' --no-pager | grep 'FSM storage'
```
