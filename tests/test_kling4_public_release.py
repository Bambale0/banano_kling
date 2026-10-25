import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.services.kling4_contract import Kling4Error
from bot.services.wan3_prime_media import MediaInfo

RATES = {
    category: {"720p": 4.0, "1080p": 6.0}
    for category in ("reference", "keyframe", "video")
}


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
            duration_seconds=3,
        )


@pytest.fixture
def public_tariff(monkeypatch):
    from bot.services.preset_manager import preset_manager

    config = deepcopy(preset_manager.get_price_config())
    config.setdefault("costs_reference", {}).setdefault("video_models", {})[
        "kling_4"
    ] = {"public_enabled": True, "billing_rates": deepcopy(RATES)}
    monkeypatch.setattr(preset_manager, "get_price_config", lambda: deepcopy(config))
    return config


@pytest.fixture
async def public_engine(tmp_path, monkeypatch, public_tariff):
    from bot import database, db, kling4_tariff
    from bot.services.kling4_lifecycle import Kling4Lifecycle

    monkeypatch.setattr(kling4_tariff, "kling4_public_enabled", lambda: True)
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "app.db"))
    await database.init_db()
    user = await database.get_or_create_user(700001)
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("UPDATE users SET credits=20 WHERE id=?", (user.id,))
        await conn.commit()
    actor = SimpleNamespace(
        user_id=user.id, telegram_id=user.telegram_id, is_admin=False
    )
    return database, actor, Kling4Lifecycle(probe=Probe())


async def credits(database, actor):
    return float((await database.get_or_create_user(actor.telegram_id)).credits)


def recipe():
    return {"mode": "reference", "input": {"prompt": "Public Kling", "duration": 3}}


def test_public_retail_quote_charges_users_and_keeps_admins_free(public_tariff):
    from bot.kling4_tariff import retail_quote

    provider = {
        "tariff": "reference",
        "resolution": "720p",
        "billed_seconds": "3",
    }
    user = retail_quote(provider, is_admin=False)
    admin = retail_quote(provider, is_admin=True)
    assert user["cost"] == user["charge_cost"] == 12
    assert user["profile"] == "retail" and user["admin_free"] is False
    assert admin["cost"] == 12 and admin["charge_cost"] == 0
    assert admin["profile"] == "admin" and admin["admin_free"] is True


def test_public_flag_requires_a_complete_tariff(public_tariff):
    from bot.kling4_tariff import kling4_public_enabled
    from bot.services.preset_manager import preset_manager

    assert kling4_public_enabled()
    public_tariff["costs_reference"]["video_models"]["kling_4"]["billing_rates"].pop(
        "video"
    )
    assert not kling4_public_enabled(price_config=public_tariff)
    public_tariff["costs_reference"]["video_models"]["kling_4"][
        "public_enabled"
    ] = False
    assert not kling4_public_enabled(price_config=public_tariff)
    assert preset_manager.get_price_config()["costs_reference"]["video_models"]


def test_public_catalog_seams_expose_kling4(monkeypatch, public_tariff):
    from bot import kling4_api
    from bot.handlers import video_generation_compat as telegram_catalog

    monkeypatch.setattr(telegram_catalog, "kling4_public_enabled", lambda: True)
    family, _page, _pages, models = telegram_catalog._video_model_page(
        "kling", is_admin=False
    )
    assert family == "kling"
    assert models[0] == "kling_4"
    entry = kling4_api.catalog_entry()
    assert entry["id"] == "kling_4"
    assert entry["admin_only"] is False


@pytest.mark.asyncio
async def test_public_signed_user_can_quote_over_http(public_engine):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import kling4_api
    from tests.test_wan3_http_flow import signed_user

    _database, actor, engine = public_engine
    await engine.init_schema()
    app = web.Application()
    app["kling4_lifecycle"] = engine
    app.router.add_post(
        "/kling4/{action:quote|history}",
        kling4_api.route,
    )
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/kling4/quote",
            json={"recipe": recipe(), "init_data": signed_user(actor.telegram_id)},
        )
        assert response.status == 200, await response.text()
        payload = await response.json()
        assert payload["charge_cost"] == 12
        assert payload["admin_free"] is False


