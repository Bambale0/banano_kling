"""Private reference recipes for Seedance 2.0/2.5 curated trends.

A recipe never stores the creator identity image. At run time the repeater's
single uploaded identity becomes ``@Image1`` and durable template assets fill
``@Image2..N``. Video and audio bindings keep their own independent numbering.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from bot.services.seedance_reference_binding import (
    canonicalize_seedance_reference_tags,
    missing_seedance_reference_tags,
)

SUPPORTED_MODELS = frozenset({"seedance_2", "seedance_2_5"})
REFERENCE_CONTRACT = "seedance_identity_first"
REFERENCE_PLAN_VERSION = 2
PROMPT_MARKER = "SEEDANCE_TREND_IDENTITY_CONTRACT_V1"
_PROMPT_LIMITS = {"seedance_2": 20_000, "seedance_2_5": 30_000}
MAX_USER_REFERENCE_SLOTS = 12

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
class SeedanceUserReferenceSlot:
    media_type: str
    position: int
    source_position: int
    label: str


@dataclass(frozen=True)
class CompiledSeedanceTrendRecipe:
    model: str
    prompt: str
    assets: tuple[SeedanceTrendAsset, ...]
    identity_source_position: int
    user_slots: tuple[SeedanceUserReferenceSlot, ...] = ()

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
        raise SeedanceTrendRecipeError(
            "Only Seedance 2.0/2.5 tasks can become this trend type"
        )

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
    return tuple(sorted(normalized))


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
        return (
            _canonical_tag(kind, new_index)
            if new_index is not None
            else _canonical_tag(kind, old_index)
        )

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
    replaceable_image_indices: Sequence[int] = (),
    replaceable_video_indices: Sequence[int] = (),
    replaceable_audio_indices: Sequence[int] = (),
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
        raise SeedanceTrendRecipeError(
            "Identity image index is outside the source images"
        )

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
    replaceable_images = _normalize_indices(
        replaceable_image_indices,
        upper=len(images),
        label="replaceable image",
    )
    replaceable_videos = _normalize_indices(
        replaceable_video_indices,
        upper=len(videos),
        label="replaceable video",
    )
    replaceable_audios = _normalize_indices(
        replaceable_audio_indices,
        upper=len(audios),
        label="replaceable audio",
    )
    if identity_position in fixed_images:
        raise SeedanceTrendRecipeError(
            "The creator identity cannot also be a fixed asset"
        )
    if identity_position in replaceable_images:
        raise SeedanceTrendRecipeError(
            "The creator identity is already the primary replaceable image"
        )
    for kind, fixed, replaceable in (
        ("image", fixed_images, replaceable_images),
        ("video", fixed_videos, replaceable_videos),
        ("audio", fixed_audios, replaceable_audios),
    ):
        overlap = sorted(set(fixed) & set(replaceable))
        if overlap:
            raise SeedanceTrendRecipeError(
                f"A {kind} reference cannot be both fixed and replaceable: {overlap}"
            )
    # The primary replaceable identity slot is sufficient for a one-photo trend.
    # Additional fixed or replaceable references are optional.

    image_mapping: dict[int, int] = {identity_position: 1}
    assets: list[SeedanceTrendAsset] = []
    user_slots: list[SeedanceUserReferenceSlot] = [
        SeedanceUserReferenceSlot(
            media_type="image",
            position=1,
            source_position=identity_position,
            label="ВАШЕ ЛИЦО",
        )
    ]
    included_images = sorted((*fixed_images, *replaceable_images))
    for target_position, source_position in enumerate(included_images, start=2):
        image_mapping[source_position] = target_position
        if source_position in replaceable_images:
            user_slots.append(
                SeedanceUserReferenceSlot(
                    media_type="image",
                    position=target_position,
                    source_position=source_position,
                    label=f"ВАШЕ ФОТО · @Image{target_position}",
                )
            )
        else:
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
    included_videos = sorted((*fixed_videos, *replaceable_videos))
    for target_position, source_position in enumerate(included_videos, start=1):
        video_mapping[source_position] = target_position
        if source_position in replaceable_videos:
            user_slots.append(
                SeedanceUserReferenceSlot(
                    media_type="video",
                    position=target_position,
                    source_position=source_position,
                    label=f"ВАШЕ ВИДЕО · @Video{target_position}",
                )
            )
        else:
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
    included_audios = sorted((*fixed_audios, *replaceable_audios))
    for target_position, source_position in enumerate(included_audios, start=1):
        audio_mapping[source_position] = target_position
        if source_position in replaceable_audios:
            user_slots.append(
                SeedanceUserReferenceSlot(
                    media_type="audio",
                    position=target_position,
                    source_position=source_position,
                    label=f"ВАШЕ АУДИО · @Audio{target_position}",
                )
            )
        else:
            assets.append(
                SeedanceTrendAsset(
                    media_type="audio",
                    position=target_position,
                    source_position=source_position,
                    source_url=audios[source_position - 1],
                    label=f"@Audio{target_position}",
                )
            )

    source_counts = {"image": len(images), "video": len(videos), "audio": len(audios)}
    mappings = {
        "image": image_mapping,
        "video": video_mapping,
        "audio": audio_mapping,
    }
    source_prompt = str(prompt or "").strip()
    marker_offset = source_prompt.find(f"\n\n{PROMPT_MARKER}")
    if marker_offset >= 0:
        source_prompt = source_prompt[:marker_offset].rstrip()
    if not source_prompt:
        raise SeedanceTrendRecipeError("The source task prompt is empty")
    if len(user_slots) > MAX_USER_REFERENCE_SLOTS:
        raise SeedanceTrendRecipeError(
            f"A trend can have at most {MAX_USER_REFERENCE_SLOTS} replaceable references"
        )

    canonical_source_prompt = canonicalize_seedance_reference_tags(
        source_prompt,
        image_count=source_counts["image"],
        video_count=source_counts["video"],
        audio_count=source_counts["audio"],
    )
    excluded_mentions: list[str] = []
    for match in _TAG_RE.finditer(canonical_source_prompt):
        kind = match.group("kind").lower()
        kind = "image" if kind == "img" else kind
        source_index = int(match.group("index"))
        if (
            1 <= source_index <= source_counts[kind]
            and source_index not in mappings[kind]
        ):
            tag = _canonical_tag(kind, source_index)
            if tag not in excluded_mentions:
                excluded_mentions.append(tag)
    if excluded_mentions:
        raise SeedanceTrendRecipeError(
            "Prompt references media excluded from the trend: "
            + ", ".join(excluded_mentions)
        )

    remapped_prompt = _remap_prompt(
        canonical_source_prompt,
        source_counts=source_counts,
        mappings=mappings,
    )
    target_counts = {
        "image": 1 + len(included_images),
        "video": len(included_videos),
        "audio": len(included_audios),
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

    required = {
        "@Image1",
        *(asset.label for asset in assets),
        *(_canonical_tag(slot.media_type, slot.position) for slot in user_slots),
    }

    guard_lines = [
        f"{PROMPT_MARKER}",
        "REFERENCE IDENTITY RULES:",
        "- @Image1 is the only identity/person source and is uploaded by the current user.",
    ]
    if fixed_images:
        image_slots = ", ".join(
            asset.label for asset in assets if asset.media_type == "image"
        )
        guard_lines.append(
            f"- {image_slots} are private fixed template images. Use only the clothing, "
            "accessories, objects, style, scene, or other non-identity details explicitly "
            "requested from them."
        )
    if fixed_videos:
        video_slots = ", ".join(
            asset.label for asset in assets if asset.media_type == "video"
        )
        guard_lines.append(
            f"- {video_slots} are private fixed template videos. Use only their requested "
            "motion, timing, scene, or non-identity details."
        )
    if fixed_audios:
        audio_slots = ", ".join(
            asset.label for asset in assets if asset.media_type == "audio"
        )
        guard_lines.append(
            f"- {audio_slots} are private fixed template audio references. Use only their "
            "requested sound or timing details."
        )
    replaceable_non_identity = [
        slot
        for slot in user_slots
        if not (slot.media_type == "image" and slot.position == 1)
    ]
    if replaceable_non_identity:
        slot_labels = ", ".join(
            _canonical_tag(slot.media_type, slot.position)
            for slot in replaceable_non_identity
        )
        guard_lines.append(
            f"- {slot_labels} are uploaded by the current user and replace the corresponding template references."
        )
    guard_lines.extend(
        [
            (
                "- Never copy, preserve, blend, or infer a person's face or identity from fixed "
                "template images, videos, or audio. The final person must remain recognizable "
                "as @Image1."
            ),
            "- Keep every numbered media binding exactly as assigned above.",
        ]
    )
    guard = "\n\n" + "\n".join(guard_lines)
    compiled_prompt = (
        remapped_prompt if PROMPT_MARKER in remapped_prompt else remapped_prompt + guard
    )
    unmentioned = sorted(required - _mentioned_tags(compiled_prompt))
    if unmentioned:
        raise SeedanceTrendRecipeError(
            "Compiled prompt is missing retained media bindings: "
            + ", ".join(unmentioned)
        )

    prompt_limit = _PROMPT_LIMITS[normalized_model]
    if len(compiled_prompt) > prompt_limit:
        raise SeedanceTrendRecipeError(
            f"Compiled {normalized_model} trend prompt exceeds {prompt_limit} characters"
        )
    return CompiledSeedanceTrendRecipe(
        model=normalized_model,
        prompt=compiled_prompt,
        assets=tuple(assets),
        identity_source_position=identity_position,
        user_slots=tuple(user_slots),
    )


def assemble_seedance_trend_slot_inputs(
    submitted_inputs: Sequence[Mapping[str, Any]],
    configured_slots: Sequence[Mapping[str, Any]],
    stored_assets: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Assemble typed v2 inputs in exact provider positions."""

    allowed_types = {"image", "video", "audio"}

    def keyed(
        values: Sequence[Mapping[str, Any]], *, url_key: str
    ) -> dict[tuple[str, int], str]:
        result: dict[tuple[str, int], str] = {}
        seen_urls: set[str] = set()
        for value in values:
            media_type = str(value.get("media_type") or "").strip().lower()
            try:
                position = int(value.get("position"))
            except (TypeError, ValueError) as exc:
                raise SeedanceTrendRecipeError(
                    "Trend reference slot has an invalid position"
                ) from exc
            url = str(value.get(url_key) or "").strip()
            key = (media_type, position)
            if (
                media_type not in allowed_types
                or position < 1
                or not url
                or key in result
                or url in seen_urls
            ):
                raise SeedanceTrendRecipeError(
                    "Trend reference slot is incomplete or duplicated"
                )
            result[key] = url
            seen_urls.add(url)
        return result

    expected: set[tuple[str, int]] = set()
    for slot in configured_slots:
        media_type = str(slot.get("media_type") or "").strip().lower()
        try:
            position = int(slot.get("position"))
        except (TypeError, ValueError) as exc:
            raise SeedanceTrendRecipeError(
                "Configured trend slot has an invalid position"
            ) from exc
        key = (media_type, position)
        if media_type not in allowed_types or position < 1 or key in expected:
            raise SeedanceTrendRecipeError("Configured trend slots are invalid")
        expected.add(key)

    submitted = keyed(submitted_inputs, url_key="url")
    if set(submitted) != expected:
        raise SeedanceTrendRecipeError(
            "Submitted references must exactly match the configured trend slots"
        )
    fixed = keyed(stored_assets, url_key="file_url")
    if set(fixed) & expected:
        raise SeedanceTrendRecipeError(
            "A trend slot cannot be both fixed and replaceable"
        )
    if set(fixed.values()) & set(submitted.values()):
        raise SeedanceTrendRecipeError("Trend reference URLs must be unique")

    combined = {**fixed, **submitted}
    output: dict[str, list[str]] = {"image": [], "video": [], "audio": []}
    for media_type in ("image", "video", "audio"):
        pairs = sorted(
            (position, url)
            for (kind, position), url in combined.items()
            if kind == media_type
        )
        positions = [position for position, _url in pairs]
        if positions != list(range(1, len(pairs) + 1)):
            raise SeedanceTrendRecipeError(
                f"Trend {media_type} reference positions are not contiguous: {positions}"
            )
        output[media_type] = [url for _position, url in pairs]
    return output["image"], output["video"], output["audio"]


def assemble_seedance_trend_inputs(
    user_reference_urls: Sequence[str],
    stored_assets: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Build provider arrays without exposing or accepting private asset URLs."""

    user_images = list(_clean_urls(user_reference_urls))
    if len(user_images) != 1:
        raise SeedanceTrendRecipeError(
            "This trend requires exactly one user identity image"
        )

    grouped: dict[str, list[tuple[int, str]]] = {"image": [], "video": [], "audio": []}
    for raw_asset in stored_assets:
        media_type = str(raw_asset.get("media_type") or "").strip().lower()
        if media_type not in grouped:
            raise SeedanceTrendRecipeError(
                f"Unsupported trend asset type: {media_type}"
            )
        try:
            position = int(raw_asset.get("position"))
        except (TypeError, ValueError) as exc:
            raise SeedanceTrendRecipeError(
                "Trend asset has an invalid position"
            ) from exc
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
