from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

import psycopg

from bot import db as db_backend
from bot.services import lava_payment_safety as safety

logger = logging.getLogger(__name__)

_BINDINGS_SCHEMA_LOCK = asyncio.Lock()
_BINDINGS_SCHEMA_READY = False
_BINDINGS_SCHEMA_READY_FOR: str | None = None
_INSTALL_MARKER = "_lava_binding_schema_compat_installed"


async def _execute_schema_ddl(sql: str) -> None:
    """Execute schema DDL without the SQLite-to-Postgres query filter.

    ``PostgresConnection.execute()`` intentionally skips ``CREATE TABLE``,
    ``CREATE INDEX`` and ``ALTER TABLE`` statements because the legacy database
    bootstrap owns the main schema. This compatibility table is created at
    runtime, so its DDL must use the wrapped psycopg connection directly.
    """

    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute(sql)
            await db.commit()
            return

        raw_conn = getattr(db, "_conn", None)
        if raw_conn is None:
            raise db_backend.OperationalError(
                "Postgres connection does not expose the raw psycopg connection"
            )

        try:
            async with raw_conn.cursor() as cursor:
                await cursor.execute(sql)
            await raw_conn.commit()
        except psycopg.Error as exc:
            await raw_conn.rollback()
            raise db_backend.OperationalError(str(exc)) from exc


async def _verify_bindings_table() -> None:
    async with db_backend.connect() as db:
        await db.execute(f"SELECT COUNT(*) FROM {safety._BINDINGS_TABLE}")


def _binding_database_key() -> str:
    """Cache schema readiness for this database, not for the whole process.

    SQLite test/recovery databases change at runtime. Hash the PostgreSQL DSN
    rather than retaining or logging any credential-bearing connection string.
    """
    if db_backend.is_postgres():
        dsn = os.getenv("DATABASE_URL", db_backend.DATABASE_URL)
        return "postgres:" + hashlib.sha256(dsn.encode()).hexdigest()
    current = sys.modules.get("bot.database")
    filename = (
        getattr(current, "DATABASE_PATH", None)
        or os.getenv("DATABASE_PATH", db_backend.DATABASE_PATH)
    )
    return "sqlite:" + str(Path(str(filename)).resolve())


async def _ensure_bindings_table_postgres_safe() -> None:
    """Create and verify the Lava contract-to-invoice mapping table once."""

    global _BINDINGS_SCHEMA_READY, _BINDINGS_SCHEMA_READY_FOR

    database_key = _binding_database_key()
    if _BINDINGS_SCHEMA_READY and _BINDINGS_SCHEMA_READY_FOR == database_key:
        return

    async with _BINDINGS_SCHEMA_LOCK:
        database_key = _binding_database_key()
        if _BINDINGS_SCHEMA_READY and _BINDINGS_SCHEMA_READY_FOR == database_key:
            return

        await _execute_schema_ddl(
            f"""
            CREATE TABLE IF NOT EXISTS {safety._BINDINGS_TABLE} (
                contract_id TEXT PRIMARY KEY,
                invoice_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        try:
            await _execute_schema_ddl(
                f"CREATE UNIQUE INDEX IF NOT EXISTS "
                f"idx_{safety._BINDINGS_TABLE}_invoice "
                f"ON {safety._BINDINGS_TABLE}(invoice_id)"
            )
        except db_backend.OperationalError as exc:
            # The required table is already committed. The optional unique index
            # must not make checkout unavailable.
            logger.warning(
                "Lava binding table is ready but optional invoice index was not created: %s",
                exc,
            )

        # Do not cache a false-positive initialization. This catches adapter or
        # search-path regressions before checkout tries to query the table.
        await _verify_bindings_table()
        _BINDINGS_SCHEMA_READY_FOR = database_key
        _BINDINGS_SCHEMA_READY = True


def install_lava_binding_schema_compat() -> None:
    """Replace the unsafe lazy schema initializer once."""

    if getattr(safety, _INSTALL_MARKER, False):
        return

    safety._ensure_bindings_table = _ensure_bindings_table_postgres_safe
    setattr(safety, _INSTALL_MARKER, True)
    logger.info("Installed direct-DDL Lava binding schema initializer")
