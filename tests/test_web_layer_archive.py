"""Bounded layer bundle archiver and crash-recovery ledger tests."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from bot import web_layers


@pytest.mark.asyncio
async def test_layer_archiver_retains_all_images_and_writes_bounded_s3_zip(monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"A" * 40
    jpeg = b"\xff\xd8\xff" + b"B" * 45
    stored: dict[str, bytes] = {}
    seen: list[str] = []
    class FakeStream:
        def __init__(self, data):
            self.data = data
        async def iter_chunked(self, _):
            yield self.data
    class FakeResponse:
        def __init__(self, data):
            self.status = 200
            self.headers = {"Content-Length": str(len(data))}
            self.content = FakeStream(data)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
    class FakeSession:
        def __init__(self, **_):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        def get(self, url, **_):
            seen.append(url)
            return FakeResponse(png if url.endswith("0") else jpeg)
    def persist(relative, local_path, **kwargs):
        with open(local_path, "rb") as infile:
            stored[relative] = infile.read()
        return "https://neuromixbot.com/uploads/" + relative
    monkeypatch.setattr(web_layers, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(web_layers, "persist_upload_file", persist)
    monkeypatch.setattr(web_layers.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(web_layers.aiohttp, "TCPConnector", lambda **_: object())
    task_id = "web_" + "a" * 32
    sources = ["https://cdn.kie.ai/layer-0", "https://cdn.kie.ai/layer-1"]
    urls, bundle_url = await web_layers.archive_web_layers(
        task_id, "b" * 32, sources,
    )
    assert seen == sources
    assert len(urls) == 2
    assert len(stored) == 3
    assert bundle_url.endswith("-layers.zip")
    zipped = next(data for path, data in stored.items() if path.endswith(".zip"))
    with zipfile.ZipFile(io.BytesIO(zipped)) as zipfile_obj:
        assert zipfile_obj.namelist() == [
            "000_base.png", "001_layer.jpg", "layers.json",
        ]
        assert zipfile_obj.read("000_base.png") == png
        assert zipfile_obj.read("001_layer.jpg") == jpeg
        manifest = json.loads(zipfile_obj.read("layers.json"))
        assert manifest[0]["mime"] == "image/png"
        assert manifest[1]["mime"] == "image/jpeg"


@pytest.mark.asyncio
async def test_layer_archiver_rejects_bad_host_and_large_media_without_s3(monkeypatch):
    monkeypatch.setattr(web_layers, "is_s3_enabled", lambda: True)
    for invalid in ("http://cdn.kie.ai/x.png",
                    "https://cdn.kie.ai.evil.example/x.png",
                    "https://127.0.0.1/x.png"):
        with pytest.raises(ValueError):
            await web_layers.archive_web_layers(
                "web_" + "b" * 32, "c" * 32,
                [invalid, "https://cdn.kie.ai/valid.png"],
            )
