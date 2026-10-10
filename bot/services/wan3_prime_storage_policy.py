"""Atomic cumulative byte quotas shared by every Wan upload/import surface."""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from bot import db as db_backend
from bot.services.wan3_prime_media import Wan3PrimeValidationError


ACTIVE_UPLOAD_STATES = "('open', 'assembling', 'importing')"


def positive_setting(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise Wan3PrimeValidationError(f"Invalid storage configuration: {name}", status=503) from exc
    if value <= 0:
        raise Wan3PrimeValidationError(f"Invalid storage configuration: {name}", status=503)
    return value


async def lock_storage(db) -> None:
    """Caller commits/rolls back; all quota writers serialize on the same row."""
    await db.execute("BEGIN" if db_backend.is_postgres() else "BEGIN IMMEDIATE")
    if db_backend.is_postgres():
        await db.execute("SELECT id FROM wan3_prime_storage_lock WHERE id = 1 FOR UPDATE")


async def assert_capacity(db, user_id: int, incoming_bytes: int, *, exclude_upload_id: str = "") -> None:
    if incoming_bytes < 0:
        raise Wan3PrimeValidationError("Invalid incoming size")
    # Completed files remain counted. Expired sessions are counted until cleanup
    # actually removes their files; time passing never grants free disk capacity.
    user_media = await (await db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM wan3_prime_media WHERE user_id = ?", (user_id,))).fetchone()
    all_media = await (await db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM wan3_prime_media")).fetchone()
    user_pending = await (await db.execute(
        "SELECT COALESCE(SUM(declared_size), 0) FROM wan3_prime_upload_sessions "
        f"WHERE user_id = ? AND status IN {ACTIVE_UPLOAD_STATES} AND upload_id <> ?", (user_id, exclude_upload_id),
    )).fetchone()
    all_pending = await (await db.execute(
        "SELECT COALESCE(SUM(declared_size), 0) FROM wan3_prime_upload_sessions "
        f"WHERE status IN {ACTIVE_UPLOAD_STATES} AND upload_id <> ?", (exclude_upload_id,),
    )).fetchone()
    if int(user_media[0]) + int(user_pending[0]) + incoming_bytes > positive_setting("WAN3_UPLOAD_USER_QUOTA_BYTES", 2 * 1024**3):
        raise Wan3PrimeValidationError("Wan storage quota exceeded for this user", status=429)
    if int(all_media[0]) + int(all_pending[0]) + incoming_bytes > positive_setting("WAN3_UPLOAD_GLOBAL_QUOTA_BYTES", 20 * 1024**3):
        raise Wan3PrimeValidationError("Wan global storage quota is full; try again later", status=429)
    disk = await asyncio.to_thread(shutil.disk_usage, Path.cwd())
    # Chunks, assembly and final atomic persistence can briefly coexist.
    required = (int(all_pending[0]) + incoming_bytes) * 3
    if disk.free - required < positive_setting("WAN3_UPLOAD_MIN_FREE_BYTES", 1024**3):
        raise Wan3PrimeValidationError("Wan storage reserve is temporarily unavailable", status=503)
