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
            "color=c=blue:s=720x720:r=24",
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


@pytest.mark.parametrize("element", [False, True], ids=["ordinary", "element"])
@pytest.mark.parametrize("status", ["submitting", "pending", "unknown", "done", "failed"])
async def test_mov_repeat_survives_unused_media_expiry(
    mov_context, monkeypatch, element, status
):
    from pathlib import Path

    from bot.services.wan3_prime_retention import cleanup_expired

    engine, actor, transport, saved, source = mov_context
    data = {"prompt": "@Hero moves" if element else "Animate @video1", "duration": 8}
    if element:
        data["elements"] = [{"name": "Hero", "video_url": saved["url"]}]
    else:
        data["video_urls"] = [saved["url"]]
    request = {"mode": "reference", "input": data}
    quote = await engine.quote(actor, request)
    launched = await engine.launch(actor, request, quote["quote_hash"], "retention-original")
    intent = await engine._row(launched["task_id"])
    snapshot = json.loads(intent["snapshot"])
    prepared_url = (
        snapshot["input"]["elements"][0]["video_url"]
        if element
        else snapshot["input"]["video_urls"][0]
    )
    assert prepared_url.endswith(".mp4") and prepared_url != saved["url"]
    probe = engine.probe.for_actor(actor)
    original_path = Path((await probe.probe_url(saved["url"], kind="video")).path)
    original_bytes = original_path.read_bytes()
    derivative_path = Path((await probe.probe_url(prepared_url, kind="video")).path)
    orphan = await engine.probe.storage.save_owned_file(
        actor, kind="video", filename="unused.mov", path=source
    )
    orphan_path = Path((await probe.probe_url(orphan["url"], kind="video")).path)
    async with db.connect(database.DATABASE_PATH) as conn:
        history = await (
            await conn.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id=?",
                (launched["task_id"],),
            )
        ).fetchone()
        # This is the existing pre-fix shape: only the MP4 is in history.
        assert saved["url"] not in history[0]
        assert prepared_url in history[0]
        await conn.execute(
            "UPDATE kling4_intents SET status=? WHERE task_id=?",
            (status, launched["task_id"]),
        )
        await conn.execute("UPDATE wan3_prime_media SET created_at='2000-01-01'")
        await conn.commit()
    monkeypatch.setenv("WAN3_UNUSED_MEDIA_TTL_SECONDS", "1")
    # Small pages prove pinned inputs do not starve the unrelated orphan.
    removed = 0
    for _ in range(4):
        removed += (await cleanup_expired(limit=1))["removed_media"]
    assert removed == 1 and not orphan_path.exists()
    assert original_path.read_bytes() == original_bytes
    assert derivative_path.is_file()
    repeat = await engine.owner_recipe(actor, launched["task_id"])
    assert repeat == request
    repeat_quote = await engine.quote(actor, repeat)
    assert repeat_quote == quote
    # The fixture's provider normally returns the same ID for every POST.
    async def create(model, payload):
        transport.calls += 1
        return 200, {"code": 200, "data": {"taskId": "kie-repeat-task"}}

    monkeypatch.setattr(transport, "create", create)
    repeated = await engine.launch(
        actor, repeat, repeat_quote["quote_hash"], "retention-repeat"
    )
    assert repeated["task_id"] != launched["task_id"]
    assert transport.calls == 2
    assert await engine.owner_recipe(actor, repeated["task_id"]) == request


async def test_intent_snapshot_retains_derivative_without_history(mov_context):
    from pathlib import Path

    from bot.services.wan3_prime_retention import cleanup_expired

    engine, actor, _transport, saved, _source = mov_context
    request = {
        "mode": "reference",
        "input": {"prompt": "Animate @video1", "video_urls": [saved["url"]]},
    }
    quote = await engine.quote(actor, request)
    launched = await engine.launch(actor, request, quote["quote_hash"], "intent-only")
    intent = await engine._row(launched["task_id"])
    url = json.loads(intent["snapshot"])["input"]["video_urls"][0]
    probe = engine.probe.for_actor(actor)
    paths = [
        Path((await probe.probe_url(value, kind="video")).path)
        for value in (saved["url"], url)
    ]
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "DELETE FROM generation_tasks WHERE task_id=?", (launched["task_id"],)
        )
        await conn.execute("UPDATE wan3_prime_media SET created_at='2000-01-01'")
        await conn.commit()
    assert (await cleanup_expired())["removed_media"] == 0
    assert all(path.is_file() for path in paths)
    assert await engine.quote(
        actor, await engine.owner_recipe(actor, launched["task_id"])
    ) == quote


@pytest.mark.parametrize("fault", ["discovery", "recipe", "snapshot"])
async def test_retention_lookup_failure_never_unlinks_candidate(
    mov_context, monkeypatch, fault
):
    from pathlib import Path

    from bot.services import wan3_prime_retention as retention

    engine, actor, _transport, saved, _source = mov_context
    path = Path(
        (await engine.probe.for_actor(actor).probe_url(saved["url"], kind="video")).path
    )
    original_bytes = path.read_bytes()
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("UPDATE wan3_prime_media SET created_at='2000-01-01'")
        if fault != "discovery":
            # A present but malformed optional table must not be treated as absent.
            await conn.execute(
                f"ALTER TABLE kling4_intents RENAME COLUMN {fault} TO unavailable"
            )
        await conn.commit()
    if fault == "discovery":
        real = retention._table_exists

        async def fail(conn, name):
            if name == "kling4_intents":
                raise db.OperationalError("synthetic lookup failure")
            return await real(conn, name)

        monkeypatch.setattr(retention, "_table_exists", fail)
    with pytest.raises(db.OperationalError):
        await retention.cleanup_expired()
    assert path.read_bytes() == original_bytes
    async with db.connect(database.DATABASE_PATH) as conn:
        assert await (
            await conn.execute(
                "SELECT 1 FROM wan3_prime_media WHERE public_url=?", (saved["url"],)
            )
        ).fetchone()


async def test_retention_without_kling_schema_still_expires_orphans(mov_context):
    from pathlib import Path

    from bot.services.wan3_prime_retention import cleanup_expired

    engine, actor, _transport, saved, _source = mov_context
    path = Path(
        (await engine.probe.for_actor(actor).probe_url(saved["url"], kind="video")).path
    )
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("DROP TABLE kling4_intents")
        await conn.execute("UPDATE wan3_prime_media SET created_at='2000-01-01'")
        await conn.commit()
    assert (await cleanup_expired())["removed_media"] == 1
    assert not path.exists()
