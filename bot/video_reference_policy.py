"""Shared limits and normalization for video reference flows."""

from collections.abc import Iterable

from bot.model_capabilities import (
    get_video_capability,
    max_image_references,
    max_video_references,
    normalize_video_model_key,
    supports_video_reference,
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


def normalize_reference_urls(
    urls: Iterable[str] | None,
    *,
    max_count: int,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls or []:
        value = str(url or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
        if len(normalized) >= max_count:
            break
    return normalized
