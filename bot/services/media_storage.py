"""Canonical storage for public `/uploads/` references and generated media.

The interface deliberately uses paths relative to ``static/uploads``. This
keeps database URLs and provider payloads stable while allowing the durable
adapter to move from the host filesystem to an S3-compatible object store.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

from bot.config import config

logger = logging.getLogger(__name__)

LOCAL_UPLOAD_ROOT = Path("static/uploads")
_CACHE_MARKER_SUFFIX = ".s3-cache"


class MediaStorageConfigurationError(RuntimeError):
    """Raised when S3 mode is enabled without a complete safe configuration."""


@dataclass(frozen=True)
class S3Settings:
    endpoint: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    key_prefix: str
    public_base_url: str
    force_path_style: bool
    keep_local_cache: bool
    cache_ttl_seconds: int
    cache_cleanup_interval_seconds: int
    connect_timeout_seconds: int
    read_timeout_seconds: int
    max_attempts: int
    presign_ttl_seconds: int

    @classmethod
    def from_config(cls) -> S3Settings:
        values = {
            "MEDIA_S3_ENDPOINT": str(config.MEDIA_S3_ENDPOINT or "").strip().rstrip("/"),
            "MEDIA_S3_REGION": str(config.MEDIA_S3_REGION or "").strip(),
            "MEDIA_S3_BUCKET": str(config.MEDIA_S3_BUCKET or "").strip(),
            "MEDIA_S3_ACCESS_KEY_ID": str(config.MEDIA_S3_ACCESS_KEY_ID or "").strip(),
            "MEDIA_S3_SECRET_ACCESS_KEY": str(config.MEDIA_S3_SECRET_ACCESS_KEY or "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise MediaStorageConfigurationError(
                "S3 media storage is missing: " + ", ".join(missing)
            )

        public_base = str(config.MEDIA_S3_PUBLIC_BASE_URL or config.static_base_url).strip().rstrip("/")
        if not public_base.startswith("https://"):
            raise MediaStorageConfigurationError(
                "MEDIA_S3_PUBLIC_BASE_URL (or STATIC_BASE_URL) must use HTTPS"
            )
        key_prefix = str(config.MEDIA_S3_KEY_PREFIX or "").strip().strip("/")
        if key_prefix:
            _validate_relative_path(key_prefix)
        if key_prefix != "uploads":
            raise MediaStorageConfigurationError(
                "MEDIA_S3_KEY_PREFIX must be 'uploads' to preserve public URL contracts"
            )
        connect_timeout = int(config.MEDIA_S3_CONNECT_TIMEOUT_SECONDS)
        read_timeout = int(config.MEDIA_S3_READ_TIMEOUT_SECONDS)
        attempts = int(config.MEDIA_S3_MAX_ATTEMPTS)
        presign_ttl = int(config.MEDIA_S3_PRESIGN_TTL_SECONDS)
        cache_ttl = int(config.MEDIA_S3_CACHE_TTL_SECONDS)
        cache_cleanup_interval = int(
            config.MEDIA_S3_CACHE_CLEANUP_INTERVAL_SECONDS
        )
        if not 1 <= connect_timeout <= 120:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_CONNECT_TIMEOUT_SECONDS must be between 1 and 120"
            )
        if not 1 <= read_timeout <= 900:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_READ_TIMEOUT_SECONDS must be between 1 and 900"
            )
        if not 1 <= attempts <= 10:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_MAX_ATTEMPTS must be between 1 and 10"
            )
        if not 60 <= presign_ttl <= 900:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_PRESIGN_TTL_SECONDS must be between 60 and 900"
            )
        if not 60 <= cache_ttl <= 7 * 24 * 3600:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_CACHE_TTL_SECONDS must be between 60 and 604800"
            )
        if not 60 <= cache_cleanup_interval <= 24 * 3600:
            raise MediaStorageConfigurationError(
                "MEDIA_S3_CACHE_CLEANUP_INTERVAL_SECONDS must be between 60 and 86400"
            )
        return cls(
            endpoint=values["MEDIA_S3_ENDPOINT"],
            region=values["MEDIA_S3_REGION"],
            bucket=values["MEDIA_S3_BUCKET"],
            access_key_id=values["MEDIA_S3_ACCESS_KEY_ID"],
            secret_access_key=values["MEDIA_S3_SECRET_ACCESS_KEY"],
            key_prefix=key_prefix,
            public_base_url=public_base,
            force_path_style=bool(config.MEDIA_S3_FORCE_PATH_STYLE),
            keep_local_cache=bool(config.MEDIA_S3_KEEP_LOCAL_CACHE),
            cache_ttl_seconds=cache_ttl,
            cache_cleanup_interval_seconds=cache_cleanup_interval,
            connect_timeout_seconds=connect_timeout,
            read_timeout_seconds=read_timeout,
            max_attempts=attempts,
            presign_ttl_seconds=presign_ttl,
        )


_client_lock = threading.Lock()
_cached_client = None
_cached_settings: S3Settings | None = None


def _backend() -> str:
    backend = str(config.MEDIA_STORAGE_BACKEND or "local").strip().lower()
    if backend not in {"local", "s3"}:
        raise MediaStorageConfigurationError(
            "MEDIA_STORAGE_BACKEND must be 'local' or 's3'"
        )
    return backend


def is_s3_enabled() -> bool:
    return _backend() == "s3"


def validate_media_storage_configuration() -> None:
    """Validate the selected adapter without making a network request."""
    if is_s3_enabled():
        settings = S3Settings.from_config()
        logger.info(
            "Media storage configured: backend=s3 endpoint=%s region=%s bucket=%s prefix=%s keep_local_cache=%s",
            settings.endpoint,
            settings.region,
            settings.bucket,
            settings.key_prefix,
            settings.keep_local_cache,
        )
    else:
        logger.info("Media storage configured: backend=local")


def _validate_relative_path(relative_path: str) -> str:
    value = str(relative_path or "").strip().replace("\\", "/")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "?" in value
        or "#" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Invalid media path")
    normalized = path.as_posix()
    if normalized != value:
        raise ValueError("Invalid media path")
    return normalized


def local_upload_path(relative_path: str) -> Path:
    relative = _validate_relative_path(relative_path)
    root = LOCAL_UPLOAD_ROOT.resolve()
    candidate = (LOCAL_UPLOAD_ROOT / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Invalid media path") from exc
    return LOCAL_UPLOAD_ROOT / relative


def object_key(relative_path: str, settings: S3Settings | None = None) -> str:
    relative = _validate_relative_path(relative_path)
    settings = settings or S3Settings.from_config()
    return f"{settings.key_prefix}/{relative}" if settings.key_prefix else relative


def public_upload_url(relative_path: str) -> str:
    relative = _validate_relative_path(relative_path)
    if is_s3_enabled():
        settings = S3Settings.from_config()
        return f"{settings.public_base_url}/{object_key(relative, settings)}"
    return f"{config.static_base_url.rstrip('/')}/uploads/{relative}"


def presigned_upload_url(relative_path: str, *, method: str = "GET") -> str:
    """Sign for the actual HTTP method; S3 rejects HEAD with a GET signature."""
    relative = _validate_relative_path(relative_path)
    http_method = method.upper()
    if http_method not in {"GET", "HEAD"}:
        raise ValueError("Unsupported media request method")
    if not is_s3_enabled():
        return public_upload_url(relative)
    settings = S3Settings.from_config()
    return str(
        _s3_client(settings).generate_presigned_url(
            "head_object" if http_method == "HEAD" else "get_object",
            Params={
                "Bucket": settings.bucket,
                "Key": object_key(relative, settings),
            },
            ExpiresIn=settings.presign_ttl_seconds,
        )
    )


def _build_s3_client(settings: S3Settings):
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as exc:  # pragma: no cover - deployment dependency gate
        raise MediaStorageConfigurationError(
            "boto3 is required when MEDIA_STORAGE_BACKEND=s3"
        ) from exc

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.read_timeout_seconds,
            retries={"max_attempts": settings.max_attempts, "mode": "standard"},
            s3={
                "addressing_style": (
                    "path" if settings.force_path_style else "virtual"
                )
            },
        ),
    )


def _s3_client(settings: S3Settings):
    global _cached_client, _cached_settings
    with _client_lock:
        if _cached_client is None or _cached_settings != settings:
            _cached_client = _build_s3_client(settings)
            _cached_settings = settings
        return _cached_client


def reset_media_storage_for_tests() -> None:
    global _cached_client, _cached_settings
    with _client_lock:
        _cached_client = None
        _cached_settings = None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    finally:
        temporary.unlink(missing_ok=True)


def _cache_marker(path: Path) -> Path:
    return path.with_name(f".{path.name}{_CACHE_MARKER_SUFFIX}")


def _mark_materialized_cache(path: Path) -> None:
    marker = _cache_marker(path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


def _mark_retained_local_copy(path: Path) -> None:
    _cache_marker(path).unlink(missing_ok=True)


def _content_args(
    relative_path: str,
    *,
    content_type: str | None,
    cache_control: str | None,
) -> dict[str, str]:
    args: dict[str, str] = {}
    detected = content_type or mimetypes.guess_type(relative_path)[0]
    if detected:
        args["ContentType"] = detected
    if cache_control:
        args["CacheControl"] = cache_control
    return args


def file_sha256(path: str | os.PathLike[str]) -> str:
    """Hash a file in bounded memory, including large multipart upload sources."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def persist_upload_bytes(
    relative_path: str,
    data: bytes,
    *,
    content_type: str | None = None,
    cache_control: str | None = None,
) -> str:
    relative = _validate_relative_path(relative_path)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("Media payload must be non-empty bytes")
    payload = bytes(data)
    started = time.monotonic()

    if not is_s3_enabled():
        _atomic_write(local_upload_path(relative), payload)
        logger.info(
            "Media storage put: backend=local key=%s bytes=%s duration_ms=%s",
            relative,
            len(payload),
            round((time.monotonic() - started) * 1000),
        )
        return public_upload_url(relative)

    settings = S3Settings.from_config()
    key = object_key(relative, settings)
    client = _s3_client(settings)
    request = {
        "Bucket": settings.bucket,
        "Key": key,
        "Body": payload,
        "Metadata": {"sha256": hashlib.sha256(payload).hexdigest()},
        **_content_args(
            relative, content_type=content_type, cache_control=cache_control
        ),
    }
    try:
        client.put_object(**request)
    except Exception:
        logger.exception(
            "Media storage put failed: backend=s3 key=%s bytes=%s",
            key,
            len(payload),
        )
        raise
    if settings.keep_local_cache:
        try:
            _atomic_write(local_upload_path(relative), payload)
            _mark_retained_local_copy(local_upload_path(relative))
        except OSError:
            logger.warning("Media cache write failed after durable S3 put: key=%s", key)
    logger.info(
        "Media storage put: backend=s3 key=%s bytes=%s duration_ms=%s",
        key,
        len(payload),
        round((time.monotonic() - started) * 1000),
    )
    return public_upload_url(relative)


