"""Bounded backfill for small trend MP4s and posters.

Run from /app inside the bot container. Read-only until --execute is supplied.
Never rewrites originals or publishes any private provider reference URLs.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from bot import db as db_backend
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.trend_preview_service import (
    cached_trend_preview_assets,
    ensure_trend_preview_assets,
)

logger = logging.getLogger(__name__)


async def run(*, limit: int, before_id: int | None, execute: bool) -> dict[str, int]:
    from bot import database

    args: list[int] = []
    where = """WHERE status = 'approved'
        AND LOWER(COALESCE(tags, '')) LIKE '%"trend"%'
        AND preview_url IS NOT NULL AND preview_url <> ''"""
    if before_id is not None:
        where += " AND id < ?"
        args.append(before_id)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        rows = await (await db.execute(
            "SELECT id, preview_url FROM user_prompts " + where + " ORDER BY id DESC LIMIT ?",
            (*args, limit),
        )).fetchall()

    outcome = {"checked": 0, "cached": 0, "created": 0, "failed": 0, "skipped": 0}
    for row in rows:
        url = str(row[1] or "")
        if not resolve_local_upload_path(url):
            outcome["skipped"] += 1
            continue
        outcome["checked"] += 1
        cached = cached_trend_preview_assets(url)
        if cached["preview_poster_url"] and cached["preview_url"] != url:
            outcome["cached"] += 1
            continue
        if not execute:
            outcome["skipped"] += 1
            continue
        try:
            generated = await ensure_trend_preview_assets(url)
            if generated["preview_poster_url"] and generated["preview_url"] != url:
                outcome["created"] += 1
            else:
                outcome["failed"] += 1
        except Exception:
            # Do not print URLs: originals may come from expiring external sources.
            logger.exception("Trend preview backfill failed: prompt_id=%s", row[0])
            outcome["failed"] += 1
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--before-id", type=int)
    parser.add_argument("--execute", action="store_true", help="Without this, only count pending assets")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be between 1 and 200")
    if args.before_id is not None and args.before_id <= 0:
        parser.error("--before-id must be positive")
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run(limit=args.limit, before_id=args.before_id, execute=args.execute))
    print(result)


if __name__ == "__main__":
    main()
