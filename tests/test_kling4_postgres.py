"""Kling4 intents through the real production PG adapter, isolated CI DB only."""

import asyncio
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import database, db
from bot.services.kling4_contract import Kling4Error
from bot.services.kling4_lifecycle import Kling4Lifecycle
from tests.test_result_durability_postgres import (
    delivery_postgres_schema as delivery_postgres_schema,  # noqa: PLC0414 - pytest fixture re-export
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUNTIME_POSTGRES_TEST") != "1",
    reason="requires isolated PostgreSQL runtime CI",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_state", ["fail", "success"])
async def test_pg_kling4_idempotency_settings_failure_and_ambiguous_restart(
    delivery_postgres_schema, monkeypatch, tmp_path, provider_state
):
    class Provider:
        calls = 0
        task = "pg-kling4-" + uuid.uuid4().hex

        async def create(self, model, data):
            self.calls += 1
            return 200, {"code": 200, "data": {"taskId": self.task}}

        async def detail(self, task):
            return {
                "taskId": task,
                "model": "kling-4.0/reference-to-video",
                "state": provider_state,
                "creditsConsumed": 85.5 if provider_state == "success" else 0,
                **(
                    {
                        "resultJson": json.dumps(
                            {"resultUrls": ["https://provider.example.test/kling4.mp4"]}
                        )
                    }
                    if provider_state == "success"
                    else {}
                ),
            }

    provider = Provider()
    engine = Kling4Lifecycle(transport=provider)
    await engine.init_schema()
    from bot.config import config
    from bot.services import kling4_lifecycle as module
    from bot.services.wan3_prime_media import MediaInfo

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://media.example.test")
    monkeypatch.setattr(config, "is_admin", lambda uid: uid == 999999999)

    async def download(_url, *, destination, **_kwargs):
        destination.write_bytes(b"original-kling4-output")

    class ResultProbe:
        def __init__(self, *_args, **_kwargs):
            pass

        async def probe_file(self, _path, *, kind):
            return MediaInfo(kind=kind, duration_seconds=3, size_bytes=21)

    class Telegram:
        sent = 0

        async def send_message(self, *_args, **_kwargs):
            self.sent += 1

        async def send_video(self, _user, *, video, **_kwargs):
            assert Path(video.path).read_bytes() == b"original-kling4-output"
            self.sent += 1

    engine.telegram_bot = Telegram()
    monkeypatch.setattr(module, "fetch_public_asset", download)
    monkeypatch.setattr(module, "ActualWan3PrimeProbe", ResultProbe)
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("DELETE FROM kling4_intents")
        row = await (
            await conn.execute(
                "INSERT INTO users(telegram_id,credits) VALUES(999999999,100) ON CONFLICT(telegram_id) DO UPDATE SET credits=100 RETURNING id"
            )
        ).fetchone()
        await conn.commit()
    actor = SimpleNamespace(user_id=row[0], telegram_id=999999999, is_admin=True)
    request = {
        "mode": "reference",
        "input": {"prompt": "Kling4 PostgreSQL regression", "duration": 3},
    }
    quote = await engine.quote(actor, request)
    results = await asyncio.gather(
        *(
            engine.launch(actor, request, quote["quote_hash"], "pg-concurrent-intent")
            for _ in range(4)
        )
    )
    assert len({result["task_id"] for result in results}) == 1 and provider.calls == 1
    await engine.tick()
    expected = "done" if provider_state == "success" else "failed"
    terminal = await engine.status(actor, results[0]["task_id"])
    assert terminal["status"] == expected
    if expected == "done":
        assert terminal["actual_credits"] == "85.5"
        assert "/uploads/kling4/results/" in terminal["result_url"]
    await engine.tick()
    assert (await engine.status(actor, results[0]["task_id"]))[
        "delivery_status"
    ] == "delivered"
    assert engine.telegram_bot.sent == 1 and provider.calls == 1
    settings, revision = await engine.settings()
    settings["max_active"] = 4
    await engine.update_settings(actor, settings, revision)
    with pytest.raises(Kling4Error):
        await engine.launch(actor, request, quote["quote_hash"], "pg-stale-intent")

    class Uncertain:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            raise TimeoutError

    uncertain = Uncertain()
    restart = Kling4Lifecycle(transport=uncertain)
    new_quote = await restart.quote(actor, request)
    unknown = await restart.launch(
        actor, request, new_quote["quote_hash"], "pg-uncertain-intent"
    )
    restart = Kling4Lifecycle(transport=uncertain)
    recovered = await restart.launch(
        actor, request, new_quote["quote_hash"], "pg-uncertain-intent"
    )
    assert (
        unknown["status"] == recovered["status"] == "unknown" and uncertain.calls == 1
    )
    async with db.connect(database.DATABASE_PATH) as conn:
        balance = await (
            await conn.execute("SELECT credits FROM users WHERE id=?", (actor.user_id,))
        ).fetchone()
    assert balance[0] == 100
