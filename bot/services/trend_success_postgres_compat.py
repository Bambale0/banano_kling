from __future__ import annotations

import logging

from bot import db as db_backend

logger = logging.getLogger(__name__)
_INSTALLED = False
_HELPERS_EXTENDED = False


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
        global _HELPERS_EXTENDED
        await original_helpers(conn)
        if _HELPERS_EXTENDED:
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
        _HELPERS_EXTENDED = True
        logger.info("Postgres trend success metrics schema is ready")

    postgres_backend._ensure_postgres_helpers = ensure_helpers_with_trend_success
    _INSTALLED = True
