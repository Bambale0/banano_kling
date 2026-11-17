# Astro GPT-6 reports: PostgreSQL schema and all-seven real-facts acceptance

## Proven production-specific fault

Existing `bot.postgres_aiosqlite.translate_sql()` deliberately returns `None`
for generic SQLite `CREATE TABLE`/`CREATE INDEX`. After #587 merged, both
`AstroReportJobs.initialize()` and `AstroReportSqlStore.initialize()` used
that generic execute path. Consequently the new Astro schema does not exist
in production PostgreSQL when `ASTRO_REPORTS_ENABLED=1`. Production rollout
remains disabled until this is repaired and validated.

Fix: `execute_native_ddl()` only for these **constant, application-owned**
PostgreSQL `CREATE` statements; continue using the normal `db.connect()` SQL
adapter for parameterized inserts, updates, reads and fencing. For SQLite,
retain `conn.execute()` unchanged. No destructive migrations or DB changes
in the running production database.

## Evidence (2026-11-17)

- TDD RED on a disposable PostgreSQL 16 container: the unmodified #587 code
  failed with `relation "astro_report_circuit" does not exist` after the
  interpreter silently skipped all CREATE statements.
- GREEN on the same isolated PostgreSQL 16: job/circuit/checkpoint tables and
  indexes created; all 8 concurrent worker claims returned **exactly one**
  winner; correct owner filtering, checkpoint persistence and terminal status.
  Smoke script: `scripts/astro_postgres_queue_smoke.py`. The script connects
  using the project's **real PostgresConnection/SQL translator**, with an
  isolated direct connection to bypass unrelated legacy database bootstrap.
  PostgreSQL was disposed after the test. Synthetic database credentials only.
- `tests/test_astro_postgres_native_schema.py`: forces Postgres mode and
  rejects any generic CREATE, verifying native PG DDL for all Astro tables.
- `pytest tests/test_astro*.py` in a read-only network-isolated bot container:
  **250 passed**, one unrelated unknown pytest-config-option warning.
- `scripts/astro_seven_real_facts_reports_smoke.py`, network-isolated with
  GeoNames and real JPL DE440 assets: all seven real astronomical fact sets
  completed their **entire** original versioned reports with every section;
  re-running did not invoke the provider again. Sections/word counts:

  natal 18/20,072; compatibility 25/20,100; karma 27/16,116;
  year 41/27,816; month 52/13,144; solar 33/27,732;
  lunar 43/13,080.

  These word counts come from a **deterministic synthetic text generator**.
  This verifies full plan coverage, calendars, checkpoint replay, factual
  calculation boundaries and no network dependence. It does NOT demonstrate
  seven paid GPT-6 reports, their linguistic quality, or model fact fidelity.
- Separately #587 verified a **single low-cost real KIE GPT-6 Astra request**
  with structured Responses HTTP 200 and usage; no real birth data used.

## Release and remaining gates

Protected `tanyapi` CI → squash merge → exact-SHA Docker deployment. Verify
PostgreSQL schema bootstrap in a disposable environment before enabling paid
report jobs. Production `ASTRO_REPORTS_ENABLED=0` stays unchanged; never
invent/rotate Fernet keys, enable public access, or charge users implicitly.
Before live activation: operator-managed stable Fernet/HMAC secrets, KIE
model configuration, admin/anon auth smoke, cost limits and real signed
Telegram UI end-to-end. The frontend PR #583 remains separately staged.

Skills: project `AGENTS.md`, `.agents` TDD and verification instructions.