@pytest.mark.asyncio
async def test_signed_bootstrap_obeys_public_flag(public_engine, monkeypatch):
    from bot import creator_tariff_display, miniapp
    from tests.test_wan3_http_flow import signed_user

    _database, actor, _engine = public_engine

    class Request:
        def __init__(self, body):
            self.body = body
            self.can_read_body = True
            self.query = {}
            self.match_info = {}
            self.headers = {}
            self._state = {}
            self.app = {
                "bot": SimpleNamespace(
                    get_me=AsyncMock(
                        return_value=SimpleNamespace(username="synthetic_bot")
                    )
                )
            }

        async def json(self):
            return self.body

        def get(self, key, default=None):
            return self._state.get(key, default)

        def __setitem__(self, key, value):
            self._state[key] = value

    monkeypatch.setattr(
        miniapp, "is_channel_subscription_required", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        miniapp,
        "_cached_bot_me",
        AsyncMock(return_value=SimpleNamespace(username="synthetic_bot")),
    )
    for name in (
        "_fetch_recent_tasks",
        "list_saved_references",
        "get_and_clear_miniapp_notifications",
    ):
        monkeypatch.setattr(miniapp, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(miniapp, "get_partner_overview", AsyncMock(return_value={}))
    monkeypatch.setattr(
        miniapp, "can_attempt_telegram_delivery", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        miniapp, "needs_telegram_bot_start", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        creator_tariff_display,
        "get_actor_tariff",
        AsyncMock(return_value="standard"),
    )

    auth = signed_user(actor.telegram_id)
    for enabled in (True, False):
        monkeypatch.setattr(
            miniapp, "kling4_public_enabled", lambda enabled=enabled: enabled
        )
        response = await miniapp.miniapp_bootstrap(Request({"init_data": auth}))
        assert response.status == 200, response.text
        model_ids = {item["id"] for item in json.loads(response.text)["video_models"]}
        assert ("kling_4" in model_ids) is enabled


@pytest.mark.asyncio
async def test_public_telegram_requires_confirmation_before_launch(
    public_engine, monkeypatch
):
    from bot.handlers import kling4

    _database, actor, _real_engine = public_engine
    quote = {
        "quote_hash": "public-quote",
        "cost": 12,
        "charge_cost": 12,
        "admin_free": False,
        "credit_name": "бананов",
        "credit_emoji": "🍌",
    }
    engine = SimpleNamespace(
        quote=AsyncMock(return_value=quote),
        launch=AsyncMock(return_value={"task_id": "kling4_paid", "status": "pending"}),
    )
    monkeypatch.setattr(kling4, "actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(kling4, "kling4_lifecycle", engine)
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(
            bot_id=1, chat_id=actor.telegram_id, user_id=actor.telegram_id
        ),
    )
    await state.update_data(k4_session="public-session")
    await kling4.save(state, recipe())
    await state.set_state(kling4.Kling4States.editing)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=actor.telegram_id),
        message_id=123,
        answer=AsyncMock(),
    )

    await kling4.launch_prompt(message, state, recipe())
    engine.launch.assert_not_awaited()
    markup = message.answer.call_args.kwargs["reply_markup"]
    assert any(
        button.callback_data == "k4:confirm"
        for row in markup.inline_keyboard
        for button in row
    )

    query = SimpleNamespace(
        data="k4:confirm",
        from_user=message.from_user,
        message=message,
        answer=AsyncMock(),
    )
    await kling4.callback(query, state)
    engine.launch.assert_awaited_once_with(
        actor,
        recipe(),
        quote["quote_hash"],
        f"k4_tg_1_{actor.telegram_id}_123",
    )
    await kling4.callback(query, state)
    assert engine.launch.await_count == 1


@pytest.mark.asyncio
async def test_public_unknown_submission_debits_once_and_never_resubmits(public_engine):
    database, actor, engine = public_engine

    class Transport:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            raise TimeoutError("ambiguous acknowledgement")

    engine.transport = Transport()
    await engine.init_schema()
    quote = await engine.quote(actor, recipe())
    assert quote["cost"] == quote["charge_cost"] == 12
    first = await engine.launch(actor, recipe(), quote["quote_hash"], "public-once")
    second = await engine.launch(actor, recipe(), quote["quote_hash"], "public-once")
    assert first["task_id"] == second["task_id"]
    assert first["status"] == second["status"] == "unknown"
    assert first["charged_credits"] == 12 and first["refunded_credits"] == 0
    assert await credits(database, actor) == 8
    assert engine.transport.calls == 1


@pytest.mark.asyncio
async def test_unknowns_do_not_fill_queue_and_admin_can_audit_refund(public_engine):
    from bot import db

    database, actor, engine = public_engine

    class Transport:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            raise TimeoutError("ambiguous acknowledgement")

    admin = SimpleNamespace(
        user_id=actor.user_id, telegram_id=999999999, is_admin=True
    )
    engine.transport = Transport()
    await engine.init_schema()
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("UPDATE users SET credits=40 WHERE id=?", (actor.user_id,))
        await conn.commit()
    settings, revision = await engine.settings()
    settings["max_active"] = 1
    await engine.update_settings(admin, settings, revision)
    quote = await engine.quote(actor, recipe())
    first = await engine.launch(actor, recipe(), quote["quote_hash"], "unknown-one")
    second = await engine.launch(actor, recipe(), quote["quote_hash"], "unknown-two")
    assert first["status"] == second["status"] == "unknown"
    assert engine.transport.calls == 2
    assert await credits(database, actor) == 16

    resolved = await engine.reject_unknown(
        admin, first["task_id"], "provider_not_created"
    )
    assert resolved["status"] == "failed" and resolved["refunded_credits"] == 12
    with pytest.raises(Kling4Error) as exc:
        await engine.reject_unknown(
            admin, first["task_id"], "provider_not_created"
        )
    assert exc.value.status == 409
    await engine.reject_unknown(admin, second["task_id"], "provider_not_created")
    assert await credits(database, actor) == 40
    async with db.connect(database.DATABASE_PATH) as conn:
        audit = await (
            await conn.execute(
                "SELECT request_data FROM generation_tasks WHERE task_id=?",
                (first["task_id"],),
            )
        ).fetchone()
    resolution = json.loads(audit[0])["kling4_unknown_resolution"]
    assert resolution == {
        "actor_telegram_id": admin.telegram_id,
        "reason": "operator_verified_not_created",
    }


