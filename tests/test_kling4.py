import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bot.services.kling4_contract import (
    DEFAULT_SETTINGS,
    Kling4Error,
    require_admin,
    validate_recipe,
)
from bot.services.wan3_prime_media import MediaInfo, Wan3PrimeValidationError


class Probe:
    async def probe_url(self, url, *, kind):
        return MediaInfo(
            kind=kind,
            url=url,
            sha256="a" * 64,
            size_bytes=1000,
            width=1280,
            height=720,
            extension={"image": ".png", "video": ".mp4", "audio": ".wav"}[kind],
            duration_seconds=3.52 if "fraction" in url else 3,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,video,resolution,cost",
    [
        ("reference", False, "720p", "85.5"),
        ("reference", False, "1080p", "127.5"),
        ("keyframe", False, "720p", "85.5"),
        ("keyframe", False, "1080p", "127.5"),
        ("reference", True, "720p", "102"),
        ("reference", True, "1080p", "153"),
    ],
)
async def test_six_tariffs(mode, video, resolution, cost):
    body = {
        "mode": mode,
        "input": {
            "prompt": "A calm landscape",
            "duration": 3,
            "resolution": resolution,
        },
    }
    if video:
        body["input"]["video_urls"] = ["https://owned/clip.mp4"]
    recipe = await validate_recipe(body, Probe())
    assert Decimal(recipe.quote(DEFAULT_SETTINGS, 1)["provider_credits"]) == Decimal(
        cost
    )


@pytest.mark.asyncio
async def test_fractional_video_and_quote_frozen_input():
    recipe = await validate_recipe(
        {
            "mode": "reference",
            "input": {
                "prompt": "A",
                "duration": 3,
                "video_urls": ["https://owned/fraction.mp4"],
            },
        },
        Probe(),
    )
    assert recipe.quote(DEFAULT_SETTINGS, 1)["provider_credits"] == "119"
    assert (
        recipe.quote(DEFAULT_SETTINGS, 1)["quote_hash"]
        != recipe.quote(DEFAULT_SETTINGS, 2)["quote_hash"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input",
    [
        {"prompt": "x", "duration": True},
        {"prompt": "x", "seed": 1},
        {"prompt": "x", "duration": 3, "keyframe_urls": ["https://owned/a.png"] * 5},
        {"prompt": "@missing"},
        {"prompt": "x", "video_urls": []},
    ],
)
async def test_bad_contract_never_submitted(input):
    with pytest.raises(Kling4Error):
        await validate_recipe({"mode": "keyframe", "input": input}, Probe())


@pytest.mark.asyncio
async def test_element_video_count_and_reserved_names():
    base = {
        "mode": "reference",
        "input": {
            "prompt": "@Hero smiles",
            "elements": [
                {
                    "name": "Hero",
                    "video_url": "https://owned/hero.mp4",
                    "tag": "character",
                }
            ],
        },
    }
    result = await validate_recipe(base, Probe())
    assert result.video_seconds == 3
    base["input"]["elements"][0]["name"] = "IMAGE_1"
    with pytest.raises(Kling4Error):
        await validate_recipe(base, Probe())


def test_server_admin_gate():
    with pytest.raises(Kling4Error) as exc:
        require_admin(SimpleNamespace(is_admin=False))
    assert exc.value.status == 403


@pytest.mark.asyncio
async def test_unknown_submission_is_durable_and_not_resubmitted(tmp_path, monkeypatch):
    from bot import database
    from bot.services.kling4_lifecycle import Kling4Lifecycle

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "app.db"))
    await database.init_db()
    user = await database.get_or_create_user(999999999)
    actor = SimpleNamespace(
        user_id=user.id, telegram_id=user.telegram_id, is_admin=True
    )

    class Transport:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            raise TimeoutError("ambiguous transport")

    transport = Transport()
    engine = Kling4Lifecycle(transport=transport, probe=Probe())
    await engine.init_schema()
    request = {"mode": "reference", "input": {"prompt": "test", "duration": 3}}
    quote = await engine.quote(actor, request)
    first = await engine.launch(actor, request, quote["quote_hash"], "same-intent")
    second = await engine.launch(actor, request, quote["quote_hash"], "same-intent")
    assert first["status"] == second["status"] == "unknown"
    assert first["task_id"] == second["task_id"] and transport.calls == 1
    with pytest.raises(Kling4Error):
        await engine.launch(
            actor,
            {"mode": "reference", "input": {"prompt": "changed"}},
            quote["quote_hash"],
            "same-intent",
        )
    with pytest.raises(Kling4Error):
        await engine.status(replace_actor(actor, is_admin=False), first["task_id"])


