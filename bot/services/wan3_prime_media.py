from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

WAN3_MODEL_KEY = "wan_3_prime"
WAN3_PROVIDER_MODEL = "wan/3-0-video-prime"

MAX_PROMPT_LENGTH = 20_000
MAX_SEED = 2_147_483_647
ALLOWED_SCENARIOS = {"text", "first_frame", "first_last", "reference", "edit", "file", "link"}
ALLOWED_RESOLUTIONS = {"480P", "720P", "1080P"}
ALLOWED_RATIOS = {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"}
REFERENCE_LIMITS = {
    "reference_image_urls": 10,
    "reference_video_urls": 5,
    "reference_audio_urls": 5,
    "reference_file_urls": 1,
    "reference_link_urls": 1,
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
AUDIO_EXTENSIONS = {".wav", ".mp3"}
DOCUMENT_EXTENSIONS = {
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".pdf",
    ".txt",
    ".key",
    ".pages",
    ".numbers",
    ".md",
}


class Wan3PrimeValidationError(ValueError):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


class MediaProbe(Protocol):
    async def probe_url(self, url: str, *, kind: str) -> MediaInfo:
        ...

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        ...


@dataclass(frozen=True)
class MediaInfo:
    kind: str
    sha256: str | None = None
    url: str | None = None
    path: str | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    extension: str | None = None
    has_alpha: bool = False
    pages: int | None = None
    upstream_page_validation_required: bool = False


@dataclass(frozen=True)
class Wan3PrimeRecipe:
    scenario: str
    prompt: str
    first_frame_url: str | None = None
    last_frame_url: str | None = None
    reference_image_urls: list[str] = field(default_factory=list)
    reference_video_urls: list[str] = field(default_factory=list)
    reference_audio_urls: list[str] = field(default_factory=list)
    reference_file_urls: list[str] = field(default_factory=list)
    reference_link_urls: list[str] = field(default_factory=list)
    resolution: str = "1080P"
    aspect_ratio: str = "adaptive"
    duration: int = 5
    audio: bool = True
    seed: int | None = None
    nsfw_checker: bool = False
    # Internal-only frozen provider input. Never populated from client JSON.
    prepared_input: dict[str, Any] = field(default_factory=dict, repr=False)
    media: dict[str, list[MediaInfo]] = field(default_factory=dict)
    input_video_seconds: float = 0.0
    input_audio_seconds: float = 0.0
    upstream_page_validation_required: bool = False

    def safe_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["media"] = {
            key: [
                {
                    "kind": item.get("kind"),
                    "sha256": item.get("sha256"),
                    "size_bytes": item.get("size_bytes"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "duration_seconds": item.get("duration_seconds"),
                    "extension": item.get("extension"),
                    "upstream_page_validation_required": item.get(
                        "upstream_page_validation_required"
                    ),
                }
                for item in values
            ]
            for key, values in data["media"].items()
        }
        return data

    def raw_provider_args(self) -> dict[str, Any]:
        args: dict[str, Any] = {
            "prompt": self.prompt,
            "scenario": self.scenario,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "resolution": self.resolution,
            "first_frame_url": self.first_frame_url,
            "last_frame_url": self.last_frame_url,
            "reference_image_urls": list(self.reference_image_urls),
            "reference_video_urls": list(self.reference_video_urls),
            "reference_audio_urls": list(self.reference_audio_urls),
            "reference_file_urls": list(self.reference_file_urls),
            "reference_link_urls": list(self.reference_link_urls),
            "audio": self.audio,
            "seed": self.seed,
            "nsfw_checker": self.nsfw_checker,
        }
        return args

    def fingerprint(self) -> str:
        payload = self.safe_summary()
        # Idempotency describes the original user operation, not later admin template edits.
        payload.pop("prepared_input", None)
        payload["provider_args"] = self.raw_provider_args()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NullMediaProbe:
    async def probe_url(self, url: str, *, kind: str) -> MediaInfo:
        return MediaInfo(kind=kind, url=url, extension=Path(urlparse(url).path).suffix.lower())

    async def probe_file(self, path: str, *, kind: str) -> MediaInfo:
        return MediaInfo(kind=kind, path=path, extension=Path(path).suffix.lower())


def normalize_wan3_body(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise Wan3PrimeValidationError("Request body must be an object")

    aliases = {
        "v_model": "model",
        "generation_type": "scenario",
        "v_duration": "duration",
        "v_ratio": "aspect_ratio",
        "wan_resolution": "resolution",
        "wan_seed": "seed",
        "wan_audio": "audio",
        "wan_nsfw_checker": "nsfw_checker",
        "wan_first_frame_url": "first_frame_url",
        "wan_last_frame_url": "last_frame_url",
        "reference_images": "reference_image_urls",
        "v_reference_videos": "reference_video_urls",
        "audio_references": "reference_audio_urls",
        "wan_reference_file_urls": "reference_file_urls",
        "wan_reference_link_urls": "reference_link_urls",
        "v_duration": "duration",
        "v_ratio": "aspect_ratio",
    }
    out = dict(body)
    if "v_model" in out and "model" not in out:
        out["model"] = out["v_model"]
    for source, target in aliases.items():
        if source in out and target not in out:
            out[target] = out[source]
    if "aspect_ratio" not in out and "ratio" in out:
        out["aspect_ratio"] = out["ratio"]
    if "scenario" in out:
        scenario = out["scenario"]
        if scenario == "imgtxt":
            out["scenario"] = "first_frame"
        elif scenario == "video":
            out["scenario"] = "reference"
    return out


def _strict_int(value: Any, *, field_name: str, minimum: int, maximum: int, allow_auto: bool = False) -> int:
    if isinstance(value, bool):
        raise Wan3PrimeValidationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        result = int(value.strip())
    else:
        raise Wan3PrimeValidationError(f"{field_name} must be an integer")
    if allow_auto and result == -1:
        return result
    if not minimum <= result <= maximum:
        if allow_auto:
            raise Wan3PrimeValidationError(f"{field_name} must be -1 or {minimum}-{maximum}")
        raise Wan3PrimeValidationError(f"{field_name} must be {minimum}-{maximum}")
    return result


def _strict_bool(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise Wan3PrimeValidationError(f"{field_name} must be a boolean")
    return value


def _array(value: Any, *, field_name: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Wan3PrimeValidationError(f"{field_name} must be an array")
    if len(value) > limit:
        raise Wan3PrimeValidationError(f"{field_name} accepts at most {limit} items")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise Wan3PrimeValidationError(f"{field_name}[{index}] must be a non-empty URL")
        out.append(item.strip())
    return out


def _optional_url(value: Any, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip():
        raise Wan3PrimeValidationError(f"{field_name} must be a non-empty URL")
    return value.strip()


def _host_is_private(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_private or ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        pass
    return False


async def assert_public_url(url: str, *, resolve_dns: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise Wan3PrimeValidationError("URL must use http or https")
    if not parsed.hostname:
        raise Wan3PrimeValidationError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise Wan3PrimeValidationError("Credential URLs are not allowed")
    if _host_is_private(parsed.hostname):
        raise Wan3PrimeValidationError("Local or private network URLs are not allowed")
    if not resolve_dns:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise Wan3PrimeValidationError("URL hostname cannot be resolved") from exc
    for info in infos:
        address = info[4][0]
        if _host_is_private(address):
            raise Wan3PrimeValidationError("URL resolves to a local or private network address")


def _extension(url_or_path: str) -> str:
    return Path(urlparse(url_or_path).path or url_or_path).suffix.lower()


def _check_dimensions(info: MediaInfo, *, min_px: int, max_px: int) -> None:
    if info.width is None or info.height is None:
        return
    if not min_px <= int(info.width) <= max_px or not min_px <= int(info.height) <= max_px:
        raise Wan3PrimeValidationError(f"{info.kind} dimensions must be {min_px}-{max_px}px")
    ratio = max(info.width, info.height) / max(1, min(info.width, info.height))
    if ratio > 8:
        raise Wan3PrimeValidationError(f"{info.kind} aspect ratio must be <= 8:1")


def _check_size(info: MediaInfo, *, max_bytes: int) -> None:
    if info.size_bytes is not None and info.size_bytes > max_bytes:
        raise Wan3PrimeValidationError(f"{info.kind} file is too large")


def _check_duration(info: MediaInfo, *, kind: str) -> float:
    if info.duration_seconds is None:
        raise Wan3PrimeValidationError(f"{kind} duration must be measured server-side before launch")
    duration = float(info.duration_seconds)
    if not math.isfinite(duration) or not 1 <= duration <= 15:
        raise Wan3PrimeValidationError(f"{kind} duration must be 1-15 seconds")
    return duration


async def validate_wan3_recipe(body: dict[str, Any], probe: MediaProbe | None = None) -> Wan3PrimeRecipe:
    probe = probe or NullMediaProbe()
    data = normalize_wan3_body(body)
    model = str(data.get("model") or data.get("v_model") or WAN3_MODEL_KEY).strip()
    if model and model not in {WAN3_MODEL_KEY, WAN3_PROVIDER_MODEL, "wan3_prime"}:
        raise Wan3PrimeValidationError("model must be wan_3_prime")

    scenario = str(data.get("scenario") or "text").strip().lower()
    if scenario not in ALLOWED_SCENARIOS:
        raise Wan3PrimeValidationError("Unsupported Wan 3.0 scenario")

    prompt_raw = data.get("prompt", "")
    if not isinstance(prompt_raw, str):
        raise Wan3PrimeValidationError("prompt must be a string")
    prompt = prompt_raw.strip()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise Wan3PrimeValidationError("prompt exceeds 20000 characters")

    first_frame = _optional_url(data.get("first_frame_url"), field_name="first_frame_url")
    last_frame = _optional_url(data.get("last_frame_url"), field_name="last_frame_url")
    images = _array(data.get("reference_image_urls"), field_name="reference_image_urls", limit=10)
    videos = _array(data.get("reference_video_urls"), field_name="reference_video_urls", limit=5)
    audios = _array(data.get("reference_audio_urls"), field_name="reference_audio_urls", limit=5)
    files = _array(data.get("reference_file_urls"), field_name="reference_file_urls", limit=1)
    links = _array(data.get("reference_link_urls"), field_name="reference_link_urls", limit=1)

    if scenario in {"text", "edit"} and not prompt:
        raise Wan3PrimeValidationError("prompt is required for this mode")
    if last_frame and not first_frame:
        raise Wan3PrimeValidationError("last_frame_url requires first_frame_url")
    if (first_frame or last_frame) and (images or videos or audios or files or links):
        raise Wan3PrimeValidationError("first/last frames cannot be combined with reference_* inputs")
    if files and links:
        raise Wan3PrimeValidationError("reference_file_urls and reference_link_urls are mutually exclusive")
    if scenario == "edit":
        if not videos:
            raise Wan3PrimeValidationError("edit mode requires Video1 as reference_video_urls[0]")
        if first_frame or last_frame:
            raise Wan3PrimeValidationError("edit mode uses Video1, not first/last frames")
    expected_inputs = {
        "text": not any([first_frame, last_frame, images, videos, audios, files, links]),
        "first_frame": bool(first_frame and not last_frame),
        "first_last": bool(first_frame and last_frame),
        "reference": bool(images or videos or audios or files or links),
        "edit": bool(videos),
        "file": bool(files),
        "link": bool(links),
    }
    if not expected_inputs[scenario]:
        raise Wan3PrimeValidationError("explicit scenario does not match supplied inputs", status=409)

    resolution = str(data.get("resolution") or "1080P").strip().upper()
    if resolution not in ALLOWED_RESOLUTIONS:
        raise Wan3PrimeValidationError("resolution must be 480P, 720P or 1080P")
    aspect_ratio = str(data.get("aspect_ratio") or "adaptive").strip()
    if aspect_ratio.lower() == "adaptive":
        aspect_ratio = "adaptive"
    if aspect_ratio not in ALLOWED_RATIOS:
        raise Wan3PrimeValidationError("aspect_ratio is not supported")
    duration = _strict_int(data.get("duration", 5), field_name="duration", minimum=2, maximum=30, allow_auto=True)
    seed = data.get("seed")
    normalized_seed = None if seed in (None, "") else _strict_int(seed, field_name="seed", minimum=0, maximum=MAX_SEED)
    audio = _strict_bool(data.get("audio"), field_name="audio", default=True)
    nsfw_checker = _strict_bool(data.get("nsfw_checker"), field_name="nsfw_checker", default=False)

    media: dict[str, list[MediaInfo]] = {}

    async def add_url(field: str, url: str, kind: str) -> MediaInfo:
        await assert_public_url(url)
        info = await probe.probe_url(url, kind=kind)
        ext = info.extension or _extension(url)
        info = MediaInfo(**{**asdict(info), "extension": ext, "url": info.url or url})
        media.setdefault(field, []).append(info)
        return info

    for field, url in (("first_frame_url", first_frame), ("last_frame_url", last_frame)):
        if url:
            info = await add_url(field, url, "image")
            if (info.extension or "").lower() not in IMAGE_EXTENSIONS:
                raise Wan3PrimeValidationError(f"{field} must be JPEG/PNG/BMP/WEBP")
            if info.has_alpha:
                raise Wan3PrimeValidationError("PNG transparency is not supported")
            _check_size(info, max_bytes=20 * 1024 * 1024)
            _check_dimensions(info, min_px=240, max_px=8000)

    for url in images:
        info = await add_url("reference_image_urls", url, "image")
        if (info.extension or "").lower() not in IMAGE_EXTENSIONS:
            raise Wan3PrimeValidationError("reference images must be JPEG/PNG/BMP/WEBP")
        if info.has_alpha:
            raise Wan3PrimeValidationError("PNG transparency is not supported")
        _check_size(info, max_bytes=20 * 1024 * 1024)
        _check_dimensions(info, min_px=240, max_px=8000)

    video_seconds = 0.0
    for url in videos:
        info = await add_url("reference_video_urls", url, "video")
        if (info.extension or "").lower() not in VIDEO_EXTENSIONS:
            raise Wan3PrimeValidationError("reference videos must be MP4 or MOV")
        _check_size(info, max_bytes=100 * 1024 * 1024)
        _check_dimensions(info, min_px=240, max_px=4096)
        video_seconds += _check_duration(info, kind="video")
    if video_seconds > 15:
        raise Wan3PrimeValidationError("combined reference video duration must be <= 15 seconds")

    audio_seconds = 0.0
    for url in audios:
        info = await add_url("reference_audio_urls", url, "audio")
        if (info.extension or "").lower() not in AUDIO_EXTENSIONS:
            raise Wan3PrimeValidationError("reference audio must be WAV or MP3")
        _check_size(info, max_bytes=15 * 1024 * 1024)
        audio_seconds += _check_duration(info, kind="audio")
    if audio_seconds > 15:
        raise Wan3PrimeValidationError("combined reference audio duration must be <= 15 seconds")

    upstream_page_validation_required = False
    for url in files:
        info = await add_url("reference_file_urls", url, "file")
        if (info.extension or "").lower() not in DOCUMENT_EXTENSIONS:
            raise Wan3PrimeValidationError("reference file type is not supported")
        _check_size(info, max_bytes=100 * 1024 * 1024)
        if info.pages is not None and info.pages > 50:
            raise Wan3PrimeValidationError("reference file must be <= 50 pages")
        if info.pages is None and (info.extension or "").lower() in DOCUMENT_EXTENSIONS:
            upstream_page_validation_required = True
    for url in links:
        await add_url("reference_link_urls", url, "link")

    if duration != -1 and video_seconds + duration > 30:
        raise Wan3PrimeValidationError("reference video duration plus output duration must be <= 30 seconds")

    return Wan3PrimeRecipe(
        scenario=scenario,
        prompt=prompt,
        first_frame_url=first_frame,
        last_frame_url=last_frame,
        reference_image_urls=images,
        reference_video_urls=videos,
        reference_audio_urls=audios,
        reference_file_urls=files,
        reference_link_urls=links,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        duration=duration,
        audio=audio,
        seed=normalized_seed,
        nsfw_checker=nsfw_checker,
        media=media,
        input_video_seconds=video_seconds,
        input_audio_seconds=audio_seconds,
        upstream_page_validation_required=upstream_page_validation_required,
    )


def canonical_child_path(root: str | os.PathLike[str], relative: str) -> Path:
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if base != target and base not in target.parents:
        raise Wan3PrimeValidationError("Path escapes Wan 3.0 upload storage")
    return target
