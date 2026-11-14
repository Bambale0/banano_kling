"""Serialize SQLite initialization for native VK public interactions.

The shared SQLite adapter reissues PRAGMA journal_mode=WAL on each new
connection before busy_timeout. Multiple concurrent opens can hit SQLITE_BUSY
even when the subsequent mutations are unique/idempotent. One event-loop
lock covers the VK feed likes and comments, while PostgreSQL remains
fully concurrent and protected by its actual DB uniqueness constraints.
"""
from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

_SQLITE_WRITER_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Lock
] = WeakKeyDictionary()


def sqlite_vk_writer_lock() -> asyncio.Lock:
    """Return a lock tied to this event loop, never a reused global loop."""
    loop = asyncio.get_running_loop()
    lock = _SQLITE_WRITER_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _SQLITE_WRITER_LOCKS[loop] = lock
    return lock