def replace_actor(actor, **changes):
    return SimpleNamespace(**(vars(actor) | changes))


@pytest.mark.asyncio
async def test_same_clip_in_video_and_element_only_bills_ordinary_slot():
    recipe = await validate_recipe(
        {
            "mode": "reference",
            "input": {
                "prompt": "@Hero waves",
                "duration": 3,
                "video_urls": ["https://owned/hero.mp4"],
                "elements": [{"name": "Hero", "video_url": "https://owned/hero.mp4"}],
            },
        },
        Probe(),
    )
    assert Decimal(recipe.quote(DEFAULT_SETTINGS, 1)["provider_credits"]) == 102
    assert recipe.video_seconds == 6


@pytest.mark.asyncio
async def test_video_element_without_ordinary_video_uses_nonvideo_tariff():
    recipe = await validate_recipe(
        {
            "mode": "reference",
            "input": {
                "prompt": "@Hero waves",
                "duration": 3,
                "elements": [{"name": "Hero", "video_url": "https://owned/hero.mp4"}],
            },
        },
        Probe(),
    )
    assert Decimal(recipe.quote(DEFAULT_SETTINGS, 1)["provider_credits"]) == Decimal(
        "85.5"
    )


@pytest.fixture
async def engine_context(tmp_path, monkeypatch):
    from bot import database
    from bot.services import kling4_lifecycle as module

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "app.db"))
    await database.init_db()
    user = await database.get_or_create_user(999999999)
    actor = SimpleNamespace(
        user_id=user.id, telegram_id=user.telegram_id, is_admin=True
    )

    class Transport:
        calls = 0
        detail_calls = 0

        def __init__(self):
            self.payload = {
                "taskId": "kie-task",
                "model": "kling-4.0/reference-to-video",
                "state": "waiting",
            }

        async def create(self, model, data):
            self.calls += 1
            return 200, {"code": 200, "data": {"taskId": "kie-task"}}

        async def detail(self, task_id):
            self.detail_calls += 1
            return self.payload

    transport = Transport()
    engine = module.Kling4Lifecycle(transport=transport, probe=Probe())
    await engine.init_schema()
    return engine, actor, transport


@pytest.mark.asyncio
async def test_stale_quote_settings_audit_and_no_submission(engine_context):
    engine, actor, transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    settings, revision = await engine.settings()
    settings["rates"]["reference"]["720p"] = "30"
    await engine.update_settings(actor, settings, revision)
    with pytest.raises(Kling4Error):
        await engine.launch(actor, request, quote["quote_hash"], "stale-intent")
    assert transport.calls == 0
    with pytest.raises(Kling4Error):
        await engine.update_settings(actor, settings, revision)
    settings["admin_only"] = False
    with pytest.raises(Kling4Error):
        await engine.update_settings(actor, settings, revision + 1)


@pytest.mark.asyncio
async def test_double_click_uses_one_provider_post(engine_context):
    import asyncio

    engine, actor, transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    results = await asyncio.gather(
        *(
            engine.launch(actor, request, quote["quote_hash"], "double-click")
            for _ in range(2)
        )
    )
    assert results[0]["task_id"] == results[1]["task_id"] and transport.calls == 1
    with pytest.raises(Kling4Error):
        await engine.status(
            replace_actor(actor, user_id=actor.user_id + 1), results[0]["task_id"]
        )