def persist_upload_file(
    relative_path: str,
    source_path: str | os.PathLike[str],
    *,
    content_type: str | None = None,
    cache_control: str | None = None,
    retain_local_copy: bool = False,
) -> str:
    relative = _validate_relative_path(relative_path)
    source = Path(source_path)
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    if not is_s3_enabled():
        destination = local_upload_path(relative)
        if source.resolve() != destination.resolve():
            _atomic_write(destination, source.read_bytes())
        return public_upload_url(relative)

    settings = S3Settings.from_config()
    key = object_key(relative, settings)
    started = time.monotonic()
    extra = _content_args(
        relative, content_type=content_type, cache_control=cache_control
    )
    source_digest = file_sha256(source)
    extra["Metadata"] = {"sha256": source_digest}
    # Reused reference PNGs are normalized on every submission. Checking the
    # durable remote digest avoids re-uploading several megabytes per request.
    # A matching byte count without a trusted digest is NOT sufficient.
    remote_unchanged = False
    try:
        remote_unchanged = remote_upload_fingerprint(relative) == (
            source.stat().st_size, source_digest
        )
    except Exception as exc:  # noqa: BLE001 - unknown S3 HEAD failure; PUT is fallback
        logger.warning(
            "Media storage remote fingerprint unavailable: key=%s error=%s; uploading",
            key, type(exc).__name__,
        )
    if not remote_unchanged:
        try:
            _s3_client(settings).upload_file(
                str(source), settings.bucket, key, ExtraArgs=extra or None
            )
        except Exception:
            logger.exception(
                "Media storage upload failed: backend=s3 key=%s bytes=%s",
                key,
                source.stat().st_size,
            )
            raise
    if file_sha256(source) != source_digest:
        raise OSError("Media source changed while verifying S3 content")
    local_target = local_upload_path(relative)
    try:
        if source.resolve() == local_target.resolve():
            if settings.keep_local_cache or retain_local_copy:
                _mark_retained_local_copy(source)
            else:
                _mark_materialized_cache(source)
    except OSError:
        logger.warning("Media cache marker update failed: key=%s", key)
    if remote_unchanged:
        logger.debug("Media storage upload skipped (unchanged remote): key=%s", key)
    else:
        logger.info(
            "Media storage upload: backend=s3 key=%s bytes=%s duration_ms=%s",
            key,
            source.stat().st_size,
            round((time.monotonic() - started) * 1000),
        )
    return public_upload_url(relative)


