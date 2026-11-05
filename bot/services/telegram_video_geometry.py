"""Actual local video display geometry for Telegram result previews."""

import asyncio
import json
import logging
import subprocess

from aiogram.types import FSInputFile

from bot.services import media_input_utils

logger = logging.getLogger(__name__)


def video_preview_dimensions(path: str) -> tuple[int, int] | None:
    """Use the downloaded file's display geometry for Telegram's video preview.

    Neironych MP4 files may have valid 9:16 geometry that Telegram does not
    reliably infer on upload. A missing/broken ffprobe must not block delivery.
    """
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height,sample_aspect_ratio:stream_tags=rotate:stream_side_data=rotation",
                "-of", "json", path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode != 0:
            return None
        streams = json.loads(probe.stdout).get("streams") or []
        if not streams or not isinstance(streams[0], dict):
            return None
        stream = streams[0]
        width, height = int(stream["width"]), int(stream["height"])
        if not (0 < width <= 16384 and 0 < height <= 16384):
            return None

        sar = str(stream.get("sample_aspect_ratio") or "1:1")
        if ":" in sar and sar != "N/A":
            numerator, denominator = (int(part) for part in sar.split(":", 1))
            if numerator > 0 and denominator > 0:
                width = round(width * numerator / denominator)
        rotation = (stream.get("tags") or {}).get("rotate")
        if rotation is None:
            for side_data in stream.get("side_data_list") or []:
                if isinstance(side_data, dict) and "rotation" in side_data:
                    rotation = side_data["rotation"]
                    break
        if rotation is not None and int(float(rotation)) % 180 == 90:
            width, height = height, width
        if not (0 < width <= 16384 and 0 < height <= 16384):
            return None
        return width, height
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, subprocess.TimeoutExpired):
        return None



async def telegram_video_geometry(source: str | FSInputFile) -> dict[str, int]:
    """Probe local media only; remote URLs and Telegram file IDs stay untouched."""
    if isinstance(source, FSInputFile):
        path = str(source.path)
    elif isinstance(source, str):
        path = media_input_utils.resolve_local_upload_path(source)
    else:
        path = None
    if not path:
        return {}
    dimensions = await asyncio.to_thread(video_preview_dimensions, path)
    if dimensions is None:
        logger.warning("Telegram video geometry unavailable: source_kind=local")
        return {}
    width, height = dimensions
    logger.info("Telegram video preview geometry: width=%s height=%s", width, height)
    return {"width": width, "height": height}