@pytest.mark.asyncio
async def test_canonical_success_waits_for_valid_durable_video(
    engine_context, monkeypatch, tmp_path
):
    from bot.config import config
    from bot.services import kling4_lifecycle as module

    engine, actor, transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(actor, request, quote["quote_hash"], "durable-result")
    task_id = result["task_id"]
    transport.payload = {
        **transport.payload,
        "state": "success",
        "resultJson": "not-json",
        "response": {"resultUrls": ["https://provider/result.mp4"]},
    }
    with pytest.raises(ValueError):
        await engine.reconcile(task_id)
    assert (await engine.status(actor, task_id))["status"] == "pending"
    transport.payload = {
        **transport.payload,
        "model": "wrong",
        "resultJson": json.dumps({"resultUrls": ["https://provider/result.mp4"]}),
    }
    with pytest.raises(Kling4Error):
        await engine.reconcile(task_id)
    transport.payload.update(model="kling-4.0/reference-to-video", creditsConsumed=85.5)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://media.example.test")

    async def download(url, *, destination, **kwargs):
        destination.write_bytes(b"owned-video-result")

    class ResultProbe:
        async def probe_file(self, path, *, kind):
            return MediaInfo(kind="video", duration_seconds=3, size_bytes=18)

    monkeypatch.setattr(module, "fetch_public_asset", download)
    monkeypatch.setattr(module, "ActualWan3PrimeProbe", ResultProbe)
    await engine.reconcile(task_id)
    done = await engine.status(actor, task_id)
    assert done["status"] == "done" and done["actual_credits"] == "85.5"
    assert (
        "/uploads/kling4/results/" in done["result_url"]
        and "/static/" not in done["result_url"]
    )
    transport.payload["state"] = "fail"
    await engine.reconcile(task_id)
    assert (await engine.status(actor, task_id))["status"] == "done"

    class Bot:
        calls = 0

        async def send_video(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError

    bot = Bot()
    engine.telegram_bot = bot
    with pytest.raises(TimeoutError):
        await engine.deliver(task_id)
    assert (await engine.status(actor, task_id))["status"] == "done"
    await engine.deliver(task_id)
    assert (await engine.status(actor, task_id))["delivery_status"] == "delivered"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_adopt_uses_normalized_snapshot(engine_context):
    from bot import database, db

    engine, actor, transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test", "aspect_ratio": None}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(actor, request, quote["quote_hash"], "adopt-intent")
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE kling4_intents SET status='unknown',provider_task_id=NULL WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    transport.payload["param"] = json.dumps(
        {"input": json.dumps({"prompt": "test", "duration": 5, "resolution": "720p"})}
    )
    adopted = await engine.adopt(actor, result["task_id"], "kie-task")
    assert adopted["status"] == "pending" and transport.calls == 1


@pytest.mark.asyncio
async def test_real_http_auth_and_current_admin_permissions(engine_context):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import kling4_api
    from tests.test_wan3_http_flow import signed_user

    engine, actor, transport = engine_context
    app = web.Application()
    app["kling4_lifecycle"] = engine
    app.router.add_post(
        "/kling4/{action:quote|generate|status|history|recipe|adopt|settings}",
        kling4_api.route,
    )
    async with TestClient(TestServer(app)) as client:
        request = {"mode": "reference", "input": {"prompt": "test"}}
        missing = await client.post("/kling4/quote", json={"recipe": request})
        assert missing.status == 401
        invalid = await client.post(
            "/kling4/quote",
            json={"recipe": request, "init_data": "user=forged", "is_admin": True},
        )
        assert invalid.status == 401
        for action in (
            "quote",
            "generate",
            "status",
            "history",
            "recipe",
            "adopt",
            "settings",
        ):
            denied = await client.post(
                "/kling4/" + action,
                json={
                    "recipe": request,
                    "init_data": signed_user(123123),
                    "is_admin": True,
                },
            )
            assert denied.status == 403, await denied.text()
        quote_response = await client.post(
            "/kling4/quote",
            json={"recipe": request, "init_data": signed_user(actor.telegram_id)},
        )
        assert quote_response.status == 200, await quote_response.text()
        quote = await quote_response.json()
        launch = await client.post(
            "/kling4/generate",
            json={
                "recipe": request,
                "init_data": signed_user(actor.telegram_id),
                "quote_hash": quote["quote_hash"],
                "idempotency_key": "signed-http-intent",
            },
        )
        assert launch.status == 200, await launch.text()
        assert transport.calls == 1


@pytest.mark.asyncio
async def test_startup_wires_delivery_in_webhook_mode(engine_context):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import kling4_api

    engine, _actor, _transport = engine_context
    app = web.Application()
    bot = object()
    app["bot"] = bot
    app["kling4_lifecycle"] = engine
    kling4_api.setup_kling4_routes(app, "/mini-app")
    async with TestClient(TestServer(app)):
        assert engine.telegram_bot is bot
    assert engine.runner is None


@pytest.mark.asyncio
async def test_watchdog_cannot_fail_owned_kling4_intent(engine_context, monkeypatch):
    from bot import database, db
    from bot.services import task_watchdog
    from bot.services.task_watchdog import force_fail_task, get_stuck_tasks

    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)
    engine, actor, _transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(actor, request, quote["quote_hash"], "watchdog-intent")
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE generation_tasks SET created_at=datetime('now','-3 hours') WHERE task_id=?",
            (result["task_id"],),
        )
        row = await (
            await conn.execute(
                "SELECT id FROM generation_tasks WHERE task_id=?", (result["task_id"],)
            )
        ).fetchone()
        await conn.commit()
    stuck = await get_stuck_tasks(minutes=30)
    assert all(t["task_id"] != result["task_id"] for t in stuck)
    # A stale watchdog process must also fail the atomic update guard.
    failed = await force_fail_task(row[0], actor.user_id, 0)
    assert not failed
    assert (await engine.status(actor, result["task_id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_retention_respects_publication(engine_context, tmp_path, monkeypatch):
    from bot import database, db
    from bot.services import kling4_lifecycle as module

    engine, actor, _transport = engine_context
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(
        actor, request, quote["quote_hash"], "retention-intent"
    )
    monkeypatch.chdir(tmp_path)
    module.ROOT.mkdir(parents=True, exist_ok=True)
    path = module.ROOT / "result.mp4"
    path.write_bytes(b"video")
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE kling4_intents SET status='done',delivery_status='delivered',result_path=?,result_url='https://original',created_epoch=0 WHERE task_id=?",
            (str(path), result["task_id"]),
        )
        await conn.execute(
            "UPDATE generation_tasks SET is_public_feed=1 WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    await engine.cleanup_results()
    assert path.exists()
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE generation_tasks SET is_public_feed=0,is_profile_visible=0 WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    await engine.cleanup_results()
    assert (
        not path.exists()
        and (await engine.status(actor, result["task_id"]))["result_url"] is None
    )


@pytest.mark.asyncio
async def test_telegram_editor_modes_quote_and_double_confirm(
    engine_context, monkeypatch
):
    from unittest.mock import AsyncMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from bot.handlers import kling4 as handler

    engine, actor, transport = engine_context
    monkeypatch.setattr(handler, "kling4_lifecycle", engine)
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=actor.telegram_id, user_id=actor.telegram_id),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=actor.telegram_id), answer=AsyncMock()
    )
    await handler.command(message, state)
    recipe = (await state.get_data())["k4_recipe"]
    recipe["input"]["prompt"] = "A quiet landscape"
    await handler.save(state, recipe)
    query = SimpleNamespace(
        from_user=message.from_user,
        message=message,
        answer=AsyncMock(),
        data="k4:new:image",
    )
    await handler.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["elements"][0][
        "name"
    ] == "Hero1"
    query.data = "k4:mode"
    await handler.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["mode"] == "keyframe"
    await handler.callback(query, state)
    assert (await state.get_data())["k4_recipe"]["input"]["elements"][0][
        "name"
    ] == "Hero1"
    query.data = "k4:remove:element:0"
    await handler.callback(query, state)
    query.data = "k4:quote"
    await handler.callback(query, state)
    assert (await state.get_data())["k4_quote"]["cost"] == 0
    query.data = "k4:launch"
    await handler.callback(query, state)
    await handler.callback(query, state)
    assert transport.calls == 1
    denied = SimpleNamespace(from_user=SimpleNamespace(id=123123), answer=AsyncMock())
    before = await state.get_data()
    await handler.command(denied, state)
    assert await state.get_data() == before and transport.calls == 1


