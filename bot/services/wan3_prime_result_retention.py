"""Task-aware result expiry and capacity admission before any paid submission."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot import database
from bot import db as db_backend
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_retention import _table_exists
from bot.services.wan3_prime_storage_policy import lock_storage, positive_setting

logger = logging.getLogger(__name__)
RESULT_ROOT = Path('static/uploads/wan3_prime/results')


def _result_bytes() -> int:
    if not RESULT_ROOT.is_dir():
        return 0
    total = 0
    with os.scandir(RESULT_ROOT) as entries:
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                continue
    return total


async def assert_result_capacity(db) -> None:
    """Caller holds the shared storage lock through reservation persistence."""
    maximum = positive_setting('WAN3_RESULT_MAX_BYTES', 250 * 1024**2)
    quota = positive_setting('WAN3_RESULT_GLOBAL_QUOTA_BYTES', 20 * 1024**3)
    # Count reservations first. A concurrent settlement may make a file visible
    # during the scan, but can never remove it from both halves of accounting.
    row = await (await db.execute('SELECT COUNT(*) FROM wan3_prime_intents WHERE settled = 0')).fetchone()
    reserved = int(row[0]) * maximum
    retained = await asyncio.to_thread(_result_bytes)
    if retained + reserved > quota:
        raise Wan3PrimeValidationError('Result storage capacity is full; no funds were charged', status=503)
    volume = RESULT_ROOT.resolve()
    while not volume.exists():
        volume = volume.parent
    disk = await asyncio.to_thread(shutil.disk_usage, volume)
    if disk.free - reserved * 2 < positive_setting('WAN3_UPLOAD_MIN_FREE_BYTES', 1024**3):
        raise Wan3PrimeValidationError('Not enough result storage space; no funds were charged', status=503)


async def cleanup_results(*, limit: int = 100) -> int:
    cutoff = (datetime.now(UTC) - timedelta(seconds=positive_setting('WAN3_RESULT_RETENTION_SECONDS', 30 * 86400))).replace(tzinfo=None).isoformat(' ')
    removed = 0
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        if not await _table_exists(db, 'wan3_prime_intents'):
            return 0
        await lock_storage(db)
        await db.execute('INSERT INTO wan3_prime_cleanup_cursor (id) VALUES (2) ON CONFLICT (id) DO NOTHING')
        cursor = await (await db.execute('SELECT last_media_id FROM wan3_prime_cleanup_cursor WHERE id = 2')).fetchone()
        rows = await (await db.execute('''SELECT gt.id, gt.task_id, gt.request_data,
                gt.is_public_feed, gt.is_profile_visible, intent.result_path
            FROM generation_tasks gt JOIN wan3_prime_intents intent ON intent.internal_task_id = gt.task_id
            WHERE gt.id > ? AND gt.status = 'completed' AND gt.completed_at <= ?
              AND intent.settled = 1 AND intent.delivery_status = 'delivered' AND intent.result_path IS NOT NULL
            ORDER BY gt.id LIMIT ?''' + (' FOR UPDATE OF gt, intent' if db_backend.is_postgres() else ''),
            (int(cursor[0]), cutoff, limit))).fetchall()
        await db.execute('UPDATE wan3_prime_cleanup_cursor SET last_media_id = ? WHERE id = 2',
                         (int(rows[-1]['id']) if rows else 0,))
        protected_tables = [(table, column) for table, column in (
            ('user_prompts', 'preview_url'), ('saved_references', 'file_url'),
            ('wan3_prime_trend_recipes', 'recipe_json'),
        ) if await _table_exists(db, table)]
        for row in rows:
            if row['is_public_feed'] or row['is_profile_visible']:
                continue
            path = Path(row['result_path']).resolve()
            try:
                path.relative_to(RESULT_ROOT.resolve())
            except ValueError:
                continue
            match = '%' + path.name + '%'
            in_use = bool(await (await db.execute('SELECT 1 FROM generation_tasks WHERE id <> ? AND request_data LIKE ? LIMIT 1',
                                                  (row['id'], match))).fetchone())
            for table, column in protected_tables:
                if in_use:
                    break
                in_use = bool(await (await db.execute(f'SELECT 1 FROM {table} WHERE {column} LIKE ? LIMIT 1', (match,))).fetchone())
            if in_use:
                continue
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError:
                logger.warning('Wan3 result expiry deferred: task_id=%s', row['task_id'])
                continue
            metadata = json.loads(row['request_data'] or '{}')
            metadata['result_expired'] = True
            metadata['result_expired_at'] = datetime.now(UTC).isoformat()
            await db.execute('UPDATE generation_tasks SET result_url = NULL, result_urls = NULL, request_data = ?, '
                             'updated_at = CURRENT_TIMESTAMP WHERE id = ?', (json.dumps(metadata), row['id']))
            await db.execute('UPDATE wan3_prime_intents SET result_path = NULL, result_url = NULL '
                             'WHERE internal_task_id = ?', (row['task_id'],))
            removed += 1
        await db.commit()
    if removed:
        logger.info('Wan3 expired private delivered results: count=%s', removed)
    return removed


async def lock_publication(db, generation_id: int | str, user_id: int) -> None:
    """Hold expiry's lock from the fresh publication read through media copy/commit."""
    clause, value = database._generation_identifier_clause(generation_id)
    row = await (await db.execute(f'SELECT task_id, model FROM generation_tasks WHERE {clause} AND user_id = ?',
                                  (value, user_id))).fetchone()
    if row and (str(row[0] or '').startswith('wan3_') or row[1] == 'wan_3_prime'):
        await lock_storage(db)
