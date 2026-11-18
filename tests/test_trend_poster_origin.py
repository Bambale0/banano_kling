"""Public trend thumbnails must be served through the Mini App origin.

These are *public*, small JPG derivatives, never paid originals, private user
uploads, or arbitrary S3 keys. Signed redirects have broken in some WebViews.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from aiohttp import web

from bot.services import trend_poster_origin as origin


class FakeSettings:
    bucket = "demo-public"
    key_prefix = "uploads"

    @classmethod
    def from_config(cls):
        return cls()


class FakeClient:
    def __init__(self, payload=b"\xff\xd8public-jpeg", *, source_size=None, error=None):
        self.payload = payload
        self.source_size = source_size if source_size is not None else len(payload)
        self.error = error
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "Body": BytesIO(self.payload),
            "ContentRange": f"bytes 0-{len(self.payload)-1}/{self.source_size}",
        }


class Request:
    method = "GET"

    def __init__(self, path):
        self.match_info = {"poster_path": path}


@pytest.mark.asyncio
async def test_public_jpeg_is_inline_and_cacheable_same_origin(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(origin, "S3Settings", FakeSettings)
    monkeypatch.setattr(origin, "_s3_client", lambda _s: client)

    result = await origin.serve_public_trend_poster(Request("catalog/0123456789abcdef0123456789abcdef.jpg"))
    assert result.status == 200
    assert result.body == b"\xff\xd8public-jpeg"
    assert result.content_type == "image/jpeg"
    assert result.headers["Cache-Control"].startswith("public, ")
    assert "Location" not in result.headers
    assert result.headers["X-Content-Type-Options"] == "nosniff"
    assert client.calls[0]["Key"] == "uploads/trend-previews/catalog/0123456789abcdef0123456789abcdef.jpg"
    assert "Range" in client.calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "../private.jpg",
    "catalog/../../private.jpg",
    "catalog/secret.mp4",
    "catalog/not-a-thumb.jpg",
    "catalog/%2e%2e/secret.jpg",
    "catalog/0123456789abcdef0123456789abcdef.jpg/extra",
])
async def test_rejects_unsafe_or_non_thumbnail_paths_without_s3(monkeypatch, path):
    monkeypatch.setattr(origin, "_read_public_trend_poster", lambda _key: pytest.fail("S3 must not be queried"))
    with pytest.raises(web.HTTPNotFound):
        await origin.serve_public_trend_poster(Request(path))


@pytest.mark.asyncio
async def test_bounded_download_rejects_huge_s3_object(monkeypatch):
    client = FakeClient(source_size=origin.MAX_PUBLIC_POSTER_BYTES + 1)
    monkeypatch.setattr(origin, "S3Settings", FakeSettings)
    monkeypatch.setattr(origin, "_s3_client", lambda _s: client)
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        await origin.serve_public_trend_poster(Request("catalog/0123456789abcdef0123456789abcdef.jpg"))


@pytest.mark.asyncio
async def test_missing_s3_object_returns_404(monkeypatch):
    client = FakeClient(error=KeyError("missing"))
    monkeypatch.setattr(origin, "S3Settings", FakeSettings)
    monkeypatch.setattr(origin, "_s3_client", lambda _s: client)
    with pytest.raises(web.HTTPNotFound):
        await origin.serve_public_trend_poster(Request("catalog/0123456789abcdef0123456789abcdef.jpg"))


@pytest.mark.asyncio
async def test_transient_s3_failure_returns_503_without_redirect(monkeypatch):
    client = FakeClient(error=ConnectionError("temporary outage"))
    monkeypatch.setattr(origin, "S3Settings", FakeSettings)
    monkeypatch.setattr(origin, "_s3_client", lambda _s: client)
    with pytest.raises(web.HTTPServiceUnavailable):
        await origin.serve_public_trend_poster(Request("179502/0123456789abcdef01234567.jpg"))