@pytest.mark.asyncio
async def test_real_owned_upload_quote_and_foreign_media_denied(
    engine_context, monkeypatch
):
    import asyncio
    import io

    from aiohttp import FormData, web
    from aiohttp.test_utils import TestClient, TestServer
    from PIL import Image

    from bot import kling4_api
    from bot.config import config
    from bot.handlers import miniapp_regression_safety as safety
    from bot.services.wan3_prime_storage import ActualWan3PrimeProbe, wan3_prime_storage
    from tests.test_wan3_http_flow import signed_user

    engine, actor, _transport = engine_context
    engine.probe = ActualWan3PrimeProbe(wan3_prime_storage)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://owned.example.test")
    image = io.BytesIO()
    Image.new("RGB", (400, 400), "blue").save(image, format="PNG")
    raw = image.getvalue()
    app = web.Application()
    app["kling4_lifecycle"] = engine
    # Install the actual production add_post guard, including its eager payload
    # read. A bare /kling4 test route misses this /mini-app/api integration.
    original = safety._ORIGINAL_ADD_POST or web.UrlDispatcher.add_post
    monkeypatch.setattr(safety, "_ORIGINAL_ADD_POST", original)
    monkeypatch.setattr(web.UrlDispatcher, "add_post", safety._guarded_add_post)
    kling4_api.setup_kling4_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        auth = {"init_data": signed_user(actor.telegram_id)}
        init = await client.post(
            "/mini-app/api/kling4/media/init",
            json={
                **auth,
                "kind": "image",
                "filename": "frame.png",
                "size": len(raw),
                "content_type": "image/png",
            },
        )
        assert init.status == 200, await init.text()
        upload_id = (await init.json())["upload_id"]
        form = FormData()
        form.add_field("upload_id", upload_id)
        form.add_field("index", "0")
        form.add_field("total", "1")
        form.add_field("chunk", raw, filename="frame.png", content_type="image/png")
        uploaded = await asyncio.wait_for(
            client.post(
                "/mini-app/api/kling4/media/chunk",
                data=form,
                headers={"X-Telegram-Init-Data": auth["init_data"]},
            ),
            timeout=3,
        )
        assert uploaded.status == 200, await uploaded.text()
        complete = await client.post(
            "/mini-app/api/kling4/media/complete", json={**auth, "upload_id": upload_id}
        )
        assert complete.status == 200, await complete.text()
        url = (await complete.json())["url"]
        recipe = {
            "mode": "keyframe",
            "input": {
                "prompt": "Start from @first_frame",
                "duration": 3,
                "first_frame_url": url,
            },
        }
        quote = await client.post(
            "/mini-app/api/kling4/quote", json={**auth, "recipe": recipe}
        )
        assert quote.status == 200, await quote.text()
        # Admin status does not grant another administrator ownership of private media.
        with pytest.raises(Wan3PrimeValidationError):
            await engine.quote(replace_actor(actor, user_id=actor.user_id + 1), recipe)

        # Direct registration must retain the authoritative ban check as well
        # as the admin gate; bypassing eager body reads cannot bypass auth.
        from bot import database

        async def banned(_telegram_id):
            return True

        monkeypatch.setattr(database, "is_user_banned", banned)
        for action in ("quote", "media/init", "media/chunk"):
            denied = await client.post(
                "/mini-app/api/kling4/" + action,
                json={**auth, "recipe": recipe},
                headers={"X-Telegram-Init-Data": auth["init_data"]},
            )
            assert denied.status == 403, await denied.text()


