#!/usr/bin/env python3
"""Safely migrate Banano Kling SQLite data to PostgreSQL.

Default mode is dry-run. Use --apply to create schema and write rows.
The script always creates a SQLite backup before --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import asyncpg


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = PROJECT_DIR / "bot.db"
DEFAULT_SCHEMA_PATH = PROJECT_DIR / "migrations" / "postgres_schema_v2.sql"
DEFAULT_BACKUP_DIR = PROJECT_DIR / "backups" / "sqlite"


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    pk: str | None = "id"
    bool_columns: tuple[str, ...] = ()


TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "users",
        (
            "id",
            "telegram_id",
            "credits",
            "created_at",
            "updated_at",
            "referral_code",
            "referred_by",
            "referral_earned",
            "has_paid",
            "partner_agreed_at",
            "partner_total_revenue_rub",
            "partner_balance_rub",
            "partner_withdrawn_rub",
            "partner_tier",
            "is_banned",
            "free_generations",
        ),
        bool_columns=("has_paid", "is_banned"),
    ),
    TableSpec(
        "transactions",
        (
            "id",
            "order_id",
            "user_id",
            "payment_id",
            "credits",
            "amount_rub",
            "status",
            "created_at",
            "provider",
            "original_amount_rub",
            "promo_code",
            "promo_discount_percent",
        ),
    ),
    TableSpec(
        "generation_tasks",
        (
            "id",
            "user_id",
            "task_id",
            "type",
            "preset_id",
            "status",
            "result_url",
            "created_at",
            "completed_at",
            "prompt",
            "cost",
            "model",
            "duration",
            "aspect_ratio",
            "telegram_id",
            "reference_images",
            "is_public_feed",
            "likes_count",
            "shares_count",
            "source_feed_task_id",
            "billing_source",
            "subscription_usage_id",
        ),
        bool_columns=("is_public_feed",),
    ),
    TableSpec("generation_history", ("id", "user_id", "preset_id", "prompt", "cost", "created_at")),
    TableSpec(
        "user_settings",
        (
            "id",
            "user_id",
            "preferred_model",
            "preferred_video_model",
            "preferred_i2v_model",
            "created_at",
            "updated_at",
            "image_service",
        ),
    ),
    TableSpec("gpt55_conversations", ("user_id", "messages_json", "updated_at"), pk="user_id"),
    TableSpec("ai_assistant_conversations", ("user_id", "messages_json", "updated_at"), pk="user_id"),
    TableSpec(
        "promo_codes",
        (
            "id",
            "code",
            "credits",
            "max_uses",
            "used_count",
            "expires_at",
            "is_active",
            "created_by",
            "created_at",
            "discount_percent",
            "promo_type",
            "reward_credits",
        ),
        bool_columns=("is_active",),
    ),
    TableSpec("promo_redemptions", ("id", "promo_id", "user_id", "telegram_id", "order_id", "redeemed_at")),
    TableSpec("bot_settings", ("key", "value", "updated_at"), pk="key"),
    TableSpec("referrals", ("id", "referrer_id", "referred_id", "bonus_credits", "created_at")),
    TableSpec(
        "partner_withdrawals",
        (
            "id",
            "user_id",
            "amount_rub",
            "method",
            "requisites",
            "status",
            "created_at",
            "updated_at",
            "recipient_name",
            "phone",
            "card_mask",
            "external_payment_id",
            "external_contractor_id",
            "external_requisite_id",
            "external_status_id",
            "status_title",
            "error_message",
        ),
    ),
    TableSpec("batch_jobs", ("id", "job_id", "user_id", "mode", "total_cost", "results_count", "duration", "created_at")),
    TableSpec("credit_transactions", ("id", "user_id", "amount", "reason", "external_id", "metadata_json", "created_at")),
)

CHECKSUM_QUERIES = {
    "users_count": "SELECT COUNT(*) FROM users",
    "users_credits_sum": "SELECT COALESCE(SUM(credits), 0) FROM users",
    "transactions_count": "SELECT COUNT(*) FROM transactions",
    "transactions_amount_sum": "SELECT COALESCE(SUM(amount_rub), 0) FROM transactions",
    "generation_tasks_count": "SELECT COUNT(*) FROM generation_tasks",
    "generation_tasks_cost_sum": "SELECT COALESCE(SUM(cost), 0) FROM generation_tasks",
    "credit_transactions_count": "SELECT COUNT(*) FROM credit_transactions",
    "credit_transactions_amount_sum": "SELECT COALESCE(SUM(amount), 0) FROM credit_transactions",
    "referrals_count": "SELECT COUNT(*) FROM referrals",
    "promo_codes_count": "SELECT COUNT(*) FROM promo_codes",
}


def sqlite_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def backup_sqlite(sqlite_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{sqlite_path.name}.{stamp}.bak"
    shutil.copy2(sqlite_path, backup_path)
    return backup_path


def normalize_value(column: str, value: Any, bool_columns: tuple[str, ...]) -> Any:
    if column in bool_columns and value is not None:
        return bool(value)
    if column.endswith("_at") and isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
    return value


def fetch_sqlite_rows(conn: sqlite3.Connection, spec: TableSpec) -> tuple[list[str], list[tuple[Any, ...]]]:
    existing_columns = sqlite_columns(conn, spec.name)
    columns = [column for column in spec.columns if column in existing_columns]
    if not columns:
        return [], []
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM {spec.name} ORDER BY {spec.pk or columns[0]}"
    ).fetchall()
    values = [
        tuple(normalize_value(column, row[column], spec.bool_columns) for column in columns)
        for row in rows
    ]
    return columns, values


def build_upsert_sql(spec: TableSpec, columns: list[str]) -> str:
    placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
    quoted_columns = ", ".join(columns)
    if not spec.pk:
        conflict = "DO NOTHING"
    else:
        update_columns = [column for column in columns if column != spec.pk]
        if update_columns:
            updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
            conflict = f"({spec.pk}) DO UPDATE SET {updates}"
        else:
            conflict = f"({spec.pk}) DO NOTHING"
    return f"INSERT INTO {spec.name} ({quoted_columns}) VALUES ({placeholders}) ON CONFLICT {conflict}"


async def apply_schema(pg: asyncpg.Connection, schema_path: Path) -> None:
    await pg.execute(schema_path.read_text(encoding="utf-8"))


async def migrate_table(pg: asyncpg.Connection, conn: sqlite3.Connection, spec: TableSpec, dry_run: bool) -> int:
    if spec.name not in sqlite_tables(conn):
        print(f"SKIP {spec.name}: source table missing")
        return 0
    columns, rows = fetch_sqlite_rows(conn, spec)
    if not rows:
        print(f"OK {spec.name}: 0 rows")
        return 0
    if dry_run:
        print(f"DRY {spec.name}: would migrate {len(rows)} rows")
        return len(rows)
    sql = build_upsert_sql(spec, columns)
    async with pg.transaction():
        await pg.executemany(sql, rows)
    print(f"OK {spec.name}: migrated {len(rows)} rows")
    return len(rows)


async def reset_sequences(pg: asyncpg.Connection) -> None:
    for spec in TABLES:
        if spec.pk != "id":
            continue
        sequence_name = await pg.fetchval("SELECT pg_get_serial_sequence($1, 'id')", spec.name)
        if not sequence_name:
            continue
        await pg.execute(
            f"SELECT setval($1::regclass, COALESCE((SELECT MAX(id) FROM {spec.name}), 1), true)",
            sequence_name,
        )


def sqlite_checksum(conn: sqlite3.Connection) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, sql in CHECKSUM_QUERIES.items():
        try:
            value = conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            value = 0
        result[key] = str(value or 0)
    return result


async def postgres_checksum(pg: asyncpg.Connection) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, sql in CHECKSUM_QUERIES.items():
        try:
            value = await pg.fetchval(sql)
        except Exception:
            value = 0
        result[key] = str(value or 0)
    return result


def print_checksum_report(source: dict[str, str], target: dict[str, str]) -> bool:
    ok = True
    print("\nChecksum report:")
    for key in sorted(source):
        source_value = source[key]
        target_value = target.get(key, "0")
        same = source_value == target_value
        if not same and key.endswith("_sum"):
            try:
                same = Decimal(source_value) == Decimal(target_value)
            except InvalidOperation:
                same = False
        ok = ok and same
        status = "OK" if same else "DIFF"
        print(f"  {status} {key}: sqlite={source_value} postgres={target_value}")
    return ok


async def run(args: argparse.Namespace) -> int:
    sqlite_path = Path(args.sqlite_path).resolve()
    schema_path = Path(args.schema_path).resolve()
    if not sqlite_path.exists():
        print(f"SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 2
    if not schema_path.exists():
        print(f"Postgres schema not found: {schema_path}", file=sys.stderr)
        return 2
    if not args.postgres_url:
        print("Postgres URL is required: --postgres-url or DATABASE_URL", file=sys.stderr)
        return 2

    dry_run = not args.apply
    sqlite_conn = sqlite_connect(sqlite_path)
    source_checksum = sqlite_checksum(sqlite_conn)

    backup_path = None
    if args.apply:
        backup_path = backup_sqlite(sqlite_path, Path(args.backup_dir).resolve())
        print(f"SQLite backup created: {backup_path}")
    else:
        print("DRY-RUN: no rows will be written. Pass --apply for real migration.")

    pg = await asyncpg.connect(args.postgres_url)
    try:
        if args.apply:
            await apply_schema(pg, schema_path)
            if args.truncate:
                table_names = ", ".join(spec.name for spec in reversed(TABLES))
                await pg.execute(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
                await apply_schema(pg, schema_path)
        for spec in TABLES:
            await migrate_table(pg, sqlite_conn, spec, dry_run=dry_run)
        if args.apply:
            await reset_sequences(pg)
        target_checksum = await postgres_checksum(pg)
    finally:
        await pg.close()
        sqlite_conn.close()

    ok = print_checksum_report(source_checksum, target_checksum)
    if not ok:
        print("\nChecksum mismatch. Do not switch production DATABASE_URL yet.", file=sys.stderr)
        return 1
    if args.apply:
        print("\nMigration completed. Keep the SQLite backup until production is verified.")
        if backup_path:
            print(f"Backup: {backup_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate SQLite bot.db to PostgreSQL safely.")
    parser.add_argument("--sqlite-path", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--postgres-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--schema-path", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--apply", action="store_true", help="Actually write data to PostgreSQL.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Before --apply, truncate migrated PostgreSQL tables. Use only before cutover.",
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
