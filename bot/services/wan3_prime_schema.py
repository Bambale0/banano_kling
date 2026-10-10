"""Additive Wan schema execution across the existing SQLite/PostgreSQL adapters."""
from __future__ import annotations

from typing import Any


async def execute_wan_ddl(db: Any, statement: str) -> None:
    """Only trusted feature-owned DDL enters this function, never client input."""
    native = getattr(db, "execute_native_ddl", None)
    if native is None:
        await db.execute(statement)
        return
    # The legacy adapter deliberately skips generic CREATE/ALTER statements.
    # Serialize this feature's idempotent DDL when multiple workers start.
    await native("SELECT pg_advisory_xact_lock(73003001)")
    statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    statement = statement.replace(" REAL ", " DOUBLE PRECISION ")
    await native(statement)
