"""
Telegram Bot for AI Image/Video Generation
Using aiogram 3.x, Kie/Kling APIs, CryptoBot payments
"""

from __future__ import annotations

import os

import aiosqlite

__version__ = "1.0.0"

_ORIGINAL_AIOSQLITE_CONNECT = aiosqlite.connect
_SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000"))


class _ConfiguredAioSqliteConnection:
    def __init__(self, connector):
        self._connector = connector
        self._conn = None
        self._configured = False

    async def _ensure(self):
        if self._conn is None:
            self._conn = await self._connector
        if not self._configured:
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.execute("PRAGMA temp_store=MEMORY")
            self._configured = True
        return self._conn

    def __await__(self):
        return self._ensure().__await__()

    async def __aenter__(self):
        return await self._ensure()

    async def __aexit__(self, exc_type, exc, tb):
        conn = await self._ensure()
        return await conn.__aexit__(exc_type, exc, tb)


def _patched_aiosqlite_connect(*args, **kwargs):
    kwargs.setdefault("timeout", max(_SQLITE_BUSY_TIMEOUT_MS / 1000, 5))
    return _ConfiguredAioSqliteConnection(_ORIGINAL_AIOSQLITE_CONNECT(*args, **kwargs))


if getattr(aiosqlite.connect, "__name__", "") != "_patched_aiosqlite_connect":
    aiosqlite.connect = _patched_aiosqlite_connect
