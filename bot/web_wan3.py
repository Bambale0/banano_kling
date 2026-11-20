"""Authenticated, metadata-backed web Wan3 quotes without Telegram actors.

Every input URL is looked up from the web account, then the S3 object hash and
file signature are verified and probed locally before the price is quoted.
The canonical Wan3 service receives a frozen recipe after those checks.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from bot import web_references
from bot.services.wan3_prime_media import (
    Wan3PrimeValidationError,
    _check_dimensions,
    _check_duration,
    _check_size,
)


async def prepare_owned_wan_media(account_id: str, payload: dict) -> None:
    """Validate actual media and persist input seconds for immutable billing."""
    if payload["model"] not in {"wan_3", "wan_3_prime"}:
        return
    image_ids = payload["reference_ids"]
    video_ids = payload["video_reference_ids"]
    audio_ids = payload["audio_reference_ids"]
    scenario = payload["wan_scenario"]
    images = await web_references.owned_reference_media(account_id, image_ids, kind="image")
    videos = await web_references.owned_reference_media(account_id, video_ids, kind="video")
    audios = await web_references.owned_reference_media(account_id, audio_ids, kind="audio")
    files = await web_references.owned_reference_media(
        account_id, payload["file_reference_ids"], kind="file",
    )
    links = await web_references.owned_reference_urls(
        account_id, payload["link_reference_ids"], kind="link",
    )
    for info in files:
        from bot.services.wan3_prime_media import DOCUMENT_EXTENSIONS

        if (info.extension or "").lower() not in DOCUMENT_EXTENSIONS:
            raise ValueError("Unsupported Wan3 document")
        _check_size(info, max_bytes=100 * 1024 * 1024)
        if info.pages is not None and info.pages > 50:
            raise ValueError("Wan3 document cannot exceed 50 pages")
    for url in links:
        from bot.services.wan3_prime_media import assert_public_url
        from bot.services.wan3_prime_storage import fetch_public_asset

        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError("Unsafe stored Wan3 webpage reference")
        await assert_public_url(url)
        result = await fetch_public_asset(
            url, destination=None, max_bytes=2 * 1024 * 1024,
            webpage=True, timeout_seconds=35,
        )
        if (result.get("url") != url
                or result.get("content_type") not in (
                    "text/html", "application/xhtml+xml",
                )):
            raise ValueError("Wan3 linked webpage has moved or changed content type")

    # Use the exact same media limits as the established Wan3 lifecycle.
    for info in images:
        _check_size(info, max_bytes=20 * 1024 * 1024)
        _check_dimensions(info, min_px=240, max_px=8000)
        if info.has_alpha or (info.extension or "").lower() not in {
            ".jpg", ".jpeg", ".png", ".bmp", ".webp",
        }:
            raise Wan3PrimeValidationError("Unsupported image input")
    video_seconds = 0.0
    for info in videos:
        if (info.extension or "").lower() not in {".mp4", ".mov"}:
            raise Wan3PrimeValidationError("Wan3 video input must be MP4 or MOV")
        _check_size(info, max_bytes=100 * 1024 * 1024)
        _check_dimensions(info, min_px=240, max_px=4096)
        video_seconds += _check_duration(info, kind="video")
    audio_seconds = 0.0
    for info in audios:
        if (info.extension or "").lower() not in {".mp3", ".wav"}:
            raise Wan3PrimeValidationError("Wan3 audio must be MP3 or WAV")
        _check_size(info, max_bytes=15 * 1024 * 1024)
        audio_seconds += _check_duration(info, kind="audio")
    if (not math.isfinite(video_seconds) or video_seconds > 15
            or not math.isfinite(audio_seconds) or audio_seconds > 15):
        raise Wan3PrimeValidationError("Reference media duration exceeds Wan3 limits")
    if scenario == "edit" and not videos:
        raise Wan3PrimeValidationError("Wan3 editing requires an owned input video")
    if scenario == "file" and (len(files) != 1 or links or videos or audios or images):
        raise Wan3PrimeValidationError("Wan3 file mode requires one owned document")
    if scenario == "link" and (len(links) != 1 or files or videos or audios or images):
        raise Wan3PrimeValidationError("Wan3 link mode requires one verified webpage")
    if scenario in {"text", "first_frame", "first_last"} and (videos or audios):
        raise Wan3PrimeValidationError("Selected Wan3 scenario rejects video/audio references")
    if payload["duration"] != -1 and video_seconds + payload["duration"] > 30:
        raise Wan3PrimeValidationError("Wan3 input video + output must be <=30 seconds")
    payload["wan_input_seconds"] = str(Decimal(str(video_seconds)))
    payload["wan_audio_seconds"] = str(Decimal(str(audio_seconds)))


def settled_wan_cost(payload: dict, output_seconds: float, reserved: str) -> str:
    """Calculate actual Wan cost using the frozen pre-charge rate and media info."""
    from bot.services.wan3_prime_lifecycle import _round_half_credit
    from bot.shared_accounts.wallet import amount_units, format_units

    try:
        input_seconds = Decimal(str(payload["wan_input_seconds"]))
        rate = Decimal(str(payload["wan_rate_snapshot"]))
        output = Decimal(str(output_seconds))
        locked = Decimal(str(reserved))
    except (ValueError, TypeError, InvalidOperation, KeyError) as exc:
        raise ValueError("Unverified Wan3 settlement snapshot") from exc
    if (not all(value.is_finite() for value in (input_seconds, rate, output, locked))
            or input_seconds < 0 or input_seconds > 15
            or rate <= 0 or locked <= 0
            or output < 1 or output > 30):
        raise ValueError("Impossible Wan3 settlement values")
    # The provider's output may be fractionally different from its quoted
    # duration; never charge for more than reserved even if KIE overshoots.
    calculated = Decimal(str(_round_half_credit(
        float(rate * (input_seconds + output)),
    )))
    if calculated <= 0:
        raise ValueError("Wan3 output rounded to zero credits")
    return format_units(min(amount_units(calculated), amount_units(locked)))


async def inspect_web_wan_output(
    task_id: str, asset_key: str, durable_url: str,
) -> float:
    """ffprobe only our own persisted task-specific S3 video; no remote URLs."""
    from bot.services.media_storage import materialize_upload

    if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
        raise ValueError("Unexpected task")
    if not re.fullmatch(r"[a-f0-9]{32}", asset_key):
        raise ValueError("Unexpected media asset key")
    parsed = urlsplit(durable_url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Untrusted settlement result URL")
    filename = parsed.path.rsplit("/", 1)[-1]
    expected = asset_key + "."
    if not filename.startswith(expected) or filename[len(expected):] not in {
        "mp4", "mov", "webm",
    } or not parsed.path.endswith("/web_results/" + task_id + "/" + filename):
        raise ValueError("Result is not the durable output for this task")
    relative = "web_results/" + task_id + "/" + filename
    stored = await asyncio.to_thread(materialize_upload, relative)
    if not stored:
        raise ValueError("Wan3 output is missing from S3")
    local = Path(stored)
    if not local.is_file() or local.is_symlink():
        raise ValueError("Wan3 output is not a materialized regular file")

    def inspect() -> float:
        try:
            completed = subprocess.run([
                "ffprobe", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", "mov,matroska,webm",
                "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(local),
            ], capture_output=True, text=True, timeout=12, check=False)
            record = json.loads(completed.stdout or "{}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise ValueError("Failed to inspect Wan3 result duration") from exc
        streams = record.get("streams")
        if (completed.returncode or not isinstance(streams, list)
                or not any(x.get("codec_type") == "video"
                           for x in streams if isinstance(x, dict))):
            raise ValueError("Wan3 result has no playable video stream")
        fmt = record.get("format") or {}
        try:
            seconds = float(fmt.get("duration"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Wan3 result has no measurable duration") from exc
        if not math.isfinite(seconds) or not 1 <= seconds <= 30:
            raise ValueError("Wan3 result duration exceeds validated bounds")
        return seconds

    return await asyncio.to_thread(inspect)
