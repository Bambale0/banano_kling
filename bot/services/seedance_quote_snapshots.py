"""Immutable Seedance quote inputs in existing owner/quota managed storage."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path

from bot import database
from bot import db as db_backend
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.video_reference_measurement import (
    MAX_VIDEO_BYTES,
    _file_hash,
    _probe_seconds,
)
from bot.services.wan3_prime_media import MediaInfo, canonical_child_path
from bot.services.wan3_prime_probe_cache import probe_slot
from bot.services.wan3_prime_storage import (
    CHUNK_ROOT,
    Wan3PrimeStorage,
    fetch_public_asset,
)
from bot.services.wan3_prime_storage_policy import lock_storage


def _copy_bounded(source: Path, destination: Path):
    """Create private owned staging once; later probe never sees a mutable source."""
    total = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_VIDEO_BYTES:
                raise ValueError("Видео-референс превышает 200 MB")
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    if not total:
        raise ValueError("Видео-референс пуст")


async def _snapshot(actor, source: str, storage: Wan3PrimeStorage, *, occurrence: int = 0) -> dict:
    reservation = await storage.init_upload(actor, kind="video", filename="quote.mp4",
                                             size=MAX_VIDEO_BYTES, importing=True)
    upload_id = reservation["upload_id"]
    staged = canonical_child_path(CHUNK_ROOT, f"{upload_id}/snapshot.mp4")
    persisted = False
    persistence = None
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("INSERT INTO seedance_snapshot_reservations(upload_id,user_id) VALUES (?,?)",
                         (upload_id, actor.user_id))
        await db.commit()
    try:
        local = resolve_local_upload_path(source)
        if local:
            local = Path(local).resolve()
            if Path("static/uploads").resolve() not in local.parents or not local.is_file():
                raise ValueError("Видео недоступно в хранилище")
            copying = asyncio.create_task(asyncio.to_thread(_copy_bounded, local, staged))
            try:
                await asyncio.shield(copying)
            except asyncio.CancelledError:
                await asyncio.shield(copying)
                raise
        else:
            await fetch_public_asset(source, destination=staged, max_bytes=MAX_VIDEO_BYTES, timeout_seconds=45)
        # The unique staging object is never exposed to clients or overwritten.
        # Probe the copied bytes, then verify the same hash at final persistence.
        digest = await asyncio.to_thread(_file_hash, staged)
        seconds = await _probe_seconds(staged)
        if not math.isfinite(seconds) or not 2 <= seconds <= 30:
            raise ValueError("Видео-референс должно длиться 2–30 секунд")
        size = staged.stat().st_size
        source_key = "seedance-quote-" + hashlib.sha256(f"{source}\nslot-occurrence:{occurrence}".encode()).hexdigest() + ".mp4"
        async with db_backend.connect(database.DATABASE_PATH) as db:
            db.row_factory = db_backend.Row
            await lock_storage(db)
            row = await (await db.execute(
                "SELECT id,public_url,local_path,sha256 FROM wan3_prime_media "
                "WHERE user_id=? AND sha256=? AND size_bytes=? AND filename=? "
                "AND source='seedance_quote_snapshot' ORDER BY id LIMIT 1",
                (actor.user_id, digest, size, source_key),
            )).fetchone()
            if row and Path(row["local_path"]).is_file() and await asyncio.to_thread(_file_hash, Path(row["local_path"])) == digest:
                # Keep a recently reused snapshot outside the 24h orphan grace
                # while the quote/lease transaction is being created.
                await db.execute("UPDATE wan3_prime_media SET created_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                await db.commit()
                return {"media_id": row["id"], "url": row["public_url"], "seconds": seconds, "sha256": digest}
            await db.commit()
        info = MediaInfo(kind="video", url="", sha256=digest, size_bytes=size,
                         duration_seconds=seconds, extension=".mp4")
        persistence = asyncio.create_task(storage._persist_owned_file(
            actor, kind="video", filename=source_key, path=staged, info=info,
            content_type="video/mp4", source="seedance_quote_snapshot", upload_id=upload_id,
            assembly_stamp=None, expected_sha256=digest,
        ))
        try:
            saved = await asyncio.shield(persistence)
        except asyncio.CancelledError:
            await asyncio.shield(persistence)
            raise
        persisted = True
        return {"media_id": saved["reference"]["id"], "url": saved["url"], "seconds": seconds, "sha256": digest}
    finally:
        # Existing reservation stays accounted for until staging is gone. On an
        # uncertain final commit keep the reservation for bounded orphan GC.
        if (persisted or persistence is None
                or (persistence.done() and not persistence.cancelled() and persistence.exception() is None)):
            cleanup = asyncio.create_task(storage.discard_import(actor, upload_id))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await asyncio.shield(cleanup)
                raise


async def authorize_video_sources(actor, sources: list[str], *, server_authorized: bool = False):
    """Public remote URLs are fetchable; local paths additionally need ownership.

    The caller may authorize retained private/trend sources only after rebuilding
    their server-owned permission context; this flag is never client supplied.
    """
    if server_authorized:
        return
    own_root = (Path("static/uploads/refs/video") / str(actor.telegram_id)).resolve()
    for source in sources:
        local = resolve_local_upload_path(source)
        if not local:
            continue
        path = Path(local).resolve()
        if own_root in path.parents:
            continue
        async with db_backend.connect(database.DATABASE_PATH) as db:
            row = await (await db.execute("SELECT 1 FROM wan3_prime_media WHERE user_id=? AND local_path=? AND kind='video' LIMIT 1",
                                          (actor.user_id, str(path)))).fetchone()
        if not row:
            raise ValueError("Загрузите своё видео-референс через форму")


async def prepare_video_snapshots(actor, sources: list[str]) -> list[dict]:
    """Caller has already authorized the full effective recipe (including hidden refs)."""
    if not 1 <= len(sources) <= 10:
        raise ValueError("Нужно от 1 до 10 видео-референсов")
    storage = Wan3PrimeStorage()
    await storage.init_schema()
    snapshots = []
    occurrences = {}
    # Shared bounded admission and whole-plan deadline, including downloads.
    async with probe_slot(actor.user_id), asyncio.timeout(120):
        for source in sources:
            occurrence = occurrences.get(source, 0)
            occurrences[source] = occurrence + 1
            # Distinct provider URLs preserve repeated slots through adapters
            # that de-duplicate URL strings. Same-slot objects still reuse across quotes.
            snapshots.append(await _snapshot(actor, source, storage, occurrence=occurrence))
    if math.fsum(item["seconds"] for item in snapshots) > 30.01:
        raise ValueError("Суммарная длительность видео-референсов — максимум 30 секунд")
    return snapshots


async def snapshot_is_leased(db, media_id: int) -> bool:
    """Called under the same storage lock as quote creation and paid claim."""
    row = await (await db.execute(
        "SELECT 1 FROM seedance_quote_media_leases l JOIN seedance_quote_receipts q ON q.quote_id=l.quote_id "
        "WHERE l.media_id=? AND ((q.phase='quoted' AND q.expires_at>CURRENT_TIMESTAMP) "
        "OR q.phase IN ('submitting','outcome_unknown') "
        "OR (q.phase='accepted' AND (q.canonical_bound=0 "
        "OR NOT EXISTS (SELECT 1 FROM generation_tasks g WHERE g.task_id=q.provider_task_id) "
        "OR EXISTS (SELECT 1 FROM generation_tasks g WHERE g.task_id=q.provider_task_id "
        "AND (g.status NOT IN ('completed','failed') OR g.completed_at IS NULL OR g.completed_at>?)))) "
        "OR (q.phase IN ('rejected','provider_failed') AND q.updated_at>?)) LIMIT 1",
        (media_id, _retention_cutoff(), _retention_cutoff()),
    )).fetchone()
    return bool(row)


def _retention_cutoff():
    from datetime import UTC, datetime, timedelta
    return (datetime.now(UTC) - timedelta(days=30)).replace(tzinfo=None).isoformat(" ")


async def cleanup_snapshot_reservations(db, *, cutoff: str, limit: int):
    """GC only feature-owned stale reservations; caller holds shared storage lock."""
    import shutil

    from bot.services.wan3_prime_storage import UPLOAD_ROOT

    rows = await (await db.execute(
        "SELECT upload_id,user_id FROM seedance_snapshot_reservations WHERE created_at<=? LIMIT ?",
        (cutoff, limit),
    )).fetchall()
    for row in rows:
        upload_id, user_id = row[0], row[1]
        final = canonical_child_path(UPLOAD_ROOT, f"{user_id}/{upload_id}.mp4")
        registered = await (await db.execute("SELECT 1 FROM wan3_prime_media WHERE local_path=? LIMIT 1",
                                             (str(final),))).fetchone()
        if not registered:
            await asyncio.to_thread(final.unlink, missing_ok=True)
        staged = canonical_child_path(CHUNK_ROOT, upload_id)
        if staged.exists():
            await asyncio.to_thread(shutil.rmtree, staged)
        await db.execute("UPDATE wan3_prime_upload_sessions SET status='expired',updated_at=CURRENT_TIMESTAMP "
                         "WHERE upload_id=? AND user_id=? AND status IN ('importing','failed','rejected')",
                         (upload_id, user_id))
        await db.execute("DELETE FROM seedance_snapshot_reservations WHERE upload_id=?", (upload_id,))


async def verify_quote_snapshots(db, quote_id: str, user_id: int):
    """Fail before debit if an immutable object was removed/tampered with."""
    from bot.services.seedance_quote_receipts import QuoteConflict
    from bot.services.wan3_prime_storage import UPLOAD_ROOT

    receipt = await (await db.execute("SELECT provider_json FROM seedance_quote_receipts WHERE quote_id=? AND user_id=?",
                                      (quote_id, user_id))).fetchone()
    recipe = json.loads(receipt[0]) if receipt else {}
    expected = recipe.get("_snapshot_media_ids")
    if not isinstance(expected, list) or not expected or any(not isinstance(value, int) for value in expected):
        raise QuoteConflict("План референсов недоступен")
    rows = await (await db.execute(
        "SELECT l.media_id,m.public_url,m.local_path,m.sha256,m.user_id,m.source FROM seedance_quote_media_leases l "
        "LEFT JOIN wan3_prime_media m ON m.id=l.media_id WHERE l.quote_id=?", (quote_id,),
    )).fetchall()
    if {row["media_id"] for row in rows} != set(expected):
        raise QuoteConflict("Референсы расчёта недоступны. Загрузите видео заново")
    urls = recipe.get("video_urls", recipe.get("video_references"))
    by_id = {row["media_id"]: row for row in rows}
    if not isinstance(urls, list) or len(urls) != len(expected) or any(
            url != by_id[media_id]["public_url"] for media_id, url in zip(expected, urls)):
        raise QuoteConflict("Состав референсов расчёта изменился")
    for row in rows:
        if not row["local_path"] or row["source"] != "seedance_quote_snapshot":
            raise QuoteConflict("Референс расчёта удалён")
        path = Path(row["local_path"]).resolve()
        if (row["user_id"] != user_id or UPLOAD_ROOT.resolve() not in path.parents
                or not path.is_file() or await asyncio.to_thread(_file_hash, path) != row["sha256"]):
            raise QuoteConflict("Референсы расчёта изменились. Загрузите видео заново")
