"""Shared limits for video reference flows."""

from collections.abc import Iterable


VIDEO_REFERENCE_LIMITS = {
    "seedance_2": 3,
    "motion_control_v26": 1,
    "motion_control_v30": 1,
}

VIDEO_IMAGE_REFERENCE_LIMITS = {
    "seedance_2": 9,
    "v3_std": 9,
    "v3_pro": 9,
}

DEFAULT_VIDEO_REFERENCE_MODEL = "seedance_2"


def video_model_supports_reference_videos(model: str | None) -> bool:
    return (model or "") in VIDEO_REFERENCE_LIMITS


def get_max_video_references(model: str | None) -> int:
    return VIDEO_REFERENCE_LIMITS.get(model or "", 3)


def get_max_video_image_references(model: str | None) -> int:
    return VIDEO_IMAGE_REFERENCE_LIMITS.get(model or "", 9)


def choose_video_reference_model(model: str | None) -> str:
    if video_model_supports_reference_videos(model):
        return str(model)
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