@pytest.mark.asyncio
async def test_retention_serializes_with_publication_and_skips_full_protected_page(
    engine_context, tmp_path, monkeypatch
):
    import asyncio

    from bot import database, db
    from bot.services import kling4_lifecycle as module
    from bot.services.wan3_prime_result_retention import lock_publication

    engine, actor, _transport = engine_context
    monkeypatch.chdir(tmp_path)
    module.ROOT.mkdir(parents=True, exist_ok=True)
    request = {"mode": "reference", "input": {"prompt": "test"}}
    quote = await engine.quote(actor, request)
    result = await engine.launch(
        actor, request, quote["quote_hash"], "publication-lock"
    )
    path = module.ROOT / "protected.mp4"
    path.write_bytes(b"original")
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute(
            "UPDATE kling4_intents SET status='done',delivery_status='delivered',created_epoch=0,result_path=?,result_url='https://original' WHERE task_id=?",
            (str(path), result["task_id"]),
        )
        await conn.execute(
            "UPDATE generation_tasks SET status='completed',is_public_feed=0,is_profile_visible=0 WHERE task_id=?",
            (result["task_id"],),
        )
        await conn.commit()
    async with db.connect(database.DATABASE_PATH) as publication:
        await lock_publication(publication, result["task_id"], actor.user_id)
        cleanup = asyncio.create_task(engine.cleanup_results())
        await asyncio.sleep(0.02)
        assert not cleanup.done(), "Expiry must wait for the publication transaction"
        await publication.execute(
            "UPDATE generation_tasks SET is_public_feed=1 WHERE task_id=?",
            (result["task_id"],),
        )
        await publication.commit()
    await cleanup
    assert path.exists()
    # A full page of protected results cannot starve a later private original.
    async with db.connect(database.DATABASE_PATH) as conn:
        for index in range(20):
            task = "kling4_protected_" + str(index)
            await conn.execute(
                "INSERT INTO kling4_intents (task_id,user_id,telegram_id,idempotency_key,request_hash,recipe,quote,snapshot,provider_model,status,delivery_status,created_epoch,result_path) VALUES (?,?,?,?,?,?,?,?,?,'done','delivered',0,?)",
                (
                    task,
                    actor.user_id,
                    actor.telegram_id,
                    task,
                    "hash",
                    "{}",
                    "{}",
                    "{}",
                    "model",
                    str(path),
                ),
            )
            await conn.execute(
                "INSERT INTO generation_tasks (user_id,telegram_id,task_id,type,preset_id,model,status,is_public_feed) VALUES (?,?,?,'video','kling_4','kling_4','completed',1)",
                (actor.user_id, actor.telegram_id, task),
            )
        private = module.ROOT / "private.mp4"
        private.write_bytes(b"private")
        await conn.execute(
            "INSERT INTO kling4_intents (task_id,user_id,telegram_id,idempotency_key,request_hash,recipe,quote,snapshot,provider_model,status,delivery_status,created_epoch,result_path) VALUES ('kling4_private',?,?, 'private','hash','{}','{}','{}','model','done','delivered',0,?)",
            (actor.user_id, actor.telegram_id, str(private)),
        )
        await conn.commit()
    await engine.cleanup_results()
    assert path.exists() and not private.exists()


