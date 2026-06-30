#!/usr/bin/env python3
"""Скачивает все внешние медиа-файлы для ленты на сервер и обновляет БД."""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    import aiosqlite

    from bot.database import DATABASE_PATH
    from bot.services.media_storage import _ensure_media_dir, download_media

    await _ensure_media_dir()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Все completed задачи с внешним result_url
        cursor = await db.execute(
            """
            SELECT task_id, result_url FROM generation_tasks
            WHERE status = 'completed'
              AND result_url IS NOT NULL
              AND result_url != ''
              AND (result_url LIKE 'http://%' OR result_url LIKE 'https://%')
            ORDER BY id DESC
            """,
        )
        rows = await cursor.fetchall()
        total = len(rows)
        logger.info("Found %d tasks with external URLs to download", total)

        downloaded = 0
        failed = 0
        skipped = 0

        for i, row in enumerate(rows, 1):
            task_id = row["task_id"]
            url = row["result_url"]
            logger.info("[%d/%d] Processing %s...", i, total, task_id)

            stored_url, error = await download_media(task_id, url)
            if stored_url and stored_url != url and not stored_url.startswith(("http://", "https://")):
                # Обновляем в БД
                await db.execute(
                    "UPDATE generation_tasks SET result_url = ? WHERE task_id = ?",
                    (stored_url, task_id),
                )
                downloaded += 1
                logger.info("  -> downloaded to %s", stored_url)
            elif stored_url == url:
                skipped += 1
                logger.info("  -> skipped (same URL)")
            else:
                failed += 1
                logger.warning("  -> failed: %s", error)

        await db.commit()

    logger.info(
        "Done: %d downloaded, %d failed, %d skipped out of %d total",
        downloaded, failed, skipped, total,
    )


if __name__ == "__main__":
    asyncio.run(main())