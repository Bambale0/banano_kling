#!/usr/bin/env python3
"""Localize historical RenderGrid image results into durable backend storage.

RenderGrid result URLs are not a durable storage contract. New image completions
are localized by bot.main; this script repairs historical generation_tasks rows
that still point at cdn.rendergrid.io.

Rows are updated only after a non-empty local file exists. The UPDATE uses the
old result_url as a compare-and-swap guard so concurrent task updates are not
overwritten.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from bot import db as db_backend
from bot.database import DATABASE_PATH
from bot.services.feed_persist import FEED_MEDIA_MAX_BYTES, persist_feed_result_urls

logger = logging.getLogger("rendergrid-image-backfill")

BACKFILL_LIMIT = max(1, int(os.getenv("RENDERGRID_IMAGE_BACKFILL_LIMIT", "500")))
BACKFILL_CONCURRENCY = max(
    1, min(16, int(os.getenv("RENDERGRID_IMAGE_BACKFILL_CONCURRENCY", "6")))
)
MIN_VALID_IMAGE_BYTES = max(
    1, int(os.getenv("RENDERGRID_IMAGE_MIN_VALID_BYTES", "1024"))
)
UPLOAD_ROOT = Path("static/uploads")
RENDERGRID_RESULT_HOST = "cdn.rendergrid.io"


def _parse_result_urls(value: Any, fallback: str | None = None) -> list[str]:
    parsed: Any = value
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = [raw]
        else:
            parsed = []

    if not isinstance(parsed, (list, tuple)):
        parsed = []

    urls: list[str] = []
    for item in parsed:
        url = str(item or "").strip()
        if url and url not in urls:
            urls.append(url)

    fallback_url = str(fallback or "").strip()
    if fallback_url and fallback_url not in urls:
        urls.insert(0, fallback_url)
    return urls


def _is_rendergrid_result_url(url: str) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").strip().lower().lstrip(".")
    except ValueError:
        return False
    return host == RENDERGRID_RESULT_HOST or host.endswith(f".{RENDERGRID_RESULT_HOST}")


def _durable_feed_path(url: str) -> Path | None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    path = unquote(parsed.path if parsed.scheme else str(url or ""))
    prefix = "/uploads/feed/"
    if not path.startswith(prefix) or "/thumbs/" in path:
        return None

    relative = path[len("/uploads/") :].lstrip("/")
    candidate = UPLOAD_ROOT / relative
    try:
        candidate.resolve().relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        return None
    return candidate


def _durable_file_exists(url: str) -> bool:
    path = _durable_feed_path(url)
    if not path:
        return False
    try:
        return path.is_file() and path.stat().st_size >= MIN_VALID_IMAGE_BYTES
    except OSError:
        return False


def _replace_result_url_list(
    raw_result_urls: Any,
    *,
    old_url: str,
    new_url: str,
) -> str:
    urls = _parse_result_urls(raw_result_urls, old_url)
    replaced = [new_url if item == old_url else item for item in urls]
    if new_url not in replaced:
        replaced.insert(0, new_url)
    deduped: list[str] = []
    for item in replaced:
        if item and item not in deduped:
            deduped.append(item)
    return json.dumps(deduped, ensure_ascii=False)


async def _localize_row(row: db_backend.Row) -> tuple[int, str, str | None]:
    row_id = int(row["id"])
    source_url = str(row["result_url"] or "").strip()
    if not source_url or not _is_rendergrid_result_url(source_url):
        return row_id, source_url, None

    try:
        persisted = await persist_feed_result_urls(
            [source_url],
            require_local=True,
            max_size_bytes=FEED_MEDIA_MAX_BYTES,
        )
    except Exception:
        logger.exception("row=%s localization crashed", row_id)
        return row_id, source_url, None

    if not persisted:
        return row_id, source_url, None
    durable_url = str(persisted[0] or "").strip()
    if not durable_url or not _durable_file_exists(durable_url):
        logger.warning("row=%s produced no valid durable file", row_id)
        return row_id, source_url, None
    return row_id, source_url, durable_url


async def backfill_rendergrid_image_results(
    *,
    limit: int = BACKFILL_LIMIT,
    concurrency: int = BACKFILL_CONCURRENCY,
) -> dict[str, int]:
    counters = {
        "scanned": 0,
        "localized": 0,
        "updated": 0,
        "skipped_race": 0,
        "failed": 0,
    }

    async with db_backend.connect(DATABASE_PATH, timeout=30) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT id, task_id, result_url, result_urls
            FROM generation_tasks
            WHERE type = 'image'
              AND status = 'completed'
              AND result_url LIKE 'https://cdn.rendergrid.io/%'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        rows = await cursor.fetchall()

        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def guarded(row: db_backend.Row):
            async with sem:
                return await _localize_row(row)

        results = await asyncio.gather(*(guarded(row) for row in rows))
        rows_by_id = {int(row["id"]): row for row in rows}

        for row_id, old_url, durable_url in results:
            counters["scanned"] += 1
            if not durable_url:
                counters["failed"] += 1
                continue
            counters["localized"] += 1

            row = rows_by_id[row_id]
            result_urls_json = _replace_result_url_list(
                row["result_urls"],
                old_url=old_url,
                new_url=durable_url,
            )
            cursor = await db.execute(
                """
                UPDATE generation_tasks
                SET result_url = ?,
                    result_urls = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND result_url = ?
                """,
                (durable_url, result_urls_json, row_id, old_url),
            )
            if cursor.rowcount == 1:
                counters["updated"] += 1
            else:
                counters["skipped_race"] += 1

        await db.commit()

    return counters


async def _main() -> int:
    counters = await backfill_rendergrid_image_results()
    print(
        "[rendergrid-image-backfill] "
        + " ".join(f"{key}={value}" for key, value in counters.items())
    )
    return 0 if counters["failed"] == 0 else 2


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(_main()))
