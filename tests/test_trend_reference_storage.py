from pathlib import Path

import pytest
from PIL import Image

from bot.services import trend_reference_storage as storage


@pytest.mark.asyncio
async def test_persist_trend_image_is_content_addressed_and_durable(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage, "TREND_REFERENCE_ROOT", Path("static/uploads/trend-assets")
    )
    monkeypatch.setattr(
        storage,
        "config",
        type("TestConfig", (), {"static_base_url": "https://assets.example.test"})(),
    )
    source = tmp_path / "creator-face-and-dress.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(source, format="PNG")
    monkeypatch.setattr(
        storage, "resolve_local_upload_path", lambda _value: str(source)
    )

    first = await storage.persist_trend_reference(
        "https://source.test/private.png", media_type="image"
    )
    second = await storage.persist_trend_reference(
        "https://source.test/private.png", media_type="image"
    )

    assert first == second
    assert first.mime_type == "image/png"
    assert first.size_bytes == source.stat().st_size
    assert len(first.file_hash) == 64
    assert first.file_url.startswith(
        "https://assets.example.test/uploads/trend-assets/image/"
    )
    relative = first.file_url.split("https://assets.example.test/", 1)[1]
    expected = Path("static") / relative
    assert expected.is_file()
    assert expected.read_bytes() == source.read_bytes()


@pytest.mark.asyncio
async def test_persist_trend_image_rejects_invalid_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage, "TREND_REFERENCE_ROOT", Path("static/uploads/trend-assets")
    )
    source = tmp_path / "not-image.png"
    source.write_text("not an image", encoding="utf-8")
    monkeypatch.setattr(
        storage, "resolve_local_upload_path", lambda _value: str(source)
    )

    with pytest.raises(storage.TrendReferenceStorageError, match="valid image"):
        await storage.persist_trend_reference(
            "https://source.test/not-image.png", media_type="image"
        )


@pytest.mark.asyncio
async def test_external_reference_is_rejected_before_any_download(monkeypatch):
    monkeypatch.setattr(storage, "resolve_local_upload_path", lambda _value: None)
    with pytest.raises(storage.TrendReferenceStorageError, match="только загруженный"):
        await storage.persist_trend_reference(
            "http://127.0.0.1/private.png",
            media_type="image",
        )


@pytest.mark.asyncio
async def test_video_mime_and_extension_do_not_bypass_signature_validation(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage, "TREND_REFERENCE_ROOT", Path("static/uploads/trend-assets")
    )
    source = tmp_path / "fake.mp4"
    source.write_bytes(b"this is not an mp4 container")
    monkeypatch.setattr(
        storage, "resolve_local_upload_path", lambda _value: str(source)
    )

    with pytest.raises(storage.TrendReferenceStorageError, match="supported video"):
        await storage.persist_trend_reference(
            "https://source.test/fake.mp4",
            media_type="video",
        )


@pytest.mark.asyncio
async def test_aac_adts_reference_keeps_aac_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage, "TREND_REFERENCE_ROOT", Path("static/uploads/trend-assets")
    )
    monkeypatch.setattr(
        storage,
        "config",
        type("TestConfig", (), {"static_base_url": "https://assets.example.test"})(),
    )
    source = tmp_path / "voice.aac"
    source.write_bytes(b"\xff\xf1" + b"\x00" * 30)
    monkeypatch.setattr(
        storage, "resolve_local_upload_path", lambda _value: str(source)
    )

    persisted = await storage.persist_trend_reference(
        "https://source.test/voice.aac",
        media_type="audio",
    )

    assert persisted.mime_type == "audio/aac"
    assert persisted.file_url.endswith(".aac")



@pytest.mark.asyncio
async def test_audio_mime_and_extension_do_not_bypass_signature_validation(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage, "TREND_REFERENCE_ROOT", Path("static/uploads/trend-assets")
    )
    source = tmp_path / "fake.mp3"
    source.write_bytes(b"this is not an mp3 stream")
    monkeypatch.setattr(
        storage, "resolve_local_upload_path", lambda _value: str(source)
    )

    with pytest.raises(storage.TrendReferenceStorageError, match="supported audio"):
        await storage.persist_trend_reference(
            "https://source.test/fake.mp3",
            media_type="audio",
        )
