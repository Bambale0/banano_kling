"""Typed GenerationContext contract shared by every generation flow.

This module codifies the internal generation context described in
``docs/reference-system.md``:

    GenerationContext
      input_media
      reference_context (scene / identity / style)
      model_config
      privacy_policy

Reference roles are never guessed from the fact of an upload alone: every flow
must resolve explicit roles through the resolvers below and pass the validation
gate before a task is created, credits are reserved, or a provider request is
sent.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

import aiohttp
from PIL import Image, UnidentifiedImageError

from bot.services.media_input_utils import _resolve_local_upload_path

_MAX_REMOTE_PROBE_BYTES = 20 * 1024 * 1024
_REMOTE_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=4, sock_read=6)


class GenerationContextError(ValueError):
    """Raised when a generation context violates its reference contract."""


class ReferenceRole(str, Enum):
    SCENE = "scene"
    IDENTITY = "identity"
    STYLE = "style"


@dataclass(frozen=True)
class ReferenceImage:
    url: str
    role: ReferenceRole


@dataclass(frozen=True)
class ReferenceContext:
    scene: tuple[ReferenceImage, ...] = ()
    identity: tuple[ReferenceImage, ...] = ()
    style: tuple[ReferenceImage, ...] = ()

    @property
    def ordered(self) -> tuple[ReferenceImage, ...]:
        """Provider payload order: scene first, then identity, then style."""
        return self.scene + self.identity + self.style


@dataclass(frozen=True)
class ModelConfig:
    service: str
    provider_model: str = ""
    ratio: str = "1:1"
    quality: str = ""
    max_references: int = 0


@dataclass(frozen=True)
class PrivacyPolicy:
    """Privacy mode must be explicit; private flows fail closed without it."""

    private_recipe: bool = False
    hide_prompt: bool = False
    allow_prompt_actions: bool = True
    feed_prompt_visible: bool = True


@dataclass(frozen=True)
class GenerationContext:
    input_media: tuple[str, ...]
    reference_context: ReferenceContext
    model_config: ModelConfig
    privacy_policy: PrivacyPolicy
    notes: tuple[str, ...] = field(default=())


def _clean_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        raise GenerationContextError("Пустая ссылка на референс")
    return url


def _unique(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url in seen:
            raise GenerationContextError("Референсы не должны дублироваться")
        seen.add(url)
        result.append(url)
    return result


def _reference(url: str, role: ReferenceRole) -> ReferenceImage:
    return ReferenceImage(url=url, role=role)


def resolve_pinterest_reference_roles(urls: Sequence[str]) -> ReferenceContext:
    """Pinterest/Trend identity transfer: Image 1 = scene, Image 2+ = identity.

    There is no hidden "first upload = person" fallback: with fewer than one
    scene and one identity reference this resolver raises instead of guessing.
    """

    cleaned = _unique(_clean_url(url) for url in urls)
    if len(cleaned) < 2:
        raise GenerationContextError(
            "Нужны scene-референс и хотя бы одно identity-фото"
        )
    return ReferenceContext(
        scene=(_reference(cleaned[0], ReferenceRole.SCENE),),
        identity=tuple(
            _reference(url, ReferenceRole.IDENTITY) for url in cleaned[1:]
        ),
    )


def resolve_standard_reference_roles(
    urls: Sequence[str],
    *,
    extras_role: ReferenceRole = ReferenceRole.STYLE,
) -> ReferenceContext:
    """Ordinary I2I: Image 1+ are identity/style according to the chosen mode."""

    if extras_role not in {ReferenceRole.IDENTITY, ReferenceRole.STYLE}:
        raise GenerationContextError("Недопустимая роль дополнительных референсов")
    cleaned = _unique(_clean_url(url) for url in urls)
    if not cleaned:
        raise GenerationContextError("Нужно хотя бы одно фото")
    return ReferenceContext(
        identity=(
            _reference(cleaned[0], ReferenceRole.IDENTITY),
            *(
                _reference(url, extras_role)
                for url in cleaned[1:]
            ),
        )
    )


def resolve_text_to_image_context() -> ReferenceContext:
    """T2I has no references at all."""
    return ReferenceContext()


def build_generation_context(
    *,
    input_media: Sequence[str],
    reference_context: ReferenceContext,
    model_config: ModelConfig,
    privacy_policy: PrivacyPolicy,
) -> GenerationContext:
    return GenerationContext(
        input_media=tuple(_clean_url(item) for item in input_media),
        reference_context=reference_context,
        model_config=model_config,
        privacy_policy=privacy_policy,
    )


def validate_generation_context(context: GenerationContext) -> list[str]:
    """Return a list of gate violations; empty list means the gate is passed."""

    errors: list[str] = []
    refs = context.reference_context
    all_refs = refs.scene + refs.identity + refs.style

    urls = [ref.url for ref in all_refs]
    if len(set(urls)) != len(urls):
        errors.append("duplicate reference URL")

    if context.model_config.max_references and len(all_refs) > (
        context.model_config.max_references
    ):
        errors.append(
            f"provider supports at most {context.model_config.max_references} "
            f"references, got {len(all_refs)}"
        )

    policy = context.privacy_policy
    if policy.private_recipe and not policy.hide_prompt:
        errors.append("private recipe requires prompt hiding")

    for ref in all_refs:
        if not ref.url.startswith(("https://", "http://", "/uploads/")):
            errors.append(f"invalid reference URL scheme: {ref.url}")
            break

    return errors


def ensure_generation_context_valid(context: GenerationContext) -> None:
    errors = validate_generation_context(context)
    if errors:
        raise GenerationContextError("; ".join(errors))


def ensure_pinterest_reference_gate(
    urls: Sequence[str],
    *,
    privacy_policy: PrivacyPolicy | None = None,
) -> ReferenceContext:
    """Validation gate for Pinterest runs, executed before any side effect.

    Checks: scene exists, identity exists, roles valid, privacy mode enabled.
    Provider count support is checked by ``validate_generation_context`` once
    the model config is known.
    """

    reference_context = resolve_pinterest_reference_roles(urls)
    if not reference_context.scene or not reference_context.identity:
        raise GenerationContextError(
            "Нужны scene-референс и хотя бы одно identity-фото"
        )
    policy = privacy_policy or PrivacyPolicy()
    if not policy.private_recipe or not policy.hide_prompt:
        raise GenerationContextError(
            "Приватный режим задачи не активирован"
        )
    return reference_context


# ---------------------------------------------------------------------------
# Aspect ratio helpers (scene-matched output ratio for Pinterest flows).
# ---------------------------------------------------------------------------

_RATIO_SEPARATOR = ":"


def parse_ratio(value: str) -> float | None:
    parts = str(value or "").strip().split(_RATIO_SEPARATOR)
    if len(parts) != 2:
        return None
    try:
        width = float(parts[0])
        height = float(parts[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def pick_closest_ratio(width: int, height: int, supported: Sequence[str]) -> str | None:
    """Return the supported ratio closest to the given image dimensions."""

    if width <= 0 or height <= 0:
        return None
    target = width / height
    best: tuple[float, str] | None = None
    for candidate in supported:
        value = parse_ratio(candidate)
        if value is None:
            continue
        delta = abs(value - target) / target
        if best is None or delta < best[0]:
            best = (delta, candidate)
    return best[1] if best else None


async def probe_image_size(url: str) -> tuple[int, int] | None:
    """Return (width, height) for own local uploads or remote image URLs.

    Never raises: any failure returns ``None`` so callers keep the configured
    ratio instead of blocking generation because of a failed probe.
    """

    local_path = _resolve_local_upload_path(str(url or ""))
    if local_path:
        try:
            with Image.open(local_path) as image:
                return int(image.width), int(image.height)
        except (OSError, UnidentifiedImageError, ValueError):
            return None

    parsed_ok = str(url or "").startswith(("http://", "https://"))
    if not parsed_ok:
        return None
    try:
        async with aiohttp.ClientSession(timeout=_REMOTE_PROBE_TIMEOUT) as session:
            async with session.get(str(url)) as response:
                if response.status >= 400:
                    return None
                content_type = str(response.headers.get("Content-Type") or "")
                if not content_type.lower().startswith("image/"):
                    return None
                raw = await response.content.read(_MAX_REMOTE_PROBE_BYTES + 1)
                if len(raw) > _MAX_REMOTE_PROBE_BYTES:
                    return None
        with Image.open(io.BytesIO(raw)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - probing is best-effort by design
        return None


__all__ = [
    "GenerationContext",
    "GenerationContextError",
    "ModelConfig",
    "PrivacyPolicy",
    "ReferenceContext",
    "ReferenceImage",
    "ReferenceRole",
    "build_generation_context",
    "ensure_generation_context_valid",
    "ensure_pinterest_reference_gate",
    "parse_ratio",
    "pick_closest_ratio",
    "probe_image_size",
    "resolve_pinterest_reference_roles",
    "resolve_standard_reference_roles",
    "resolve_text_to_image_context",
    "validate_generation_context",
]
