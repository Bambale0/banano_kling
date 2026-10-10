"""Recover corrupt/transient provider files without retrying paid generation."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from bot import database
from bot import db as db_backend
from bot.services.wan3_prime_schema import execute_wan_ddl
from bot.services.wan3_prime_storage_policy import positive_setting

logger = logging.getLogger(__name__)


async def init_result_repair_schema() -> None:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await execute_wan_ddl(db, '''CREATE TABLE IF NOT EXISTS wan3_prime_result_retries (
            internal_task_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.commit()


async def reject_invalid_result(task_id: str, local_path: str | None = None) -> None:
    if local_path:
        path = Path(local_path).resolve()
        try:
            path.relative_to(Path('static/uploads/wan3_prime/results').resolve())
        except ValueError:
            logger.error('Wan3 invalid result outside managed root: task_id=%s', task_id)
        else:
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError:
                # Clearing the reference causes the next canonical download to
                # replace the bad file instead of repeatedly probing it.
                logger.warning('Wan3 invalid file removal deferred: task_id=%s', task_id)
    maximum = positive_setting('WAN3_RESULT_PROBE_MAX_ATTEMPTS', 5)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute('BEGIN' if db_backend.is_postgres() else 'BEGIN IMMEDIATE')
        await db.execute('''INSERT INTO wan3_prime_result_retries (internal_task_id, attempts) VALUES (?, 1)
            ON CONFLICT (internal_task_id) DO UPDATE SET
            attempts = wan3_prime_result_retries.attempts + 1, updated_at = CURRENT_TIMESTAMP''', (task_id,))
        row = await (await db.execute('SELECT attempts FROM wan3_prime_result_retries WHERE internal_task_id = ?', (task_id,))).fetchone()
        attempts = int(row[0])
        status = 'result_attention' if attempts >= maximum else 'settlement_pending'
        await db.execute('''UPDATE wan3_prime_intents SET status = ?, provider_state = 'success',
            result_path = NULL, result_url = NULL, error_code = 'result_validation_failed',
            error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE internal_task_id = ? AND settled = 0''',
            (status, 'Result needs operator review' if status == 'result_attention' else 'Retrying result download', task_id))
        await db.commit()
    logger.warning('Wan3 invalid result: task_id=%s attempts=%s status=%s action=%s',
                   task_id, attempts, status, 'operator_review' if status == 'result_attention' else 'redownload')
