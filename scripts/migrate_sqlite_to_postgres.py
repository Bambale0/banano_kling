#!/usr/bin/env python3
"""Migrate the current SQLite bot database into PostgreSQL.

This script is intentionally schema-driven so it can follow the existing
SQLite schema while the application is being moved gradually.

Usage:
  POSTGRES_DSN=postgresql://2loop:password@127.0.0.1:5432/2loop \
  DATABASE_PATH=/root/2loop/bot.db \
  venv/bin/python scripts/migrate_sqlite_to_postgres.py
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    load_dotenv = None

if load_dotenv:
    load_dotenv("/root/2loop/.env")


SQLITE_TO_PG_TYPES = {
    "INTEGER": "BIGINT",
    "TEXT": "TEXT",
    "REAL": "DOUBLE PRECISION",
    "TIMESTAMP": "TIMESTAMPTZ",
    "BOOLEAN": "BOOLEAN",
}


def pg_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def map_type(sqlite_type: str) -> str:
    normalized = (sqlite_type or "TEXT").upper().split()[0]
    return SQLITE_TO_PG_TYPES.get(normalized, "TEXT")


def normalize_default(default: Any, sqlite_type: str) -> str:
    default_sql = str(default)
    normalized_type = (sqlite_type or "").upper()
    normalized_default = default_sql.strip().strip("'\"").upper()

    if "BOOL" in normalized_type:
        if normalized_default in {"0", "FALSE"}:
            return "FALSE"
        if normalized_default in {"1", "TRUE"}:
            return "TRUE"

    if normalized_default == "CURRENT_TIMESTAMP":
        return "CURRENT_TIMESTAMP"
    if normalized_default in {"FALSE", "TRUE"}:
        return normalized_default
    return default_sql


def normalize_value(value: Any, sqlite_type: str) -> Any:
    if value is None:
        return None
    normalized_type = (sqlite_type or "").upper()
    if "BOOL" in normalized_type:
        return bool(value)
    if "TIMESTAMP" in normalized_type or "DATETIME" in normalized_type:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    if isinstance(value, bytes):
        return value
    return value


async def create_table(pg: asyncpg.Connection, sqlite: sqlite3.Connection, table: str):
    columns = sqlite.execute(f"PRAGMA table_info({pg_ident(table)})").fetchall()
    definitions: list[str] = []
    primary_keys: list[str] = []

    for column in columns:
        _, name, col_type, notnull, default, pk = column
        if pk:
            primary_keys.append(name)
            if (col_type or "").upper().startswith("INTEGER"):
                definitions.append(f"{pg_ident(name)} BIGSERIAL")
                continue

        definition = f"{pg_ident(name)} {map_type(col_type)}"
        if notnull:
            definition += " NOT NULL"
        if default is not None:
            definition += f" DEFAULT {normalize_default(default, col_type)}"
        definitions.append(definition)

    if primary_keys:
        pk_cols = ", ".join(pg_ident(col) for col in primary_keys)
        definitions.append(f"PRIMARY KEY ({pk_cols})")

    await pg.execute(f"DROP TABLE IF EXISTS {pg_ident(table)} CASCADE")
    await pg.execute(f"CREATE TABLE {pg_ident(table)} ({', '.join(definitions)})")


async def copy_table(pg: asyncpg.Connection, sqlite: sqlite3.Connection, table: str):
    sqlite.row_factory = sqlite3.Row
    rows = sqlite.execute(f"SELECT * FROM {pg_ident(table)}").fetchall()
    if not rows:
        return 0

    columns = rows[0].keys()
    table_info = sqlite.execute(f"PRAGMA table_info({pg_ident(table)})").fetchall()
    column_types = {row[1]: row[2] for row in table_info}
    col_sql = ", ".join(pg_ident(col) for col in columns)
    placeholders = ", ".join(f"${idx}" for idx in range(1, len(columns) + 1))
    query = f"INSERT INTO {pg_ident(table)} ({col_sql}) VALUES ({placeholders})"
    values = [
        tuple(normalize_value(row[col], column_types.get(col, "")) for col in columns)
        for row in rows
    ]
    await pg.executemany(query, values)
    return len(values)


async def reset_serial_sequences(pg: asyncpg.Connection, sqlite: sqlite3.Connection, table: str):
    columns = sqlite.execute(f"PRAGMA table_info({pg_ident(table)})").fetchall()
    for column in columns:
        _, name, col_type, _, _, pk = column
        if not pk or not (col_type or "").upper().startswith("INTEGER"):
            continue
        sequence = await pg.fetchval(
            "SELECT pg_get_serial_sequence($1, $2)", table, name
        )
        if not sequence:
            continue
        await pg.execute(
            f"SELECT setval($1::regclass, COALESCE((SELECT MAX({pg_ident(name)}) FROM {pg_ident(table)}), 1), true)",
            sequence,
        )


async def create_unique_indexes(pg: asyncpg.Connection, sqlite: sqlite3.Connection, table: str):
    indexes = sqlite.execute(f"PRAGMA index_list({pg_ident(table)})").fetchall()
    for index in indexes:
        _, name, unique, origin, _ = index
        if not unique:
            continue
        if origin == "pk":
            continue
        info = sqlite.execute(f"PRAGMA index_info({pg_ident(name)})").fetchall()
        if not info:
            continue
        cols = ", ".join(pg_ident(row[2]) for row in info)
        await pg.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {pg_ident(name)} "
            f"ON {pg_ident(table)} ({cols})"
        )


async def migrate(sqlite_path: Path, postgres_dsn: str):
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if not postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is required")

    sqlite = sqlite3.connect(sqlite_path)
    pg = await asyncpg.connect(postgres_dsn)
    try:
        tables = [
            row[0]
            for row in sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        for table in tables:
            await create_table(pg, sqlite, table)
        for table in tables:
            count = await copy_table(pg, sqlite, table)
            print(f"{table}: {count} rows")
        for table in tables:
            await reset_serial_sequences(pg, sqlite, table)
        for table in tables:
            await create_unique_indexes(pg, sqlite, table)
    finally:
        await pg.close()
        sqlite.close()


if __name__ == "__main__":
    asyncio.run(
        migrate(
            Path(os.getenv("DATABASE_PATH", "/root/2loop/bot.db")),
            os.getenv("POSTGRES_DSN", ""),
        )
    )