def materialize_upload(relative_path: str) -> str | None:
    relative = _validate_relative_path(relative_path)
    destination = local_upload_path(relative)
    if destination.is_file() and not destination.is_symlink():
        marker = _cache_marker(destination)
        if marker.is_file():
            marker.touch(exist_ok=True)
        return str(destination)
    if not is_s3_enabled():
        return None

    settings = S3Settings.from_config()
    key = object_key(relative, settings)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{uuid4().hex}.tmp"
    )
    started = time.monotonic()
    try:
        _s3_client(settings).download_file(settings.bucket, key, str(temporary))
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise OSError("Downloaded media object is empty")
        os.replace(temporary, destination)
        os.chmod(destination, 0o644)
        _mark_materialized_cache(destination)
    except Exception as exc:  # noqa: BLE001 - download boundary
        temporary.unlink(missing_ok=True)
        logger.warning(
            "Media storage materialize failed: key=%s error=%s",
            key,
            type(exc).__name__,
        )
        return None
    logger.info(
        "Media storage materialized: key=%s bytes=%s duration_ms=%s",
        key,
        destination.stat().st_size,
        round((time.monotonic() - started) * 1000),
    )
    return str(destination)


def upload_exists(relative_path: str) -> bool:
    relative = _validate_relative_path(relative_path)
    if not is_s3_enabled():
        return local_upload_path(relative).is_file()
    settings = S3Settings.from_config()
    try:
        _s3_client(settings).head_object(
            Bucket=settings.bucket, Key=object_key(relative, settings)
        )
        return True
    except Exception as exc:  # noqa: BLE001 - S3 SDK exception boundary
        if _is_missing_object_error(exc):
            return False
        logger.warning(
            "Media storage existence check failed: key=%s error=%s",
            object_key(relative, settings),
            type(exc).__name__,
        )
        return False


