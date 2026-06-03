import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.migrate_sqlite_to_postgres import (
    TABLES,
    TableSpec,
    build_upsert_sql,
    fetch_sqlite_rows,
    normalize_value,
)


def _postgres_table_columns(schema: str, table_name: str) -> set[str]:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table_name)} \((.*?)\n\);",
        schema,
        flags=re.DOTALL,
    )
    assert match, f"{table_name} table is missing from postgres schema"

    columns = set()
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        first_token = line.split()[0]
        if first_token.upper() in {"CONSTRAINT", "FOREIGN", "PRIMARY", "UNIQUE"}:
            continue
        columns.add(first_token)
    return columns


def test_postgres_schema_contains_admin_feature_tables():
    schema = Path("migrations/postgres_schema_v2.sql").read_text(encoding="utf-8")
    for table in (
        "payment_packages",
        "referral_settings",
        "push_scenarios",
        "partner_payouts",
        "antifraud_rules",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_migration_table_order_starts_with_users():
    assert TABLES[0].name == "users"
    assert "transactions" in [spec.name for spec in TABLES]
    assert "credit_transactions" in [spec.name for spec in TABLES]


def test_migration_specs_match_postgres_schema_columns():
    schema = Path("migrations/postgres_schema_v2.sql").read_text(encoding="utf-8")
    for spec in TABLES:
        postgres_columns = _postgres_table_columns(schema, spec.name)
        missing = set(spec.columns) - postgres_columns
        assert not missing, (
            f"{spec.name} columns missing from PostgreSQL schema: {sorted(missing)}"
        )


def test_build_upsert_sql_uses_primary_key_conflict():
    sql = build_upsert_sql(
        TableSpec("users", ("id", "telegram_id")), ["id", "telegram_id"]
    )
    assert "ON CONFLICT (id) DO UPDATE" in sql
    assert "telegram_id = EXCLUDED.telegram_id" in sql


def test_fetch_sqlite_rows_converts_boolean_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER, has_paid INTEGER)"
    )
    conn.execute("INSERT INTO users (id, telegram_id, has_paid) VALUES (1, 123, 1)")
    columns, rows = fetch_sqlite_rows(
        conn,
        TableSpec("users", ("id", "telegram_id", "has_paid"), bool_columns=("has_paid",)),
    )
    assert columns == ["id", "telegram_id", "has_paid"]
    assert rows == [(1, 123, True)]


def test_normalize_value_converts_common_sqlite_timestamps():
    assert normalize_value("created_at", "2026-05-31 12:34:56", ()) == datetime(
        2026, 5, 31, 12, 34, 56
    )
    assert normalize_value("updated_at", "2026-05-31T12:34:56Z", ()) == datetime(
        2026, 5, 31, 12, 34, 56, tzinfo=timezone.utc
    )
