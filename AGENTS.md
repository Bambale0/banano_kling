# AGENTS.md

## Project shape

- This repo is a Python Telegram bot using aiogram, aiohttp webhooks, Redis for FSM/cache, and SQLite as the production business database.
- The production DB is `bot.db` unless `.env` overrides `DATABASE_PATH`. The app is still coupled to `aiosqlite`; do not switch runtime to Postgres until the DB layer is refactored.
- Public user files live under `static/uploads/` and are required for provider callbacks, Telegram downloads, and miniapp flows.
- Secrets live in `.env`, `.env.postgres`, and `~/.codex/auth.json` on hosts. Never print secret values in logs, comments, final answers, or docs.

## Runtime safety

- Do not run two production instances against the same Telegram token and mutable DB during migration. Prepare dependencies, nginx, Redis, systemd, and Codex first; start the new bot only during cutover.
- Before DB-moving work, create a SQLite backup with `SEND_BACKUP_TO_ADMINS=0 ./scripts/backup_db.sh` or stop the bot and copy `bot.db` plus any `bot.db-wal`/`bot.db-shm` files.
- Do not delete `static/uploads/`, `backups/`, `.env*`, or `bot.db*` unless the user explicitly asks for cleanup and a fresh backup exists.
- Treat `bot.pid` as host-local state. It should not be trusted after a copy to another server.

## Common commands

- Install runtime dependencies:
  `python3 -m venv venv && source venv/bin/activate && pip install -U pip setuptools wheel && pip install -r requirements.txt`
- Run focused tests:
  `source venv/bin/activate && python -m pytest tests/<file>.py`
- Run full tests when risk justifies it:
  `source venv/bin/activate && python -m pytest`
- Restart on an active production host:
  `./restart.sh`
- Check service logs on systemd hosts:
  `journalctl -u banano-kling.service -n 200 --no-pager`

## Deployment notes

- Target migration path is `/root/tanya/banano_kling` unless the user says otherwise.
- `bot.service` in the repo contains an old hard-coded path. On new servers prefer the generated `/etc/systemd/system/banano-kling.service` from `scripts/bootstrap_new_server.sh`.
- Nginx should proxy HTTP to `127.0.0.1:${WEBHOOK_PORT:-8443}`. Do not force HTTPS before the domain and certificate have been moved.
- For a near-zero-downtime move: initial `rsync` while old prod runs, provision the new host, final short stop/final sync, then start the new service and switch DNS/webhook/cert.

## Codex and MCP

- Codex should load this file before work. Keep long-lived project rules here rather than in one-off prompts.
- Use MCP documentation servers for changing library/framework/API usage. `context7` is useful for current library docs; OpenAI/Codex facts should come from official Codex/OpenAI docs.
- Custom project agents live in `.codex/agents/`. Use them for read-heavy parallel checks: deployment safety, DB migration risk, and runtime debugging.
