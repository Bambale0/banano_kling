"""Private reference recipes for Seedance 2.0/2.5 curated trends.

A recipe never stores the creator identity image. At run time the repeater's
single uploaded identity becomes ``@Image1`` and durable template assets fill
``@Image2..N``. Video and audio bindings keep their own independent numbering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from bot.services.seedance_reference_binding import (
    canonicalize_seedance_reference_tags,
    missing_seedance_reference_tags,
)

SUPPORTED_MODELS = frozenset({"seedance_2", "seedance_2_5"})
REFERENCE_CONTRACT = "seedance_identity_first"
REFERENCE_PLAN_VERSION = 1
PROMPT_MARKER = "SEEDANCE_TREND_IDENTITY_CONTRACT_V1"

_TAG_RE = re.compile(
    r"@\s*(?P<kind>image|img|video|audio)\s*[_-]?\s*(?P<index>\d+)(?!\w)",
    re.IGNORECASE,
)


class SeedanceTrendRecipeError(ValueError):
    """Raised when a Seedance trend recipe cannot be compiled safely."""


@dataclass(frozen=True)
class SeedanceReferenceSnapshot:
    images: tuple[str, ...]
    videos: tuple[str, ...]
    audios: tuple[str, ...]


@dataclass(frozen=True)
class SeedanceTrendAsset:
    media_type: str
    position: int
    source_position: int
    source_url: str
    label: str
    role: str = "fixed_hidden"


@dataclass(frozen=True)
class CompiledSeedanceTrendRecipe:
    model: str
    prompt: str
    assets: tuple[SeedanceTrendAsset, ...]
    identity_source_position: int

    @property
    def image_assets(self) -> tuple[SeedanceTrendAsset, ...]:
        return tuple(asset for asset in self.assets if asset.media_type == "image")

    @property
    def video_assets(self) -> tuple[SeedanceTrendAsset, ...]:
        return tuple(asset for asset in self.assets if asset.media_type == "video")

    @property
    def audio_assets(self) -> tuple[SeedanceTrendAsset, ...]:
        return tuple(asset for asset in self.assets if asset.media_type == "audio")


def _clean_urls(values: Iterable[Any] | None) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return tuple(cleaned)


def _list_value(source: Mapping[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        raw = source.get(key)
        if isinstance(raw, list):
            return _clean_urls(raw)
        if isinstance(raw, str) and raw.strip():
            return _clean_urls([raw])
    return ()


def extract_seedance_reference_snapshot(
    model: str,
    request_data: Mapping[str, Any] | None,
) -> SeedanceReferenceSnapshot:
    """Return the logical media order used by an existing Seedance task."""

    normalized_model = str(model or "").strip()
    if normalized_model not in SUPPORTED_MODELS:
        raise SeedanceTrendRecipeError("Only Seedance 2.0/2.5 tasks can become this trend type")

    data = request_data if isinstance(request_data, Mapping) else {}
    images: list[str] = []

    def append_image(value: Any) -> None:
        candidate = str(value or "").strip()
        if candidate and candidate not in images:
            images.append(candidate)

    # Seedance 2.0 Mini App/Telegram snapshots keep the primary photo separate.
    append_image(data.get("v_image_url"))

    scenario = str(data.get("seedance25_scenario") or "").strip().lower()
    if normalized_model == "seedance_2_5" and scenario in {"first_frame", "first_last"}:
        append_image(data.get("first_frame_url"))
        append_image(data.get("last_frame_url"))

    for value in _list_value(
        data,
        "source_reference_images",
        "reference_images",
        "reference_image_urls",
    ):
        append_image(value)

    videos = _list_value(
        data,
        "v_reference_videos",
        "reference_video_urls",
        "video_references",
    )
    audios = _list_value(
        data,
        "reference_audios",
        "seedance25_reference_audio_urls",
        "v_reference_audio",
        "reference_audio_urls",
        "audio_references",
    )
    return SeedanceReferenceSnapshot(tuple(images), videos, audios)


def _normalize_indices(
    values: Sequence[int] | None,
    *,
    upper: int,
    label: str,
) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw in values or []:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise SeedanceTrendRecipeError(f"Invalid {label} reference index") from exc
        if value < 1 or value > upper:
            raise SeedanceTrendRecipeError(
                f"{label} reference index {value} is outside 1..{upper}"
            )
        if value in normalized:
            raise SeedanceTrendRecipeError(f"Duplicate {label} reference index {value}")
        normalized.append(value)
    return tuple(normalized)


def _canonical_tag(kind: str, index: int) -> str:
    title = "Image" if kind in {"image", "img"} else kind.title()
    return f"@{title}{index}"


def _remap_prompt(
    prompt: str,
    *,
    source_counts: Mapping[str, int],
    mappings: Mapping[str, Mapping[int, int]],
) -> str:
    canonical = canonicalize_seedance_reference_tags(
        str(prompt or "").strip(),
        image_count=int(source_counts.get("image", 0)),
        video_count=int(source_counts.get("video", 0)),
        audio_count=int(source_counts.get("audio", 0)),
    )

    def replace(match: re.Match[str]) -> str:
        kind = match.group("kind").lower()
        kind = "image" if kind == "img" else kind
        old_index = int(match.group("index"))
        new_index = mappings.get(kind, {}).get(old_index)
        return _canonical_tag(kind, new_index) if new_index is not None else _canonical_tag(kind, old_index)

    return _TAG_RE.sub(replace, canonical)


def _mentioned_tags(prompt: str) -> set[str]:
    tags: set[str] = set()
    for match in _TAG_RE.finditer(prompt):
        kind = match.group("kind").lower()
        kind = "image" if kind == "img" else kind
        tags.add(_canonical_tag(kind, int(match.group("index"))))
    return tags


def compile_seedance_trend_recipe(
    *,
    prompt: str,
    model: str,
    source_images: Sequence[str],
    source_videos: Sequence[str],
    source_audios: Sequence[str],
    identity_image_index: int,
    fixed_image_indices: Sequence[int],
    fixed_video_indices: Sequence[int],
    fixed_audio_indices: Sequence[int],
) -> CompiledSeedanceTrendRecipe:
    """Compile a creator task into a private identity-substitution recipe."""

    normalized_model = str(model or "").strip()
    if normalized_model not in SUPPORTED_MODELS:
        raise SeedanceTrendRecipeError("Only Seedance 2.0/2.5 are supported")

    images = _clean_urls(source_images)
    videos = _clean_urls(source_videos)
    audios = _clean_urls(source_audios)
    if not images:
        raise SeedanceTrendRecipeError("The source task has no image references")

    try:
        identity_position = int(identity_image_index)
    except (TypeError, ValueError) as exc:
        raise SeedanceTrendRecipeError("Invalid identity image index") from exc
    if identity_position < 1 or identity_position > len(images):
        raise SeedanceTrendRecipeError("Identity image index is outside the source images")

    fixed_images = _normalize_indices(
        fixed_image_indices,
        upper=len(images),
        label="image",
    )
    fixed_videos = _normalize_indices(
        fixed_video_indices,
        upper=len(videos),
        label="video",
    )
    fixed_audios = _normalize_indices(
        fixed_audio_indices,
        upper=len(audios),
        label="audio",
    )
    if identity_position in fixed_images:
        raise SeedanceTrendRecipeError("The creator identity cannot also be a fixed asset")
    if not fixed_images and not fixed_videos and not fixed_audios:
        raise SeedanceTrendRecipeError("Keep at least one hidden template reference")

    image_mapping: dict[int, int] = {identity_position: 1}
    assets: list[SeedanceTrendAsset] = []
    for target_position, source_position in enumerate(fixed_images, start=2):
        image_mapping[source_position] = target_position
        assets.append(
            SeedanceTrendAsset(
                media_type="image",
                position=target_position,
                source_position=source_position,
                source_url=images[source_position - 1],
                label=f"@Image{target_position}",
            )
        )

    video_mapping: dict[int, int] = {}
    for target_position, source_position in enumerate(fixed_videos, start=1):
        video_mapping[source_position] = target_position
        assets.append(
            SeedanceTrendAsset(
                media_type="video",
                position=target_position,
                source_position=source_position,
                source_url=videos[source_position - 1],
                label=f"@Video{target_position}",
            )
        )

    audio_mapping: dict[int, int] = {}
    for target_position, source_position in enumerate(fixed_audios, start=1):
        audio_mapping[source_position] = target_position
        assets.append(
            SeedanceTrendAsset(
                media_type="audio",
                position=target_position,
                source_position=source_position,
                source_url=audios[source_position - 1],
                label=f"@Audio{target_position}",
            )
        )

    remapped_prompt = _remap_prompt(
        prompt,
        source_counts={"image": len(images), "video": len(videos), "audio": len(audios)},
        mappings={
            "image": image_mapping,
            "video": video_mapping,
            "audio": audio_mapping,
        },
    )
    target_counts = {
        "image": 1 + len(fixed_images),
        "video": len(fixed_videos),
        "audio": len(fixed_audios),
    }
    missing = missing_seedance_reference_tags(
        remapped_prompt,
        image_count=target_counts["image"],
        video_count=target_counts["video"],
        audio_count=target_counts["audio"],
    )
    if missing:
        raise SeedanceTrendRecipeError(
            "Prompt references media excluded from the trend: " + ", ".join(missing)
        )

    mentioned = _mentioned_tags(remapped_prompt)
    required = {"@Image1", *(asset.label for asset in assets)}
    unmentioned = sorted(required - mentioned)
    if unmentioned:
        raise SeedanceTrendRecipeError(
            "Prompt must reference every retained media slot: " + ", ".join(unmentioned)
        )

    guard = (
        f"\n\n{PROMPT_MARKER}\n"
        "REFERENCE IDENTITY RULES:\n"
        "- @Image1 is the only identity/person source and is uploaded by the current user.\n"
        "- @Image2 and later image references are private fixed template assets. "
        "Use only the clothing, accessories, objects, style, scene, or other non-identity "
        "details explicitly requested from them.\n"
        "- Never copy, preserve, blend, or infer a person's face or identity from fixed "
        "template images, videos, or audio. The final person must remain recognizable "
        "as @Image1.\n"
        "- Keep every @Image, @Video, and @Audio binding exactly as numbered above."
    )
    compiled_prompt = remapped_prompt if PROMPT_MARKER in remapped_prompt else remapped_prompt + guard
    return CompiledSeedanceTrendRecipe(
        model=normalized_model,
        prompt=compiled_prompt,
        assets=tuple(assets),
        identity_source_position=identity_position,
    )


def assemble_seedance_trend_inputs(
    user_reference_urls: Sequence[str],
    stored_assets: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Build provider arrays without exposing or accepting private asset URLs."""

    user_images = list(_clean_urls(user_reference_urls))
    if len(user_images) != 1:
        raise SeedanceTrendRecipeError("This trend requires exactly one user identity image")

    grouped: dict[str, list[tuple[int, str]]] = {"image": [], "video": [], "audio": []}
    for raw_asset in stored_assets:
        media_type = str(raw_asset.get("media_type") or "").strip().lower()
        if media_type not in grouped:
            raise SeedanceTrendRecipeError(f"Unsupported trend asset type: {media_type}")
        try:
            position = int(raw_asset.get("position"))
        except (TypeError, ValueError) as exc:
            raise SeedanceTrendRecipeError("Trend asset has an invalid position") from exc
        file_url = str(raw_asset.get("file_url") or "").strip()
        if position < 1 or not file_url:
            raise SeedanceTrendRecipeError("Trend asset is incomplete")
        grouped[media_type].append((position, file_url))

    def ordered(kind: str, *, start: int) -> list[str]:
        pairs = sorted(grouped[kind])
        positions = [position for position, _ in pairs]
        expected = list(range(start, start + len(pairs)))
        if positions != expected:
            raise SeedanceTrendRecipeError(
                f"Trend {kind} asset positions are not contiguous: {positions}"
            )
        urls = [url for _, url in pairs]
        if len(set(urls)) != len(urls):
            raise SeedanceTrendRecipeError(f"Trend {kind} assets contain duplicates")
        return urls

    fixed_images = ordered("image", start=2)
    videos = ordered("video", start=1)
    audios = ordered("audio", start=1)
    return [user_images[0], *fixed_images], videos, audios
