"""Server-measured effective video inputs; no client duration or price authority.

Call after provider input assembly/authorization. The injected seams keep tests
independent of application bootstrap. Production remote reads use the existing
SSRF-safe, redirect-checked downloader, never ffprobe against a remote URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

MAX_VIDEO_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MeasuredVideoReference:
    url: str
    seconds: float
    sha256: str


@dataclass(frozen=True, slots=True)
class VideoReferenceMeasurement:
    references: tuple[MeasuredVideoReference, ...]
    input_seconds: float
    fingerprint: str

    def to_dict(self):
        return asdict(self)


def _file_hash(path: Path) -> str:
    size = path.stat().st_size
    if not 0 < size <= MAX_VIDEO_BYTES:
        raise ValueError("Видео-референс должен быть непустым и не превышать 200 MB")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _probe_seconds(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", "stream=codec_type,duration:format=duration",
        "-of", "json", str(path), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("Не удалось измерить видео. Загрузите файл заново")
    try:
        metadata = json.loads(output)
        streams = [s for s in metadata.get("streams", []) if s.get("codec_type") == "video"]
        if not streams:
            raise ValueError("В референсе нет видеопотока")
        duration = streams[0].get("duration")
        if duration in (None, "N/A"):
            duration = metadata.get("format", {}).get("duration")
        return float(duration)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось измерить длительность видео") from exc


async def measure_video_references(
    sources, *, resolve_local=None, fetch_remote=None, probe=None,
    allowed_root: Path | None = None,
) -> VideoReferenceMeasurement:
    """Measure the ordered effective refs, de-duplicating exact provider URLs.

    Authorization remains the caller's responsibility. Unknown opaque media
    cannot yield a quote. Local paths must stay within the managed upload root.
    """
    if resolve_local is None:
        from bot.services.media_input_utils import resolve_local_upload_path
        resolve_local = resolve_local_upload_path
    probe = probe or _probe_seconds
    root = (allowed_root or Path("static/uploads")).resolve()
    normalized = list(dict.fromkeys(str(source).strip() for source in (sources or [])))
    if len(normalized) > 10 or any(not source for source in normalized):
        raise ValueError("Некорректный список видео-референсов")
    references = []
    with TemporaryDirectory(prefix="video-quote-") as temporary:
        for index, source in enumerate(normalized):
            local = resolve_local(source)
            if local:
                path = Path(local).resolve()
                if root not in path.parents or not path.is_file():
                    raise ValueError("Видео-референс недоступен в хранилище")
            else:
                parsed = urlsplit(source)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("Нужно загрузить видео для точного расчёта цены")
                if fetch_remote is None:
                    from bot.services.wan3_prime_storage import fetch_public_asset
                    fetch_remote = fetch_public_asset
                path = Path(temporary) / f"reference-{index}.video"
                await fetch_remote(source, destination=path, max_bytes=MAX_VIDEO_BYTES)
            before = await asyncio.to_thread(_file_hash, path)
            seconds = float(await probe(path))
            after = await asyncio.to_thread(_file_hash, path)
            if before != after:
                raise ValueError("Видео изменилось во время расчёта. Рассчитайте цену ещё раз")
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("Не удалось измерить положительную длительность видео")
            references.append(MeasuredVideoReference(source, seconds, before))
    total = math.fsum(item.seconds for item in references)
    if not math.isfinite(total):
        raise ValueError("Некорректная суммарная длительность видео")
    encoded = json.dumps([asdict(item) for item in references], sort_keys=True, separators=(",", ":"))
    return VideoReferenceMeasurement(tuple(references), total, hashlib.sha256(encoded.encode()).hexdigest())
