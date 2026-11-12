from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from bot.config import config


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.put_calls: list[dict] = []
        self.deleted: list[tuple[str, str]] = []
        self.presign_operations: list[str] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        key = (kwargs["Bucket"], kwargs["Key"])
        self.objects[key] = bytes(kwargs["Body"])
        self.metadata[key] = dict(kwargs.get("Metadata") or {})
        return {"ETag": '"synthetic"'}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = Path(filename).read_bytes()
        self.metadata[(bucket, key)] = dict((ExtraArgs or {}).get("Metadata") or {})
        self.put_calls.append(
            {"Bucket": bucket, "Key": key, "ExtraArgs": ExtraArgs or {}}
        )

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)])

    def head_object(self, *, Bucket, Key):
        value = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(value),
            "Metadata": dict(self.metadata.get((Bucket, Key), {})),
        }

    def delete_object(self, *, Bucket, Key):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.presign_operations.append(operation)
        assert operation in {"get_object", "head_object"}
        return (
            "https://signed.storage.test/"
            f"{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"
        )


def configure_s3(monkeypatch, fake: FakeS3Client) -> None:
    from bot.services import media_storage

    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "MEDIA_S3_ENDPOINT", "https://s3.ru-1.storage.selcloud.ru")
    monkeypatch.setattr(config, "MEDIA_S3_REGION", "ru-1")
    monkeypatch.setattr(config, "MEDIA_S3_BUCKET", "neuromix-media")
    monkeypatch.setattr(config, "MEDIA_S3_ACCESS_KEY_ID", "synthetic-access")
    monkeypatch.setattr(config, "MEDIA_S3_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.setattr(config, "MEDIA_S3_KEY_PREFIX", "uploads")
    monkeypatch.setattr(config, "MEDIA_S3_KEEP_LOCAL_CACHE", False)
    monkeypatch.setattr(config, "MEDIA_S3_PRESIGN_TTL_SECONDS", 900)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://neuromixbot.com")
    monkeypatch.setattr(media_storage, "_build_s3_client", lambda _settings: fake)
    media_storage.reset_media_storage_for_tests()


def test_local_storage_preserves_upload_url_and_file(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "local")
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://media.example.test")
    media_storage.reset_media_storage_for_tests()

    url = media_storage.persist_upload_bytes(
        "refs/image/42/face.png",
        b"image-bytes",
        content_type="image/png",
    )

    assert url == "https://media.example.test/uploads/refs/image/42/face.png"
    assert Path("static/uploads/refs/image/42/face.png").read_bytes() == b"image-bytes"


def test_s3_storage_confirms_object_before_returning_public_url(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)

    url = media_storage.persist_upload_bytes(
        "refs/video/42/clip.mp4",
        b"video-bytes",
        content_type="video/mp4",
        cache_control="private, max-age=0",
    )

    assert url == "https://neuromixbot.com/uploads/refs/video/42/clip.mp4"
    assert fake.objects[("neuromix-media", "uploads/refs/video/42/clip.mp4")] == b"video-bytes"
    assert fake.put_calls[0]["ContentType"] == "video/mp4"
    assert fake.put_calls[0]["CacheControl"] == "private, max-age=0"
    assert not Path("static/uploads/refs/video/42/clip.mp4").exists()


def test_s3_read_url_is_presigned_without_materializing_to_disk(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)

    url = media_storage.presigned_upload_url("feed/result.mp4")

    assert url == (
        "https://signed.storage.test/neuromix-media/"
        "uploads/feed/result.mp4?expires=900"
    )
    assert not Path("static/uploads/feed/result.mp4").exists()


def test_s3_head_url_is_signed_for_head_object_not_get(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)

    url = media_storage.presigned_upload_url("refs/image/42/face.png", method="HEAD")

    assert url.startswith("https://signed.storage.test/")
    assert fake.presign_operations == ["head_object"]


def test_s3_storage_fails_closed_when_configuration_is_incomplete(monkeypatch):
    from bot.services import media_storage

    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "MEDIA_S3_ENDPOINT", "")
    monkeypatch.setattr(config, "MEDIA_S3_REGION", "ru-1")
    monkeypatch.setattr(config, "MEDIA_S3_BUCKET", "neuromix-media")
    monkeypatch.setattr(config, "MEDIA_S3_ACCESS_KEY_ID", "synthetic-access")
    monkeypatch.setattr(config, "MEDIA_S3_SECRET_ACCESS_KEY", "synthetic-secret")
    media_storage.reset_media_storage_for_tests()

    with pytest.raises(media_storage.MediaStorageConfigurationError, match="MEDIA_S3_ENDPOINT"):
        media_storage.persist_upload_bytes("refs/image/42/face.png", b"x")