@pytest.mark.asyncio
async def test_public_insufficient_balance_never_creates_or_submits(public_engine):
    from bot import db

    database, actor, engine = public_engine

    class Transport:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            return 200, {"code": 200, "data": {"taskId": "should-not-run"}}

    engine.transport = Transport()
    await engine.init_schema()
    async with db.connect(database.DATABASE_PATH) as conn:
        await conn.execute("UPDATE users SET credits=11 WHERE id=?", (actor.user_id,))
        await conn.commit()
    quote = await engine.quote(actor, recipe())
    with pytest.raises(Kling4Error) as exc:
        await engine.launch(actor, recipe(), quote["quote_hash"], "no-balance")
    assert exc.value.status == 402
    assert await credits(database, actor) == 11
    assert engine.transport.calls == 0
    assert await engine.history(actor) == []


@pytest.mark.asyncio
async def test_public_provider_rejection_refunds_exactly_once(public_engine):
    database, actor, engine = public_engine

    class Transport:
        calls = 0

        async def create(self, model, data):
            self.calls += 1
            return 400, {"code": 400, "msg": "rejected"}

    engine.transport = Transport()
    await engine.init_schema()
    quote = await engine.quote(actor, recipe())
    failed = await engine.launch(actor, recipe(), quote["quote_hash"], "rejected")
    repeated = await engine.launch(actor, recipe(), quote["quote_hash"], "rejected")
    assert failed["status"] == repeated["status"] == "failed"
    assert failed["charged_credits"] == failed["refunded_credits"] == 12
    assert await credits(database, actor) == 20
    assert engine.transport.calls == 1


@pytest.mark.asyncio
async def test_public_async_failure_refunds_exactly_once(public_engine):
    database, actor, engine = public_engine

    class Transport:
        detail_calls = 0

        async def create(self, model, data):
            return 200, {"code": 200, "data": {"taskId": "kie-public"}}

        async def detail(self, task_id):
            self.detail_calls += 1
            return {
                "taskId": "kie-public",
                "model": "kling-4.0/reference-to-video",
                "state": "waiting" if self.detail_calls == 1 else "fail",
            }

    engine.transport = Transport()
    await engine.init_schema()
    quote = await engine.quote(actor, recipe())
    pending = await engine.launch(actor, recipe(), quote["quote_hash"], "async-fail")
    assert await credits(database, actor) == 8
    await engine.reconcile(pending["task_id"])
    assert (await engine.status(actor, pending["task_id"]))["status"] == "pending"
    assert await credits(database, actor) == 8
    await engine.reconcile(pending["task_id"])
    await engine.reconcile(pending["task_id"])
    failed = await engine.status(actor, pending["task_id"])
    assert failed["status"] == "failed"
    assert failed["charged_credits"] == failed["refunded_credits"] == 12
    assert await credits(database, actor) == 20


@pytest.mark.asyncio
async def test_public_success_keeps_charge_and_delivers(
    public_engine, monkeypatch, tmp_path
):
    from bot.config import config
    from bot.services import kling4_lifecycle as module

    database, actor, engine = public_engine

    class Transport:
        async def create(self, model, data):
            return 200, {"code": 200, "data": {"taskId": "kie-public-success"}}

        async def detail(self, task_id):
            return {
                "taskId": task_id,
                "model": "kling-4.0/reference-to-video",
                "state": "success",
                "creditsConsumed": "85.5",
                "resultJson": json.dumps(
                    {"resultUrls": ["https://provider.example/result.mp4"]}
                ),
            }

    async def download(url, *, destination, **kwargs):
        destination.write_bytes(b"public-video-result")

    class ResultProbe:
        async def probe_file(self, path, *, kind):
            return MediaInfo(kind="video", duration_seconds=3, size_bytes=19)

    class Bot:
        calls = 0

        async def send_video(self, *args, **kwargs):
            self.calls += 1

    engine.transport = Transport()
    engine.telegram_bot = Bot()
    await engine.init_schema()
    quote = await engine.quote(actor, recipe())
    pending = await engine.launch(
        actor, recipe(), quote["quote_hash"], "public-success"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "STATIC_BASE_URL", "https://media.example.test")
    monkeypatch.setattr(module, "fetch_public_asset", download)
    monkeypatch.setattr(module, "ActualWan3PrimeProbe", ResultProbe)

    await engine.reconcile(pending["task_id"])
    done = await engine.status(actor, pending["task_id"])
    assert done["status"] == "done"
    assert done["charged_credits"] == 12 and done["refunded_credits"] == 0
    assert await credits(database, actor) == 8
    await engine.deliver(pending["task_id"])
    assert engine.telegram_bot.calls == 1
    assert (await engine.status(actor, pending["task_id"]))[
        "delivery_status"
    ] == "delivered"