@pytest.mark.asyncio
async def test_nonadmin_denied_before_user_creation_or_channel_probe(monkeypatch):
    from unittest.mock import AsyncMock

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import kling4_api, miniapp
    from tests.test_wan3_http_flow import signed_user

    context = AsyncMock(
        side_effect=AssertionError("Nonadmin must be denied before user context")
    )
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    app = web.Application()
    app.router.add_post("/kling4/{action:quote}", kling4_api.route)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/kling4/quote", json={"init_data": signed_user(123123), "is_admin": True}
        )
        assert response.status == 403
    context.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_parallel_uploads_preserve_both_materials_and_cancel_stale_session(
    engine_context, monkeypatch
):
    import asyncio
    from unittest.mock import AsyncMock

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    from bot import wan3_prime_api
    from bot.handlers import kling4 as handler

    _engine, actor, _transport = engine_context
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=actor.telegram_id, user_id=actor.telegram_id),
    )
    message = lambda file_id: SimpleNamespace(
        from_user=SimpleNamespace(id=actor.telegram_id),
        answer=AsyncMock(),
        text=None,
        document=SimpleNamespace(
            file_id=file_id, file_name=file_id + ".png", file_size=100
        ),
        voice=None,
        photo=None,
        bot=object(),
    )
    await handler.command(message("command"), state)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=actor.telegram_id),
        message=message("menu"),
        answer=AsyncMock(),
        data="k4:media:image_urls",
    )
    await handler.callback(query, state)
    original = state.get_data

    async def yielding_read():
        value = await original()
        await asyncio.sleep(0)
        return value

    monkeypatch.setattr(state, "get_data", yielding_read)

    async def upload(**kwargs):
        await asyncio.sleep(0.01)
        return {"url": "https://owned/" + kwargs["file_id"] + ".png"}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", upload)
    await asyncio.gather(
        handler.media(message("one"), state), handler.media(message("two"), state)
    )
    assert set((await state.get_data())["k4_recipe"]["input"]["image_urls"]) == {
        "https://owned/one.png",
        "https://owned/two.png",
    }
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(**kwargs):
        started.set()
        await release.wait()
        return {"url": "https://owned/stale.png"}

    monkeypatch.setattr(wan3_prime_api, "store_telegram_wan3_prime_media", delayed)
    pending = asyncio.create_task(handler.media(message("stale"), state))
    await started.wait()
    await handler.command(message("new-session"), state)
    await handler.callback(query, state)
    release.set()
    await pending
    assert not (await state.get_data())["k4_recipe"]["input"].get("image_urls")
