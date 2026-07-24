from __future__ import annotations

import asyncio
import logging

from bot import db as db_backend
from bot.services import lava_payment_safety as safety

logger = logging.getLogger(__name__)

_BINDINGS_SCHEMA_LOCK = asyncio.Lock()
_BINDINGS_SCHEMA_READY = False
_INSTALL_MARKER = "_lava_binding_schema_compat_installed"


async def _ensure_bindings_table_postgres_safe() -> None:
    """Create the Lava binding table without rolling back its DDL on index errors.

    The Postgres compatibility adapter rolls back the current transaction whenever
    an SQL statement raises. The previous implementation created the table and its
    optional index in one transaction, caught an index error, and then continued.
    Under concurrent startup/reconcile calls that could roll back the table creation
    itself, so the following SELECT failed with ``relation does not exist``.

    Serialize initialization within the process, commit the table first, and create
    the optional unique index in a separate transaction. An index failure can no
    longer remove the table.
    """

    global _BINDINGS_SCHEMA_READY

    if _BINDINGS_SCHEMA_READY:
        return

    async with _BINDINGS_SCHEMA_LOCK:
        if _BINDINGS_SCHEMA_READY:
            return

        async with db_backend.connect() as db:
            await db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {safety._BINDINGS_TABLE} (
                    contract_id TEXT PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

        try:
            async with db_backend.connect() as db:
                await db.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS "
                    f"idx_{safety._BINDINGS_TABLE}_invoice "
                    f"ON {safety._BINDINGS_TABLE}(invoice_id)"
                )
                await db.commit()
        except db_backend.OperationalError as exc:
            # The mapping table is already committed and usable. A duplicate or
            # concurrently-created optional index must not break checkout.
            logger.warning(
                "Lava binding table is ready but optional invoice index was not created: %s",
                exc,
            )

        _BINDINGS_SCHEMA_READY = True


def install_lava_binding_schema_compat() -> None:
    """Replace the unsafe lazy schema initializer once."""

    if getattr(safety, _INSTALL_MARKER, False):
        return

    safety._ensure_bindings_table = _ensure_bindings_table_postgres_safe
    setattr(safety, _INSTALL_MARKER, True)
    logger.info("Installed Postgres-safe Lava binding schema initializer")
