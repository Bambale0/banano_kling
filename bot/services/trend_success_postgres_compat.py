from __future__ import annotations

import asyncio
import logging

from bot import db as db_backend

logger = logging.getLogger(__name__)
_INSTALLED = False
_HELPERS_EXTENDED_SCHEMAS: set[tuple[str, str]] = set()
_HELPERS_EXTENSION_LOCK: asyncio.Lock | None = None


def install_trend_success_postgres_compat() -> None:
    """Create trend success-metrics schema through the real PostgreSQL cursor.

    The SQLite-compatible PostgreSQL adapter deliberately skips CREATE/ALTER
    statements passed through db.execute(). Trend success metrics originally
    tried to lazily create their table through that path, so production marked
    the schema ready even though PostgreSQL never created the relation.
    """

    global _INSTALLED
    if _INSTALLED or not db_backend.is_postgres():
        return

    from bot import postgres_aiosqlite as postgres_backend

    original_helpers = postgres_backend._ensure_postgres_helpers

    async def ensure_helpers_with_trend_success(conn) -> None:
        global _HELPERS_EXTENSION_LOCK
        await original_helpers(conn)

        # Connections can target independent PostgreSQL schemas. A global
        # boolean skips DDL and breaks all later catalog SELECT queries.
        async with conn.cursor() as cursor:
            await cursor.execute('SELECT current_database(), current_schema()')
            database_name, schema_name = await cursor.fetchone()
        source = (str(database_name), str(schema_name))
        if source in _HELPERS_EXTENDED_SCHEMAS:
            return
        if _HELPERS_EXTENSION_LOCK is None:
            _HELPERS_EXTENSION_LOCK = asyncio.Lock()
        async with _HELPERS_EXTENSION_LOCK:
            if source in _HELPERS_EXTENDED_SCHEMAS:
                return
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trend_generation_runs (
                        task_id TEXT PRIMARY KEY,
                        trend_id BIGINT NOT NULL,
                        user_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_trend_generation_runs_trend
                    ON trend_generation_runs(trend_id, created_at)
                    """
                )
            await conn.commit()
            _HELPERS_EXTENDED_SCHEMAS.add(source)
            logger.info("Postgres trend success metrics schema is ready")

    postgres_backend._ensure_postgres_helpers = ensure_helpers_with_trend_success
    _INSTALLED = True
