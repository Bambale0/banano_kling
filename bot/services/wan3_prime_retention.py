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


async def cleanup_expired(*, limit: int = 100) -> dict[str, int]:
    from bot.services.wan3_prime_storage import CHUNK_ROOT, UPLOAD_ROOT

    removed_sessions = removed_media = 0
    stale_lease = (datetime.now(UTC) - timedelta(seconds=positive_setting('WAN3_ASSEMBLY_LEASE_SECONDS', 300))).replace(tzinfo=None).isoformat(' ')
    cutoff = (datetime.now(UTC) - timedelta(seconds=positive_setting('WAN3_UNUSED_MEDIA_TTL_SECONDS', 86400))).replace(tzinfo=None).isoformat(' ')
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await lock_storage(db)
        if await _table_exists(db, 'seedance_snapshot_reservations'):
            from bot.services.seedance_quote_snapshots import (
                cleanup_snapshot_reservations,
            )
            await cleanup_snapshot_reservations(db, cutoff=cutoff, limit=limit)
        sessions = await (await db.execute(
            "SELECT upload_id FROM wan3_prime_upload_sessions WHERE ((expires_at <= CURRENT_TIMESTAMP "
            "AND status IN ('open', 'assembling', 'importing', 'rejected', 'failed', 'completed')) OR status = 'cancelled') AND updated_at <= ? "
            "ORDER BY expires_at LIMIT ?" + (' FOR UPDATE' if db_backend.is_postgres() else ''),
            (stale_lease, limit),
        )).fetchall()
        for session in sessions:
            directory = canonical_child_path(CHUNK_ROOT, session['upload_id'])
            try:
                if directory.exists():
                    await asyncio.to_thread(shutil.rmtree, directory)
            except OSError:
                logger.warning('Wan3 expired upload removal deferred: upload_id=%s', session['upload_id'])
                continue
            await db.execute("UPDATE wan3_prime_upload_sessions SET status = 'expired', updated_at = CURRENT_TIMESTAMP "
                             "WHERE upload_id = ?", (session['upload_id'],))
            removed_sessions += 1
        optional_tables = [(table, column) for table, column in (('trend_reference_assets', 'file_url'),
            ('saved_references', 'file_url'), ('wan3_prime_trend_recipes', 'recipe_json')) if await _table_exists(db, table)]
        cursor = await (await db.execute('SELECT last_media_id FROM wan3_prime_cleanup_cursor WHERE id = 1')).fetchone()
        after_id = int(cursor[0]) if cursor else 0
        rows = await (await db.execute(
            'SELECT id, public_url, local_path, source FROM wan3_prime_media WHERE created_at <= ? AND id > ? ORDER BY id LIMIT ?',
            (cutoff, after_id, limit),
        )).fetchall()
        # Persist progress, including pinned inputs; otherwise the oldest full
        # page of protected media would prevent any later orphan from expiring.
        await db.execute('UPDATE wan3_prime_cleanup_cursor SET last_media_id = ? WHERE id = 1',
                         (int(rows[-1]['id']) if rows else 0,))
        for row in rows:
            # The UUID-derived basename has no SQL wildcard. Overprotecting a
            # match is safe; deletion never depends on whether a task is public.
            local = Path(row['local_path']).resolve()
            try:
                local.relative_to(UPLOAD_ROOT.resolve())
            except ValueError:
                continue
            match = '%' + local.stem + '%'
            if row['source'] == 'seedance_quote_snapshot':
                if not await _table_exists(db, 'seedance_quote_media_leases'):
                    continue  # Unknown lease schema must fail closed.
                from bot.services.seedance_quote_snapshots import snapshot_is_leased
                referenced = await snapshot_is_leased(db, row['id'])
            else:
                referenced = bool(await (await db.execute(
                    'SELECT 1 FROM generation_tasks WHERE request_data LIKE ? LIMIT 1', (match,),
                )).fetchone())
                if not referenced:
                    for table, column in optional_tables:
                        referenced = bool(await (await db.execute(
                            f'SELECT 1 FROM {table} WHERE {column} LIKE ? LIMIT 1', (match,),
                        )).fetchone())
                        if referenced:
                            break
            if referenced:
                continue
            try:
                await asyncio.to_thread(local.unlink, missing_ok=True)
            except OSError:
                logger.warning('Wan3 unused media removal deferred: media_id=%s', row['id'])
                continue
            if row['source'] == 'seedance_quote_snapshot':
                await db.execute('DELETE FROM seedance_quote_media_leases WHERE media_id = ?', (row['id'],))
            await db.execute('DELETE FROM wan3_prime_media WHERE id = ?', (row['id'],))
            removed_media += 1
        await db.commit()
    if removed_sessions or removed_media:
        logger.info('Wan3 retention: removed_sessions=%s removed_unused_media=%s', removed_sessions, removed_media)
    return {'removed_sessions': removed_sessions, 'removed_media': removed_media}

