from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

import aiosqlite
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from bot import postgres_aiosqlite as legacy

logger = logging.getLogger(__name__)

_POOL: AsyncConnectionPool | None = None
_POOL_DSN: str | None = None
_POOL_LOCK: asyncio.Lock | None = None
_PERFORMANCE_INDEXES_READY = False
_PERFORMANCE_INDEXES_LOCK: asyncio.Lock | None = None

_PERFORMANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_generation_history_user_id ON generation_history(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_user_status_created ON transactions(user_id, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)",
    "CREATE INDEX IF NOT EXISTS idx_partner_withdrawals_user_created ON partner_withdrawals(user_id, created_at DESC)",
)


def _positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(0.1, value)


def _pool_min_size() -> int:
    return _positive_int("PG_POOL_MIN_SIZE", 2)


def _pool_max_size() -> int:
    return max(_pool_min_size(), _positive_int("PG_POOL_MAX_SIZE", 12))


def _pool_timeout() -> float:
    return _positive_float("PG_POOL_TIMEOUT_SECONDS", 5.0)


def _connect_timeout() -> int:
    return _positive_int("PG_CONNECT_TIMEOUT_SECONDS", 5)


def _get_pool_lock() -> asyncio.Lock:
    global _POOL_LOCK
    if _POOL_LOCK is None:
        _POOL_LOCK = asyncio.Lock()
    return _POOL_LOCK


def _get_performance_indexes_lock() -> asyncio.Lock:
    global _PERFORMANCE_INDEXES_LOCK
    if _PERFORMANCE_INDEXES_LOCK is None:
        _PERFORMANCE_INDEXES_LOCK = asyncio.Lock()
    return _PERFORMANCE_INDEXES_LOCK


async def _ensure_performance_indexes(conn) -> None:
    """Install indexes used by admin user/partner lookups once per process."""
    global _PERFORMANCE_INDEXES_READY
    if _PERFORMANCE_INDEXES_READY:
        return

    async with _get_performance_indexes_lock():
        if _PERFORMANCE_INDEXES_READY:
            return
        async with conn.cursor() as cursor:
            for statement in _PERFORMANCE_INDEXES:
                await cursor.execute(statement)
        await conn.commit()
        _PERFORMANCE_INDEXES_READY = True


async def _prepare_pool(pool: AsyncConnectionPool) -> None:
    """Prepare schema/indexes before concurrent application traffic can use the pool."""
    raw_conn = await pool.getconn(timeout=_pool_timeout())
    try:
        await legacy._ensure_postgres_helpers(raw_conn)
        await _ensure_performance_indexes(raw_conn)
    finally:
        with suppress(legacy.psycopg.Error):
            await raw_conn.rollback()
        await pool.putconn(raw_conn)


async def _get_postgres_pool() -> AsyncConnectionPool:
    """Return one bounded pool per process instead of opening a socket per query."""
    global _POOL
    global _POOL_DSN

    dsn = legacy._normalize_postgres_dsn()
    if not legacy._is_postgres_url(dsn):
        raise aiosqlite.OperationalError("DATABASE_URL is not a PostgreSQL URL")

    if _POOL is not None and _POOL_DSN == dsn:
        return _POOL

    async with _get_pool_lock():
        if _POOL is not None and _POOL_DSN == dsn:
            return _POOL

        if _POOL is not None:
            await _POOL.close(timeout=_pool_timeout())

        pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=_pool_min_size(),
            max_size=_pool_max_size(),
            timeout=_pool_timeout(),
            max_idle=300.0,
            max_lifetime=1800.0,
            kwargs={"connect_timeout": _connect_timeout()},
            open=False,
            name="banano-kling-postgres",
        )
        ready = False
        try:
            await pool.open()
            await _prepare_pool(pool)
            ready = True
        finally:
            if not ready:
                await pool.close(timeout=_pool_timeout())

        _POOL = pool
        _POOL_DSN = dsn
        logger.info(
            "PostgreSQL pool opened: min=%s max=%s acquire_timeout=%.1fs",
            _pool_min_size(),
            _pool_max_size(),
            _pool_timeout(),
        )
        return pool


class PooledPostgresConnection(legacy.PostgresConnection):
    """aiosqlite-compatible wrapper returning the physical connection to the pool."""

    def __init__(self, conn, pool: AsyncConnectionPool):
        super().__init__(conn)
        self._pool = pool

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Legacy behaviour discarded uncommitted work by physically closing the
        # connection. A pooled connection must explicitly rollback before reuse.
        with suppress(legacy.psycopg.Error):
            await self._conn.rollback()
        await self._pool.putconn(self._conn)


class PostgresPoolConnect:
    def __init__(self, *args, **kwargs):
        self._conn: PooledPostgresConnection | None = None

    async def _ensure(self) -> PooledPostgresConnection:
        if self._conn is not None:
            return self._conn

        pool = await _get_postgres_pool()
        try:
            raw_conn = await pool.getconn(timeout=_pool_timeout())
        except PoolTimeout as exc:
            logger.warning("PostgreSQL pool exhausted for %.1fs", _pool_timeout())
            raise aiosqlite.OperationalError(
                "PostgreSQL connection pool is temporarily busy"
            ) from exc

        prepared = False
        try:
            # These are no-ops after pool startup, but keep the adapter safe if a
            # future test or alternate bootstrap path injects an already-open pool.
            await legacy._ensure_postgres_helpers(raw_conn)
            await _ensure_performance_indexes(raw_conn)
            prepared = True
            self._conn = PooledPostgresConnection(raw_conn, pool)
            return self._conn
        finally:
            if not prepared:
                with suppress(legacy.psycopg.Error):
                    await raw_conn.rollback()
                await pool.putconn(raw_conn)

    def __await__(self):
        return self._ensure().__await__()

    async def __aenter__(self):
        return await self._ensure()

    async def __aexit__(self, exc_type, exc, tb):
        conn = await self._ensure()
        return await conn.__aexit__(exc_type, exc, tb)


def connect(*args, **kwargs) -> PostgresPoolConnect:
    return PostgresPoolConnect(*args, **kwargs)


async def close_postgres_pool() -> None:
    """Close the shared pool during an explicit application shutdown/test teardown."""
    global _POOL
    global _POOL_DSN

    pool = _POOL
    _POOL = None
    _POOL_DSN = None
    if pool is not None:
        await pool.close(timeout=_pool_timeout())