def _is_missing_object_error(exc: Exception) -> bool:
    if isinstance(exc, KeyError):  # deterministic fake clients in unit tests
        return True
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error") or {}
    metadata = response.get("ResponseMetadata") or {}
    code = str(error.get("Code") or "").strip()
    status = metadata.get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404


def remote_upload_fingerprint(relative_path: str) -> tuple[int, str | None] | None:
    """Return remote size and our SHA-256 metadata; absent hashes are unverified."""
    relative = _validate_relative_path(relative_path)
    if not is_s3_enabled():
        path = local_upload_path(relative)
        return (path.stat().st_size, file_sha256(path)) if path.is_file() else None
    settings = S3Settings.from_config()
    try:
        response = _s3_client(settings).head_object(
            Bucket=settings.bucket, Key=object_key(relative, settings)
        )
    except Exception as exc:
        if _is_missing_object_error(exc):
            return None
        logger.exception(
            "Media storage fingerprint check failed: backend=s3 key=%s",
            object_key(relative, settings),
        )
        raise
    size = int(response.get("ContentLength", -1))
    if size < 0:
        return None
    digest = str((response.get("Metadata") or {}).get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = None
    return (size, digest)


def remote_upload_size(relative_path: str) -> int | None:
    """Return the canonical object's size, or None when it is absent."""
    fingerprint = remote_upload_fingerprint(relative_path)
    return fingerprint[0] if fingerprint else None


def delete_upload(relative_path: str) -> None:
    relative = _validate_relative_path(relative_path)
    local_path = local_upload_path(relative)
    if not is_s3_enabled():
        local_path.unlink(missing_ok=True)
        _cache_marker(local_path).unlink(missing_ok=True)
        return
    settings = S3Settings.from_config()
    key = object_key(relative, settings)
    # Remote-first: a failed S3 delete must not lose the last local copy.
    _s3_client(settings).delete_object(Bucket=settings.bucket, Key=key)
    local_path.unlink(missing_ok=True)
    _cache_marker(local_path).unlink(missing_ok=True)
    logger.info("Media storage delete: backend=s3 key=%s", key)


def cleanup_materialized_cache(*, max_age_seconds: int | None = None) -> dict[str, int]:
    """Remove only files explicitly materialized from S3, never source copies."""
    if not LOCAL_UPLOAD_ROOT.exists():
        return {"removed_count": 0, "removed_bytes": 0}
    ttl = int(
        S3Settings.from_config().cache_ttl_seconds
        if max_age_seconds is None and is_s3_enabled()
        else (
            config.MEDIA_S3_CACHE_TTL_SECONDS
            if max_age_seconds is None
            else max_age_seconds
        )
    )
    if ttl < 60 and max_age_seconds is None:
        raise MediaStorageConfigurationError(
            "MEDIA_S3_CACHE_TTL_SECONDS must be at least 60"
        )
    cutoff = time.time() - max(0, ttl)
    removed_count = 0
    removed_bytes = 0
    for marker in LOCAL_UPLOAD_ROOT.rglob(f"*{_CACHE_MARKER_SUFFIX}"):
        if not marker.is_file() or marker.is_symlink():
            continue
        try:
            if marker.stat().st_mtime > cutoff:
                continue
            name = marker.name
            if not name.startswith(".") or not name.endswith(_CACHE_MARKER_SUFFIX):
                continue
            target_name = name[1 : -len(_CACHE_MARKER_SUFFIX)]
            target = marker.with_name(target_name)
            target.resolve().relative_to(LOCAL_UPLOAD_ROOT.resolve())
            size = target.stat().st_size if target.is_file() else 0
            target.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            removed_count += 1
            removed_bytes += size
        except (OSError, ValueError):
            logger.exception("Failed to clean materialized S3 cache marker: %s", marker)
    if removed_count:
        logger.info(
            "Media S3 cache cleanup: removed_count=%s removed_bytes=%s",
            removed_count,
            removed_bytes,
        )
    return {"removed_count": removed_count, "removed_bytes": removed_bytes}
