"""Shared limits and normalization for video reference flows."""

import asyncio
import json
import math
import subprocess
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from bot.model_capabilities import (
    get_video_capability,
    max_image_references,
    max_video_references,
    normalize_video_model_key,
    supports_video_reference,
)
from bot.services.media_input_utils import (
    canonicalize_local_upload_url,
    resolve_local_upload_path,
)

DEFAULT_VIDEO_REFERENCE_MODEL = "seedance_2"
def video_model_supports_reference_videos(model: str | None) -> bool:
    return supports_video_reference(model)


def get_max_video_references(model: str | None) -> int:
    capability = get_video_capability(model)
    if capability is None:
        return 0
    return max_video_references(model)


def get_max_video_image_references(model: str | None) -> int:
    capability = get_video_capability(model)
    if capability is None:
        return 0
    return max_image_references(model)


def get_max_audio_references(model: str | None) -> int:
    capability = get_video_capability(model)
    if capability is None:
        return 0
    return int(capability.max_reference_audio or 0)


def get_video_reference_capabilities(model: str | None) -> dict[str, object]:
    normalized = normalize_video_model_key(model)
    capability = get_video_capability(normalized)
    return {
        "model": normalized,
        "supports_video": bool(capability and capability.supports_reference_videos),
        "max_videos": capability.max_reference_videos if capability else 0,
        "max_images": capability.max_reference_images if capability else 0,
    }


def choose_video_reference_model(model: str | None) -> str:
    normalized = normalize_video_model_key(model)
    if video_model_supports_reference_videos(normalized):
        return normalized
    return DEFAULT_VIDEO_REFERENCE_MODEL


@lru_cache(maxsize=256)
def _probe_local_video_seconds(path: str, size: int, mtime_ns: int) -> float:
    """Probe a checked local upload, never an untrusted provider URL."""
    # The stat tuple invalidates this cache after a file changes.
    del size, mtime_ns
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,duration", "-of", "json", path],
            capture_output=True, text=True, timeout=12, check=True,
        )
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams") or []
        candidates = [
            item.get("duration") for item in streams
            if item.get("codec_type") == "video"
        ]
        candidates.append((metadata.get("format") or {}).get("duration"))
        for raw in candidates:
            try:
                seconds = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(seconds) and seconds > 0:
                return seconds
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось измерить длительность видео-референса; загрузите его заново") from exc
    raise ValueError("Не удалось измерить длительность видео-референса; загрузите его заново")


def _local_video_duration(source: str) -> float:
    local = resolve_local_upload_path(source)
    if not local:
        raise ValueError("Видео-референс недоступен для проверки секунд; загрузите видео заново")
    root = (Path.cwd() / "static" / "uploads").resolve()
    path = Path(local).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"} or not path.is_file():
        raise ValueError("Видео-референс недоступен для проверки секунд; загрузите видео заново")
    stat = path.stat()
    if not 0 < stat.st_size <= 200 * 1024 * 1024:
        raise ValueError("Видео-референс слишком большой либо пустой; загрузите его заново")
    return _probe_local_video_seconds(str(path), stat.st_size, stat.st_mtime_ns)


async def measure_video_reference_seconds(video_references: Iterable[str] | None) -> float:
    """Sum every server-verified attached video; never guess from URL count."""
    urls = [str(url).strip() for url in video_references or [] if str(url).strip()]
    if not urls:
        return 0.0
    # Offload ffprobe from the asyncio event loop, while keeping network access
    # prohibited and the number of probes bounded by provider capabilities.
    if len(urls) > 30:
        raise ValueError("Слишком много видео-референсов для расчёта стоимости")
    durations = await asyncio.gather(*(asyncio.to_thread(_local_video_duration, url) for url in urls))
    total = sum(durations)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Не удалось измерить длительность видео-референсов")
    return total


def apply_video_reference_cost(
    model: str | None,
    base_cost: float,
    video_references: Iterable[str] | None,
    *,
    output_seconds: float | None = None,
    reference_seconds: float | None = None,
) -> float:
    """Base video charge + measured input seconds at the SAME retail rate.

    No presence-only ×2. A missing measurement fails closed: displaying a
    guessed reference price before a paid launch is not safe.
    """
    urls = [str(url).strip() for url in video_references or [] if str(url).strip()]
    if not urls:
        return float(base_cost)
    # Wan, Motion and Genjutsu already include measured input seconds in
    # their own quote/settlement lifecycles. Applying a second surcharge here
    # would double-bill the reference.
    if normalize_video_model_key(model) in {
        "wan_3", "wan_3_prime", "motion_control_v26",
        "motion_control_v30", "motion_control", "genjutsu",
    }:
        return float(base_cost)
    if not supports_video_reference(model):
        raise ValueError("Выбранная модель не принимает видеореференсы")
    if output_seconds is None or reference_seconds is None:
        raise ValueError("Длительность видео-референсов ещё не проверена")
    output, source, base = float(output_seconds), float(reference_seconds), float(base_cost)
    if not all(math.isfinite(value) for value in (output, source, base)) or output <= 0 or source <= 0 or base < 0:
        raise ValueError("Некорректная длительность либо стоимость видеореференсов")
    return base * (output + source) / output


def normalize_reference_urls(
    urls: Iterable[str] | None,
    *,
    max_count: int,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls or []:
        value = str(url or "").strip()
        if not value:
            continue
        value = canonicalize_local_upload_url(value)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
        if len(normalized) >= max_count:
            break
    return normalized
