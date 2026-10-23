"""Prepare owned MOV references for Kling's MP4-only contract."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import tempfile
from copy import deepcopy
from pathlib import Path

from bot import database, db
from bot.services.kling4_contract import Kling4Error
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import ROOT, _kind_limit

logger = logging.getLogger(__name__)


async def _remux(source: Path, destination: Path, *, timeout: int):
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        "mov",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-fs",
        str(_kind_limit("video")),
        "-y",
        str(destination),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise Kling4Error(
            "Не удалось подготовить MOV. Отправьте видео в MP4 (H.264/AAC)."
        )


async def _mp4(actor, url, probe, *, timeout: int):
    # Ownership, immutable bytes and the local storage boundary are checked first.
    info = await probe.probe_url(url, kind="video")
    if info.extension != ".mov":
        return url
    if not info.duration_seconds or not 2 <= info.duration_seconds <= 30:
        raise Kling4Error(
            f"Видеореференс: {info.duration_seconds}с; допустимо 2–30 секунд."
        )
    source_key = f"kling4_mp4_v1:{info.sha256}"
    locks = ROOT / "kling4_conversion_locks"
    locks.mkdir(parents=True, exist_ok=True)
    # The shared upload volume makes this lock effective across bot processes.
    # Never unlink lock files: another process may already have the inode open.
    with (locks / f"{actor.user_id}-{info.sha256}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Kling4Error(
                "Это видео ещё подготавливается. Повторите промпт через несколько секунд.",
                status=409,
            ) from exc
        async with db.connect(database.DATABASE_PATH) as conn:
            rows = await (
                await conn.execute(
                    "SELECT public_url FROM wan3_prime_media WHERE user_id=? AND source=? ORDER BY id DESC",
                    (actor.user_id, source_key),
                )
            ).fetchall()
        for row in rows:
            try:
                cached = await probe.probe_url(row[0], kind="video")
            except Wan3PrimeValidationError:
                continue
            if cached.extension == ".mp4":
                return row[0]
        try:
            with tempfile.TemporaryDirectory(prefix="kling4-mp4-") as temp:
                output = Path(temp) / "reference.mp4"
                from bot.services.wan3_prime_probe_cache import probe_slot

                async with probe_slot(actor.user_id):
                    await _remux(Path(info.path), output, timeout=timeout)
                measured = await probe.probe_file(str(output), kind="video")
                if (
                    not measured.duration_seconds
                    or abs(measured.duration_seconds - info.duration_seconds) > 0.15
                    or (measured.width, measured.height) != (info.width, info.height)
                ):
                    raise Kling4Error(
                        "Подготовка MOV изменила длительность или размер кадра. Отправьте MP4."
                    )
                saved = await probe.storage.save_owned_file(
                    actor,
                    kind="video",
                    filename="reference.mp4",
                    path=output,
                    content_type="video/mp4",
                    source=source_key,
                )
        except (OSError, TimeoutError) as exc:
            logger.warning(
                "Kling4 MOV conversion failed: user_id=%s error_type=%s",
                actor.user_id,
                type(exc).__name__,
            )
            raise Kling4Error(
                "Не удалось подготовить MOV. Повторите запрос или отправьте MP4."
            ) from exc
        logger.info(
            "Kling4 MOV prepared: user_id=%s sha256=%s duration=%s",
            actor.user_id,
            info.sha256,
            info.duration_seconds,
        )
        return saved["url"]


async def prepare_request(actor, request, probe, *, timeout: int):
    """Normalize copies only; original recipe and idempotency hash stay intact."""
    prepared = deepcopy(request)
    if not isinstance(prepared, dict) or prepared.get("mode") != "reference":
        return prepared
    data = prepared.get("input")
    if not isinstance(data, dict):
        return prepared
    videos = data.get("video_urls")
    if isinstance(videos, list):
        for index, url in enumerate(videos):
            if isinstance(url, str):
                videos[index] = await _mp4(actor, url, probe, timeout=timeout)
    elements = data.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if isinstance(element, dict) and isinstance(element.get("video_url"), str):
                element["video_url"] = await _mp4(
                    actor, element["video_url"], probe, timeout=timeout
                )
    return prepared