def test_s3_only_object_is_materialized_into_safe_local_cache(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    fake.objects[("neuromix-media", "uploads/refs/image/42/face.png")] = b"remote-image"
    configure_s3(monkeypatch, fake)

    local = media_storage.materialize_upload("refs/image/42/face.png")

    assert local == str(Path("static/uploads/refs/image/42/face.png"))
    assert Path(local).read_bytes() == b"remote-image"
    assert not list(Path("static/uploads/refs/image/42").glob("*.tmp"))
    marker = Path(local).with_name(f".{Path(local).name}.s3-cache")
    assert marker.is_file()
    marker.touch()
    marker_time = 1
    import os

    os.utime(marker, (marker_time, marker_time))
    stats = media_storage.cleanup_materialized_cache(max_age_seconds=0)
    assert stats == {"removed_count": 1, "removed_bytes": len(b"remote-image")}
    assert not Path(local).exists()


@pytest.mark.parametrize(
    "unsafe",
    ["../secret", "/absolute", "refs/../../secret", "refs/image/42/face.png?token=x"],
)
def test_storage_rejects_unsafe_relative_keys(monkeypatch, unsafe):
    from bot.services import media_storage

    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "local")
    media_storage.reset_media_storage_for_tests()
    with pytest.raises(ValueError, match="media path"):
        media_storage.persist_upload_bytes(unsafe, b"x")


def test_media_input_resolver_materializes_missing_s3_upload(monkeypatch, tmp_path):
    from bot.services import media_input_utils

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    fake.objects[("neuromix-media", "uploads/refs/image/42/face.png")] = b"remote-image"
    configure_s3(monkeypatch, fake)

    resolved = media_input_utils.resolve_local_upload_path(
        "https://neuromixbot.com/uploads/refs/image/42/face.png"
    )

    assert resolved == str(Path("static/uploads/refs/image/42/face.png"))
    assert Path(resolved).read_bytes() == b"remote-image"


async def test_saved_image_reference_is_durable_and_provider_safe_in_s3(
    monkeypatch, tmp_path
):
    from bot.services.reference_storage_service import save_reference_file

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    raw = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(raw, format="WEBP")

    url, saved = await save_reference_file(
        4242,
        raw.getvalue(),
        file_ext="webp",
        kind="image",
        content_type="image/webp",
    )

    assert saved is not None
    assert url == saved.file_url
    assert url.endswith(".png")
    assert any(key.endswith(".webp") for _bucket, key in fake.objects)
    assert any(key.endswith(".png") for _bucket, key in fake.objects)
    assert saved.content_type == "image/png"


def test_generic_upload_returns_only_s3_backed_url(monkeypatch, tmp_path):
    from bot.handlers.generation import save_uploaded_file

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)

    url = save_uploaded_file(b"generated-image", "png")

    assert url is not None and "/uploads/" in url
    relative = url.split("/uploads/", 1)[1]
    assert fake.objects[("neuromix-media", f"uploads/{relative}")] == b"generated-image"
    assert not Path("static/uploads", relative).exists()


async def test_feed_copy_is_persisted_to_s3_with_thumbnail(monkeypatch, tmp_path):
    from bot.services import feed_persist

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    source = Path("static/uploads/20261111/source.jpg")
    source.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), "red").save(source, format="JPEG")

    result = await feed_persist.persist_feed_result_urls(
        ["https://neuromixbot.com/uploads/20261111/source.jpg"],
        require_local=True,
    )

    assert len(result) == 1 and "/uploads/feed/" in result[0]
    keys = {key for _bucket, key in fake.objects}
    assert any(key.startswith("uploads/feed/") and key.endswith(".jpg") for key in keys)
    assert any(key.startswith("uploads/feed/thumbs/") and key.endswith(".jpg") for key in keys)


def test_feed_thumbnail_rebuilds_from_s3_after_local_reclamation(monkeypatch, tmp_path):
    from bot.services import feed_persist

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    raw = BytesIO()
    Image.new("RGB", (64, 64), "orange").save(raw, format="JPEG")
    fake.objects[("neuromix-media", "uploads/feed/result.jpg")] = raw.getvalue()

    thumbnail_url = feed_persist.feed_thumbnail_url_for(
        "https://neuromixbot.com/uploads/feed/result.jpg"
    )

    assert thumbnail_url == "https://neuromixbot.com/uploads/feed/thumbs/result.jpg"
    assert (
        "neuromix-media",
        "uploads/feed/thumbs/result.jpg",
    ) in fake.objects


