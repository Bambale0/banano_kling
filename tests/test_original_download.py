"""Original buttons must lead to attachment responses without copying media."""
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.config import config


def test_result_buttons_request_download_without_changing_media_source(monkeypatch):
    from bot.keyboards import get_image_result_keyboard, get_video_result_keyboard

    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://neuromixbot.com")
    source = "https://tanyapi.chillcreative.ru/uploads/results/original.png"
    for keyboard in (get_image_result_keyboard(source), get_video_result_keyboard(source)):
        assert keyboard.inline_keyboard[0][0].url == (
            "https://neuromixbot.com/api/media-download/results/original.png"
        )


@pytest.mark.asyncio
async def test_local_attachment_get_head_range_and_missing(monkeypatch, tmp_path):
    from bot.services.original_download import setup_original_download_routes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "local")
    path = tmp_path / "static/uploads/results/Мой фильм.mp4"
    path.parent.mkdir(parents=True)
    original = b"original-video-bytes-no-transcoding"
    path.write_bytes(original)
    app = web.Application()
    setup_original_download_routes(app)
    async with TestClient(TestServer(app)) as client:
        url = "/api/media-download/results/Мой фильм.mp4"
        async with client.get(url) as response:
            assert response.status == 200
            assert await response.read() == original
            assert response.headers["Content-Disposition"].startswith("attachment;")
            assert "filename*=UTF-8''%D0%9C" in response.headers["Content-Disposition"]
            assert response.headers["Cache-Control"] == "private, no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        async with client.head(url) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(original))
            assert await response.read() == b""
        async with client.get(url, headers={"Range": "bytes=2-7"}) as response:
            assert response.status == 206
            assert await response.read() == original[2:8]
            assert response.headers["Content-Disposition"].startswith("attachment;")
        assert (await client.get("/api/media-download/results/missing.mp4")).status == 404
        assert (await client.get("/api/media-download/results/")).status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_s3_download_signs_attachment_with_existing_ttl_without_local_copy(
    monkeypatch, tmp_path, method,
):
    from bot.services import media_storage
    from bot.services.original_download import setup_original_download_routes

    monkeypatch.chdir(tmp_path)
    for key, value in {
        "MEDIA_STORAGE_BACKEND": "s3",
        "MEDIA_S3_ENDPOINT": "https://s3.example.test",
        "MEDIA_S3_REGION": "ru-1",
        "MEDIA_S3_BUCKET": "private-media",
        "MEDIA_S3_ACCESS_KEY_ID": "test-access",
        "MEDIA_S3_SECRET_ACCESS_KEY": "test-secret",
        "MEDIA_S3_KEY_PREFIX": "uploads",
        "MEDIA_S3_PRESIGN_TTL_SECONDS": 600,
        "STATIC_BASE_URL": "https://neuromixbot.com",
    }.items():
        monkeypatch.setattr(config, key, value)
    media_storage.reset_media_storage_for_tests()
    app = web.Application()
    setup_original_download_routes(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.request(
            method, "/api/media-download/results/clip.mp4", allow_redirects=False,
        )
        assert response.status == 307
        parsed = urlsplit(response.headers["Location"])
        assert parsed.netloc == "s3.example.test"
        assert parsed.path == "/private-media/uploads/results/clip.mp4"
        query = parse_qs(parsed.query)
        assert query["response-content-disposition"] == ['attachment; filename="clip.mp4"; filename*=UTF-8\'\'clip.mp4']
        assert query["response-cache-control"] == ["private, no-store"]
        assert query["X-Amz-Expires"] == ["600"]
        assert query["X-Amz-SignedHeaders"] == ["host"]
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
    assert not (tmp_path / "static").exists()
    media_storage.reset_media_storage_for_tests()


def test_trusted_download_mapping_preserves_external_and_signed_capabilities(monkeypatch):
    from bot.services.original_download import original_download_url

    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://neuromixbot.com")
    for url in (
        "https://evil.test/uploads/results/clip.mp4",
        "https://neuromixbot.com.evil.test/uploads/results/clip.mp4",
        "https://neuromixbot.com:444/uploads/results/clip.mp4",
        "https://name:secret@neuromixbot.com/uploads/results/clip.mp4",
        "//evil.test/uploads/results/clip.mp4",
        "https://neuromixbot.com/uploads/results/clip.mp4?token=keep-me",
        "https://neuromixbot.com/uploads/%2e%2e/secret",
    ):
        assert original_download_url(url) == url
    assert original_download_url("/uploads/results/Мой фильм.mp4") == (
        "https://neuromixbot.com/api/media-download/results/"
        "%D0%9C%D0%BE%D0%B9%20%D1%84%D0%B8%D0%BB%D1%8C%D0%BC.mp4"
    )
    signed = "https://neuromixbot.com/genjutsu/media/asset?expires=123&signature=abc"
    assert original_download_url(signed) == signed + "&download=1"
    assert original_download_url(original_download_url(signed)) == signed + "&download=1"


@pytest.mark.asyncio
async def test_download_rejects_traversal_and_local_symlink_escape(monkeypatch, tmp_path):
    from yarl import URL

    from bot.services.original_download import setup_original_download_routes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "local")
    root = tmp_path / "static/uploads"
    root.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("must-not-be-served")
    try:
        (root / "escape.txt").symlink_to(secret)
    except OSError:
        pass  # Windows may not grant symlink privileges; Linux CI covers it.
    app = web.Application()
    setup_original_download_routes(app)
    async with TestClient(TestServer(app)) as client:
        for path in ("%2e%2e/secret.txt", "%2e%2e%5csecret.txt", "%00secret", "escape.txt"):
            response = await client.get(URL("/api/media-download/" + path, encoded=True))
            assert response.status == 404
        assert (await client.post("/api/media-download/file.mp4")).status == 405


def test_attachment_filename_is_safe_and_retains_extension():
    from bot.services.media_storage import attachment_content_disposition

    value = attachment_content_disposition('results/film\r\n";bad.mp4')
    assert "\r" not in value and "\n" not in value
    assert value == 'attachment; filename="filmbad.mp4"; filename*=UTF-8\'\'filmbad.mp4'
    value = attachment_content_disposition("results/" + "я" * 500 + ".mov")
    assert len(value) < 700
    assert value.endswith(".mov")


@pytest.mark.asyncio
async def test_signing_failure_returns_private_503_without_falling_back_to_preview(monkeypatch):
    from bot.services.original_download import setup_original_download_routes

    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "MEDIA_S3_ACCESS_KEY_ID", "")
    app = web.Application()
    setup_original_download_routes(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/media-download/results/clip.mp4", allow_redirects=False)
        assert response.status == 503
        assert response.headers["Cache-Control"] == "private, no-store"
        assert "Location" not in response.headers
        assert await response.text() == "Media temporarily unavailable"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Sparse file fixture requires Linux filesystem")
async def test_large_local_original_is_served_with_range_without_a_copy(monkeypatch, tmp_path):
    from bot.services.original_download import setup_original_download_routes

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_BACKEND", "local")
    path = tmp_path / "static/uploads/results/large.mp4"
    path.parent.mkdir(parents=True)
    # Sparse fixture, no allocation of the apparent 2 GiB size in RAM or disk.
    with path.open("wb") as output:
        output.write(b"original")
        output.truncate(2 * 1024 ** 3)
    app = web.Application()
    setup_original_download_routes(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/media-download/results/large.mp4", headers={"Range": "bytes=0-7"})
        assert response.status == 206
        assert response.headers["Content-Length"] == "8"
        assert await response.read() == b"original"
    assert [p.name for p in path.parent.iterdir()] == ["large.mp4"]
