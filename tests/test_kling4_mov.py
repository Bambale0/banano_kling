import asyncio
import json
import subprocess
from copy import deepcopy

import pytest

from bot import database, db
from bot.services.wan3_prime_storage import ActualWan3PrimeProbe, Wan3PrimeStorage
from tests import test_kling4 as lifecycle_tests

engine_context = lifecycle_tests.engine_context


@pytest.fixture
async def mov_context(engine_context, tmp_path, monkeypatch):
    engine, actor, transport = engine_context
    monkeypatch.chdir(tmp_path)
    storage = Wan3PrimeStorage()
    await storage.init_schema()
    source = tmp_path / "iphone.mov"
    await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x320:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    saved = await storage.save_owned_file(
        actor, kind="video", filename=source.name, path=source
    )
    engine.probe = ActualWan3PrimeProbe(storage)
    return engine, actor, transport, saved, source


async def test_mov_quote_and_launch_preserve_original_and_reuse_mp4(mov_context):
    engine, actor, transport, saved, source = mov_context
    original_bytes = source.read_bytes()
    request = {
        "mode": "reference",
        "input": {
            "prompt": "Animate @video1",
            "duration": 8,
            "video_urls": [saved["url"]],
        },
    }
    original = deepcopy(request)
    quote = await engine.quote(actor, request)
    assert quote == await engine.quote(actor, request)
    result = await engine.launch(
        actor, request, quote["quote_hash"], "mov-regression-1"
    )
    again = await engine.launch(actor, request, quote["quote_hash"], "mov-regression-1")
    assert result["task_id"] == again["task_id"]
    assert transport.calls == 1
    row = await engine._row(result["task_id"])
    snapshot = json.loads(row["snapshot"])
    assert snapshot["input"]["video_urls"][0].endswith(".mp4")
    assert json.loads(row["recipe"]) == original
    assert request == original and source.read_bytes() == original_bytes
    async with db.connect(database.DATABASE_PATH) as conn:
        rows = await (
            await conn.execute(
                "SELECT public_url FROM wan3_prime_media WHERE source LIKE 'kling4_mp4_v1:%'"
            )
        ).fetchall()
    assert len(rows) == 1
    converted = await engine.probe.for_actor(actor).probe_url(rows[0][0], kind="video")
    assert converted.extension == ".mp4"
    assert abs(converted.duration_seconds - 3) < 0.1

    def streams(path):
        return subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-c",
                "copy",
                "-f",
                "streamhash",
                "-hash",
                "sha256",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout

    assert await asyncio.to_thread(streams, source) == await asyncio.to_thread(
        streams, converted.path
    )


async def test_mov_conversion_rejects_another_owner(mov_context):
    from types import SimpleNamespace

    from bot.services.wan3_prime_media import Wan3PrimeValidationError

    engine, actor, _transport, saved, _source = mov_context
    other = SimpleNamespace(user_id=actor.user_id + 1, telegram_id=1, is_admin=True)
    with pytest.raises(Wan3PrimeValidationError, match="another user"):
        await engine.quote(
            other,
            {
                "mode": "reference",
                "input": {"prompt": "x", "video_urls": [saved["url"]]},
            },
        )


async def test_conversion_failure_never_creates_provider_task(mov_context, monkeypatch):
    from bot.services import kling4_media
    from bot.services.kling4_contract import Kling4Error

    engine, actor, transport, saved, _source = mov_context

    async def fail(*args, **kwargs):
        raise TimeoutError("test timeout")

    monkeypatch.setattr(kling4_media, "_remux", fail)
    with pytest.raises(Kling4Error, match="подготовить MOV"):
        await engine.quote(
            actor,
            {
                "mode": "reference",
                "input": {"prompt": "x", "video_urls": [saved["url"]]},
            },
        )
    assert transport.calls == 0


async def test_concurrent_conversion_is_bounded_and_retry_reuses_result(
    mov_context, monkeypatch
):
    from bot.services import kling4_media
    from bot.services.kling4_contract import Kling4Error

    engine, actor, _transport, saved, _source = mov_context
    started, release = asyncio.Event(), asyncio.Event()
    real = kling4_media._remux

    async def wait(*args, **kwargs):
        started.set()
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(kling4_media, "_remux", wait)
    request = {
        "mode": "reference",
        "input": {"prompt": "x", "video_urls": [saved["url"]]},
    }
    first = asyncio.create_task(engine.quote(actor, request))
    await started.wait()
    try:
        with pytest.raises(Kling4Error, match="ещё подготавливается"):
            await engine.quote(actor, request)
    finally:
        release.set()
    quote = await first
    assert await engine.quote(actor, request) == quote
