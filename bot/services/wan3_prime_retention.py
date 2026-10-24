"""Bounded expiry for unused Wan inputs, preserving every task-owned recipe."""
from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot import database
from bot import db as db_backend
from bot.services.wan3_prime_media import canonical_child_path
from bot.services.wan3_prime_storage_policy import lock_storage, positive_setting

logger = logging.getLogger(__name__)


async def _table_exists(db, name: str) -> bool:
    if db_backend.is_postgres():
        row = await (await db.execute('SELECT to_regclass(?)', (name,))).fetchone()
        return bool(row and row[0])
    return bool(await (await db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))).fetchone())


async def _ownership_tables(db) -> list[tuple[str, str]]:
    # Original recipes and derived provider snapshots both own their inputs.
    # Only an absent optional table is safe to ignore; discovery/query errors
    # must propagate before any media is unlinked.
    return [
        (table, column)
        for table, column in (
            ('trend_reference_assets', 'file_url'),
            ('saved_references', 'file_url'),
            ('wan3_prime_trend_recipes', 'recipe_json'),
            ('kling4_intents', 'recipe'),
            ('kling4_intents', 'snapshot'),
        )
        if await _table_exists(db, table)
    ]


async def _referenced(db, local: Path, optional_tables: list[tuple[str, str]]) -> bool:
    # The UUID-derived basename has no SQL wildcard. Overprotecting a match is
    # safe; deletion never depends on whether a task is public or terminal.
    match = '%' + local.stem + '%'
    for table, column in [('generation_tasks', 'request_data'), *optional_tables]:
        if await (await db.execute(
            f'SELECT 1 FROM {table} WHERE {column} LIKE ? LIMIT 1', (match,),
        )).fetchone():
            return True
    return False


async def cleanup_expired(*, limit: int = 100) -> dict[str, int]:
    from bot.services.wan3_prime_storage import CHUNK_ROOT, UPLOAD_ROOT, _now

    removed_sessions = removed_media = 0
    stamp = _now()
    stale_lease = (datetime.fromisoformat(stamp) - timedelta(seconds=positive_setting('WAN3_ASSEMBLY_LEASE_SECONDS', 300))).isoformat(' ')
    cutoff = (datetime.now(UTC) - timedelta(seconds=positive_setting('WAN3_UNUSED_MEDIA_TTL_SECONDS', 86400))).replace(tzinfo=None).isoformat(' ')
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        sessions = await (await db.execute(
            "SELECT upload_id FROM wan3_prime_upload_sessions WHERE ((expires_at <= ? "
            "AND status IN ('open', 'assembling', 'importing', 'rejected', 'failed', 'completed')) OR status = 'cancelled') AND updated_at <= ? "
            "ORDER BY expires_at LIMIT ?",
            (stamp, stale_lease, limit),
        )).fetchall()
    for session in sessions:
        async with db_backend.connect(database.DATABASE_PATH) as db:
            await lock_storage(db)
            current = await (await db.execute(
                "SELECT upload_id FROM wan3_prime_upload_sessions WHERE upload_id = ? AND "
                "((expires_at <= ? AND status IN ('open', 'assembling', 'importing', 'rejected', 'failed', 'completed')) "
                "OR status = 'cancelled') AND updated_at <= ?" + (' FOR UPDATE' if db_backend.is_postgres() else ''),
                (session['upload_id'], stamp, stale_lease),
            )).fetchone()
            if not current:
                continue
            directory = canonical_child_path(CHUNK_ROOT, session['upload_id'])
            try:
                if directory.exists():
                    await asyncio.to_thread(shutil.rmtree, directory)
            except OSError:
                logger.warning('Wan3 expired upload removal deferred: upload_id=%s', session['upload_id'])
                continue
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'expired', updated_at = ? "
                             "WHERE upload_id = ?", (stamp, session['upload_id']))
            await db.commit()
            removed_sessions += 1

    # Claim a bounded page, then release both the global quota lock AND the
    # cursor write transaction before scanning recipe/history text. Otherwise
    # init_upload's schema singleton writes can still wait on the cursor row.
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await lock_storage(db)
        cursor = await (await db.execute('SELECT last_media_id FROM wan3_prime_cleanup_cursor WHERE id = 1')).fetchone()
        after_id = int(cursor[0]) if cursor else 0
        rows = await (await db.execute(
            'SELECT id, public_url, local_path FROM wan3_prime_media WHERE created_at <= ? AND id > ? ORDER BY id LIMIT ?',
            (cutoff, after_id, limit),
        )).fetchall()
        # Persist progress, including pinned inputs; otherwise the oldest full
        # page of protected media would prevent any later orphan from expiring.
        await db.execute('UPDATE wan3_prime_cleanup_cursor SET last_media_id = ? WHERE id = 1',
                         (int(rows[-1]['id']) if rows else 0,))
        await db.commit()

    candidates = []
    async with db_backend.connect(database.DATABASE_PATH) as db:
        optional_tables = await _ownership_tables(db)
        for row in rows:
            local = Path(row['local_path']).resolve()
            try:
                local.relative_to(UPLOAD_ROOT.resolve())
            except ValueError:
                continue
            if not await _referenced(db, local, optional_tables):
                candidates.append(row)

    # An unlocked negative lookup is only a hint. Re-read the row and all pin
    # sources inside a fresh transaction immediately before deleting it. Each
    # candidate releases the quota lock independently; already-owned inputs
    # never take that lock for their expensive history lookup.
    for row in candidates:
        async with db_backend.connect(database.DATABASE_PATH) as db:
            db.row_factory = db_backend.Row
            await lock_storage(db)
            current = await (await db.execute(
                'SELECT id, public_url, local_path FROM wan3_prime_media WHERE id = ? AND created_at <= ?'
                + (' FOR UPDATE' if db_backend.is_postgres() else ''), (row['id'], cutoff),
            )).fetchone()
            if (not current or current['public_url'] != row['public_url']
                    or current['local_path'] != row['local_path']):
                continue
            local = Path(current['local_path']).resolve()
            try:
                local.relative_to(UPLOAD_ROOT.resolve())
            except ValueError:
                continue
            # Discover again: a newly created optional schema may now own it.
            if await _referenced(db, local, await _ownership_tables(db)):
                continue
            try:
                await asyncio.to_thread(local.unlink, missing_ok=True)
            except OSError:
                logger.warning('Wan3 unused media removal deferred: media_id=%s', row['id'])
                continue
            await db.execute('DELETE FROM wan3_prime_media WHERE id = ?', (row['id'],))
            await db.commit()
            removed_media += 1
    if removed_sessions or removed_media:
        logger.info('Wan3 retention: removed_sessions=%s removed_unused_media=%s', removed_sessions, removed_media)
    return {'removed_sessions': removed_sessions, 'removed_media': removed_media}

