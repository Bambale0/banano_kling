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
BACKFILL_MAX_BATCHES = max(
    1, int(os.getenv("RENDERGRID_IMAGE_BACKFILL_MAX_BATCHES", "1"))
)
MIN_VALID_IMAGE_BYTES = max(
    1, int(os.getenv("RENDERGRID_IMAGE_MIN_VALID_BYTES", "1024"))
)
UPLOAD_ROOT = Path("static/uploads")
RENDERGRID_RESULT_HOST = "cdn.rendergrid.io"
BACKFILL_CHECKPOINT_PATH = str(
    os.getenv("RENDERGRID_IMAGE_BACKFILL_CHECKPOINT_PATH", "") or ""
).strip()


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
    before_id: int | None = None,
) -> dict[str, int | bool | None]:
    safe_limit = max(1, int(limit))
    safe_before_id = int(before_id) if before_id is not None else None
    counters: dict[str, int | bool | None] = {
        "scanned": 0,
        "localized": 0,
        "updated": 0,
        "skipped_race": 0,
        "failed": 0,
        "next_before_id": safe_before_id,
        "exhausted": False,
    }

    where = [
        "type = 'image'",
        "status = 'completed'",
        "result_url LIKE 'https://cdn.rendergrid.io/%'",
    ]
    params: list[Any] = []
    if safe_before_id is not None:
        where.append("id < ?")
        params.append(safe_before_id)
    params.append(safe_limit)

    # Fetch candidates and release the database connection before any provider
    # download starts. Historical media can take seconds to fetch; keeping a
    # transaction open across those network waits creates unnecessary lock
    # pressure on the live generation_tasks table.
    async with db_backend.connect(DATABASE_PATH, timeout=30) as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            f"""
            SELECT id, task_id, result_url, result_urls
            FROM generation_tasks
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()

    row_ids = [int(row["id"]) for row in rows]
    counters["next_before_id"] = min(row_ids) if row_ids else safe_before_id
    counters["exhausted"] = len(rows) < safe_limit

    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def guarded(row: db_backend.Row):
        async with sem:
            return await _localize_row(row)

    results = await asyncio.gather(*(guarded(row) for row in rows))
    rows_by_id = {int(row["id"]): row for row in rows}

    # Re-open the database only for short compare-and-swap mutations. This
    # preserves the existing race protection without holding a transaction
    # while external media is downloaded.
    async with db_backend.connect(DATABASE_PATH, timeout=30) as db:
        for row_id, old_url, durable_url in results:
            counters["scanned"] = int(counters["scanned"] or 0) + 1
            if not durable_url:
                counters["failed"] = int(counters["failed"] or 0) + 1
                continue
            counters["localized"] = int(counters["localized"] or 0) + 1

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
                counters["updated"] = int(counters["updated"] or 0) + 1
            else:
                counters["skipped_race"] = int(counters["skipped_race"] or 0) + 1

        await db.commit()

    return counters


async def reconcile_rendergrid_image_results(
    *,
    limit: int = BACKFILL_LIMIT,
    concurrency: int = BACKFILL_CONCURRENCY,
    max_batches: int = BACKFILL_MAX_BATCHES,
    before_id: int | None = None,
) -> dict[str, int | bool | None]:
    totals: dict[str, int | bool | None] = {
        "batches": 0,
        "scanned": 0,
        "localized": 0,
        "updated": 0,
        "skipped_race": 0,
        "failed": 0,
        "next_before_id": before_id,
        "exhausted": False,
    }
    cursor = before_id

    for batch_index in range(max(1, int(max_batches))):
        batch = await backfill_rendergrid_image_results(
            limit=limit,
            concurrency=concurrency,
            before_id=cursor,
        )
        totals["batches"] = int(totals["batches"] or 0) + 1
        for key in ("scanned", "localized", "updated", "skipped_race", "failed"):
            totals[key] = int(totals[key] or 0) + int(batch[key] or 0)
        cursor = (
            int(batch["next_before_id"])
            if batch["next_before_id"] is not None
            else None
        )
        totals["next_before_id"] = cursor
        totals["exhausted"] = bool(batch["exhausted"])

        logger.info(
            "batch=%s scanned=%s localized=%s updated=%s skipped_race=%s failed=%s "
            "next_before_id=%s exhausted=%s",
            batch_index + 1,
            batch["scanned"],
            batch["localized"],
            batch["updated"],
            batch["skipped_race"],
            batch["failed"],
            batch["next_before_id"],
            batch["exhausted"],
        )
        if not batch["scanned"] or batch["exhausted"] or cursor is None:
            break

    return totals


def _load_checkpoint(path: str) -> int | None:
    candidate = str(path or "").strip()
    if not candidate:
        return None
    checkpoint_path = Path(candidate)
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError):
        logger.exception("Failed to read checkpoint: %s", checkpoint_path)
        return None
    value = payload.get("next_before_id") if isinstance(payload, dict) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid checkpoint cursor: %r", value)
        return None


def _save_checkpoint(path: str, next_before_id: int | None, *, exhausted: bool) -> None:
    candidate = str(path or "").strip()
    if not candidate:
        return
    checkpoint_path = Path(candidate)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    # Once one full pass reaches the oldest candidate, reset the cursor for the
    # next invocation. Remaining failed rows will then get another controlled
    # retry cycle instead of permanently blocking or being forgotten.
    persisted_cursor = None if exhausted else next_before_id
    payload = {
        "next_before_id": persisted_cursor,
        "last_pass_exhausted": bool(exhausted),
    }
    temp_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(checkpoint_path)


async def _main() -> int:
    before_raw = str(os.getenv("RENDERGRID_IMAGE_BACKFILL_BEFORE_ID", "") or "").strip()
    before_id = int(before_raw) if before_raw else _load_checkpoint(BACKFILL_CHECKPOINT_PATH)
    counters = await reconcile_rendergrid_image_results(before_id=before_id)
    _save_checkpoint(
        BACKFILL_CHECKPOINT_PATH,
        (
            int(counters["next_before_id"])
            if counters["next_before_id"] is not None
            else None
        ),
        exhausted=bool(counters["exhausted"]),
    )
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
