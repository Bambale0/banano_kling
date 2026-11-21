"""Live Trend MP4s use a narrowly scoped same-origin byte-range endpoint."""
from __future__ import annotations

from io import BytesIO

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.services import trend_poster_origin as origin


MP4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 500
HASH = "a" * 32


class Request:
    def __init__(self, digest=HASH, headers=None):
        self.match_info = {"video_hash": digest}
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_live_mp4_full_and_range_are_same_origin_without_redirect(monkeypatch):
    monkeypatch.setattr(origin, "_read_public_trend_live_video", lambda _key: MP4)
    full = await origin.serve_public_trend_live_video(Request())
    assert full.status == 200 and full.content_type == "video/mp4"
    assert full.body == MP4 and "Location" not in full.headers
    assert full.headers["Accept-Ranges"] == "bytes"
    assert full.headers["X-Content-Type-Options"] == "nosniff"
    part = await origin.serve_public_trend_live_video(Request(headers={"Range": "bytes=0-1"}))
    assert part.status == 206 and part.body == MP4[:2]
    assert part.headers["Content-Range"] == f"bytes 0-1/{len(MP4)}"
    tail = await origin.serve_public_trend_live_video(Request(headers={"Range": "bytes=-10"}))
    assert tail.status == 206 and tail.body == MP4[-10:]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["../bad", "not-a-hash", "a"*31, "a"*32 + ".mov"])
async def test_live_route_rejects_untrusted_paths_before_s3(monkeypatch, value):
    monkeypatch.setattr(
        origin, "_read_public_trend_live_video",
        lambda _key: pytest.fail("private content must not be accessed"),
    )
    with pytest.raises(web.HTTPNotFound):
        await origin.serve_public_trend_live_video(Request(value))


@pytest.mark.asyncio
@pytest.mark.parametrize("hdr", ["bytes=5000-", "bytes=10-2", "bytes=0-1,3-4", "bytes=bad", "bytes=-0"])
async def test_invalid_byte_ranges_return_416(monkeypatch, hdr):
    monkeypatch.setattr(origin, "_read_public_trend_live_video", lambda _key: MP4)
    with pytest.raises(web.HTTPRequestRangeNotSatisfiable):
        await origin.serve_public_trend_live_video(Request(headers={"Range": hdr}))


@pytest.mark.asyncio
async def test_s3_outage_falls_back_to_poster(monkeypatch):
    def broken(_key):
        raise ConnectionError("unavailable")
    monkeypatch.setattr(origin, "_read_public_trend_live_video", broken)
    with pytest.raises(web.HTTPServiceUnavailable):
        await origin.serve_public_trend_live_video(Request())


@pytest.mark.asyncio
async def test_route_only_captures_live_namespace():
    app = web.Application()
    origin.register_public_trend_poster_route(app)

    async def generic(request):
        return web.Response(status=307)

    app.router.add_get("/uploads/{path:.*}", generic)
    for path, handler in (
        (f"/uploads/trend-previews/live/{HASH}.mp4", origin.serve_public_trend_live_video),
        (f"/uploads/trend-previews/179502/{HASH}.mp4", generic),
        (f"/uploads/feed/{HASH}.mp4", generic),
        (f"/uploads/private/{HASH}.mp4", generic),
    ):
        match = await app.router.resolve(make_mocked_request("GET", path, app=app))
        assert match.handler is handler


@pytest.mark.asyncio
async def test_bounded_s3_reader_rejects_oversized_and_corrupt_objects(monkeypatch):
    class Settings:
        bucket = "demo"
        key_prefix = "uploads"
        @classmethod
        def from_config(cls):
            return cls()
    class Client:
        def __init__(self, data, total=None):
            self.data, self.total = data, total or len(data)
        def get_object(self, **kwargs):
            assert kwargs["Key"] == f"uploads/trend-previews/live/{HASH}.mp4"
            assert "Range" in kwargs
            return {"Body": BytesIO(self.data),
                    "ContentRange": f"bytes 0-{len(self.data)-1}/{self.total}"}
    monkeypatch.setattr(origin, "S3Settings", Settings)
    monkeypatch.setattr(origin, "_s3_client", lambda _s: Client(MP4, origin.MAX_PUBLIC_LIVE_BYTES + 1))
    with pytest.raises(origin.PosterTooLargeError):
        origin._read_public_trend_live_video(f"trend-previews/live/{HASH}.mp4")
    monkeypatch.setattr(origin, "_s3_client", lambda _s: Client(b"not an mp4"))
    with pytest.raises(ValueError):
        origin._read_public_trend_live_video(f"trend-previews/live/{HASH}.mp4")