def test_repeat_choice_image_is_persisted_to_s3(monkeypatch, tmp_path):
    from bot.repeat_personalization import save_repeat_choice_image

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    raw = BytesIO()
    Image.new("RGB", (16, 16), "green").save(raw, format="PNG")

    url = save_repeat_choice_image(raw.getvalue())

    key = "uploads/" + url.split("/uploads/", 1)[1]
    assert fake.objects[("neuromix-media", key)].startswith(b"\xff\xd8\xff")


async def test_curated_trend_reference_is_persisted_to_s3(monkeypatch, tmp_path):
    from bot.services import media_storage
    from bot.services.trend_reference_storage import persist_trend_reference

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    raw = BytesIO()
    Image.new("RGB", (16, 16), "purple").save(raw, format="PNG")
    source_url = media_storage.persist_upload_bytes(
        "refs/image/42/source.png", raw.getvalue(), content_type="image/png"
    )

    persisted = await persist_trend_reference(source_url, media_type="image")

    key = "uploads/" + persisted.file_url.split("/uploads/", 1)[1]
    assert key.startswith("uploads/trend-assets/image/")
    assert fake.objects[("neuromix-media", key)] == raw.getvalue()


async def test_vk_reference_validation_uses_s3_availability(monkeypatch, tmp_path):
    from bot.shared_accounts.vk_image_refs import save_vk_image, verified_image_urls

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    raw = BytesIO()
    Image.new("RGB", (16, 16), "orange").save(raw, format="PNG")

    url = await save_vk_image(2001, raw.getvalue())

    assert verified_image_urls(2001, [url]) == [url]
    key = "uploads/" + url.split("/uploads/", 1)[1]
    assert fake.objects[("neuromix-media", key)].startswith(b"\xff\xd8\xff")


async def test_trend_preview_derivatives_are_persisted_to_s3(monkeypatch, tmp_path):
    from bot.services import media_storage, trend_preview_service

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    source_url = media_storage.persist_upload_bytes(
        "trend-assets/video/source.mp4", b"synthetic-video"
    )

    def preview(_source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"preview-video")

    def poster(_source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"preview-poster")

    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_preview", preview)
    monkeypatch.setattr(trend_preview_service, "_run_ffmpeg_poster", poster)

    assets = await trend_preview_service.ensure_trend_preview_assets(source_url)

    assert assets["preview_url"] and "/uploads/trend-previews/" in assets["preview_url"]
    assert assets["preview_poster_url"] and assets["preview_poster_url"].endswith(".jpg")
    keys = {key for _bucket, key in fake.objects}
    assert any(key.startswith("uploads/trend-previews/") and key.endswith(".mp4") for key in keys)
    assert any(key.startswith("uploads/trend-previews/") and key.endswith(".jpg") for key in keys)


def test_s3_exists_uses_remote_truth_even_when_stale_local_copy_exists(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    stale = Path("static/uploads/refs/image/stale.jpg")
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"only-local")

    assert media_storage.upload_exists("refs/image/stale.jpg") is False


def test_s3_delete_failure_does_not_remove_last_local_copy(monkeypatch, tmp_path):
    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    source = Path("static/uploads/feed/keep.jpg")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"last-copy")

    def fail_delete(**_kwargs):
        raise ConnectionError("simulated remote failure")

    monkeypatch.setattr(fake, "delete_object", fail_delete)
    with pytest.raises(ConnectionError):
        media_storage.delete_upload("feed/keep.jpg")
    assert source.read_bytes() == b"last-copy"


def test_selectel_presigned_lifetime_cannot_exceed_documented_limit(monkeypatch):
    from bot.services import media_storage

    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    monkeypatch.setattr(config, "MEDIA_S3_PRESIGN_TTL_SECONDS", 1200)
    with pytest.raises(media_storage.MediaStorageConfigurationError, match="MEDIA_S3_PRESIGN_TTL_SECONDS"):
        media_storage.validate_media_storage_configuration()


def test_s3_upload_contains_sha256_fingerprint(monkeypatch, tmp_path):
    import hashlib

    from bot.services import media_storage

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    media_storage.persist_upload_bytes("feed/hashed.jpg", b"hello")

    assert fake.put_calls[0]["Metadata"]["sha256"] == hashlib.sha256(b"hello").hexdigest()
