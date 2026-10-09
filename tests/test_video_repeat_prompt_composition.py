"""Synthetic repeat edits must reach providers with the private base intact."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp, trend_task_privacy
from bot.creator_tariff import VideoQuote
from bot.handlers import miniapp_video_continuity_compat as continuity
from bot.handlers import seedance_25_public_release as public
from bot.services.gemini_omni_service import gemini_omni_service
from bot.services.remix_prompt import compose_feed_remix_prompt
from bot.services.seedance_25_service import seedance_25_service
from bot.services.seedance_service import seedance_service

BASE = "SYNTHETIC PRIVATE BASE: cinematic forest, steady camera, blue coat"


class Request(dict):
    def __init__(self, body):
        super().__init__()
        self.app = {}
        self.can_read_body = True
        self.query = {}
        self.match_info = {}
        self.headers = {}
        self._read_bytes = json.dumps({"init_data": "signed", **body}).encode()

    async def json(self):
        return json.loads(self._read_bytes)


@pytest.fixture
async def repeat_endpoint(monkeypatch):
    """Real continuity, endpoint, persistence and adapter; only transport is fake."""
    user = await database.get_or_create_user(882201)
    source = {
        "id": 42, "user_id": user.id + 1, "type": "video", "status": "completed",
        "is_public_feed": True, "model": "seedance_2", "prompt": BASE,
        "duration": 5, "aspect_ratio": "16:9",
        "feed_repeat_reference_selection": {"version": 1, "images": [], "videos": []},
        "request_data": {"v_type": "text", "seedance25_scenario": "text"},
    }
    card = {"id": 42, "gen_type": "video", "model": "seedance_2"}
    source_read = AsyncMock(side_effect=lambda *_args: dict(source))
    card_read = AsyncMock(side_effect=lambda *_args, **_kwargs: dict(card) if card else None)
    async def quote(_actor, model, duration=5, quality=None, *_args, **_kwargs):
        return VideoQuote(model, duration, quality, 1, 1, "standard", 1, 1, "synthetic")

    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(user.telegram_id, {"user": user})))
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", card_read)
    monkeypatch.setattr(miniapp, "get_generation_task_payload", source_read)
    monkeypatch.setattr(continuity, "get_generation_task_payload", source_read)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "quote_video_for_actor", quote)
    monkeypatch.setattr(public, "quote_video_for_actor", quote)
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _actor: False)
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(return_value=True))
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "add_credits", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "credit_feed_prompt_repeat", AsyncMock())
    # Durable reservation races have their own suite; preserve actual task storage here.
    monkeypatch.setattr(continuity, "reserve_video_repeat_launch", AsyncMock(return_value=(None, None)))
    transport = AsyncMock(return_value={"task_id": "synthetic-provider-task", "success": True})
    for service in (seedance_service, seedance_25_service, gemini_omni_service):
        monkeypatch.setattr(service, "kie_key", "synthetic-test-key")
        monkeypatch.setattr(service, "_kie_post", transport)
    return SimpleNamespace(call=miniapp.miniapp_generate_video, source=source, user=user,
                           card=card, source_read=source_read, transport=transport, debit=debit)


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
@pytest.mark.parametrize("edit", ["", "   ", "12345", "Change only the coat to red", BASE])
@pytest.mark.parametrize("kind", ["typed", "legacy", "owner"])
@pytest.mark.parametrize("scope", ["feed", "profile"])
async def test_private_base_and_edit_reach_actual_provider_payload(
    repeat_endpoint, model, edit, kind, scope, caplog,
):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = model
    entry.source["is_public_feed"] = scope == "feed"
    entry.source["is_profile_visible"] = scope == "profile"
    if kind == "legacy":
        entry.source["feed_repeat_reference_selection"] = None
    elif kind == "owner":
        entry.source["user_id"] = entry.user.id
    request = Request({"source_feed_gen_id": 42, "v_model": model, "prompt": edit})
    response = await entry.call(request)
    assert response.status == 200, response.text
    entry.transport.assert_awaited_once()
    endpoint, payload = entry.transport.await_args.args
    assert endpoint == "/api/v1/jobs/createTask"
    expected = compose_feed_remix_prompt(BASE, edit)
    assert payload["input"]["prompt"] == expected
    entry.debit.assert_awaited_once()
    task = await database.get_generation_task_payload("synthetic-provider-task")
    assert task["prompt"] == expected
    assert task["source_feed_gen_id"] == 42
    assert task["action_type"] == "repeat"
    assert BASE not in response.text and BASE not in caplog.text
    detail = await miniapp.miniapp_task_detail(Request({"task_id": "synthetic-provider-task"}))
    assert detail.status == 200, detail.text
    assert BASE not in detail.text
    assert json.loads(detail.text)["task"]["prompt_hidden"] is True


@pytest.mark.parametrize("model,limit,duration", [
    ("seedance_2", 20_000, 5), ("seedance_2_5", 30_000, 5),
    ("gemini_omni_video", 4_000, 6),
])
@pytest.mark.parametrize("overflow", [0, 1])
async def test_composed_repeat_must_fit_without_truncating_edits(
    repeat_endpoint, model, limit, duration, overflow, caplog,
):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = model
    entry.source["duration"] = duration
    changes = "Keep the smile 😊"
    overhead = len(compose_feed_remix_prompt("Ж", changes)) - 1
    entry.source["prompt"] = "Ж" * (limit - overhead + overflow)
    response = await entry.call(Request({"source_feed_gen_id": 42, "v_model": model, "prompt": changes}))
    if overflow:
        assert response.status == 400, response.text
        assert json.loads(response.text)["code"] == "repeat_prompt_too_long"
        entry.debit.assert_not_awaited()
        entry.transport.assert_not_awaited()
        assert str(limit) not in response.text
    else:
        assert response.status == 200, response.text
        assert entry.transport.await_args.args[1]["input"]["prompt"] == compose_feed_remix_prompt(entry.source["prompt"], changes)
        entry.debit.assert_awaited_once()
    assert entry.source["prompt"] not in response.text
    assert entry.source["prompt"] not in caplog.text


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
@pytest.mark.parametrize("kind", ["typed", "legacy", "owner"])
@pytest.mark.parametrize("failure", ["rejected", "exception"])
async def test_repeat_provider_failures_do_not_expose_private_base(
    repeat_endpoint, model, kind, failure, caplog,
):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = model
    if kind == "legacy":
        entry.source["feed_repeat_reference_selection"] = None
    elif kind == "owner":
        entry.source["user_id"] = entry.user.id
    if failure == "exception":
        entry.transport.side_effect = RuntimeError(BASE)
    else:
        entry.transport.return_value = {"error": BASE}
    response = await entry.call(Request({"source_feed_gen_id": 42, "v_model": model, "prompt": "12345"}))
    assert response.status in (500, 502), response.text
    entry.transport.assert_awaited_once()
    assert BASE not in response.text
    assert BASE not in caplog.text


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
async def test_regular_video_prompt_remains_an_explicit_replacement(repeat_endpoint, model):
    entry = repeat_endpoint
    response = await entry.call(Request({"v_model": model, "prompt": "Entirely new user prompt"}))
    assert response.status == 200, response.text
    assert entry.transport.await_args.args[1]["input"]["prompt"] == "Entirely new user prompt"
    entry.source_read.assert_not_awaited()


@pytest.mark.parametrize("unavailable", ["card", "task", "prompt"])
@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
async def test_unavailable_base_never_launches_the_edit_alone(repeat_endpoint, model, unavailable, caplog):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = model
    if unavailable == "card":
        entry.card.clear()
    elif unavailable == "task":
        entry.source_read.side_effect = None
        entry.source_read.return_value = None
    else:
        entry.source["prompt"] = ""
    response = await entry.call(Request({"source_feed_gen_id": 42, "v_model": model, "prompt": "12345"}))
    assert response.status in (400, 404), response.text
    entry.transport.assert_not_awaited()
    entry.debit.assert_not_awaited()
    assert BASE not in response.text and BASE not in caplog.text


@pytest.mark.parametrize("adapter", ["shared", "omni"])
@pytest.mark.parametrize("failure", ["exception", "invalid_json", "http_error"])
async def test_provider_transport_never_logs_echoed_private_prompt(monkeypatch, caplog, adapter, failure):
    import aiohttp

    from bot.services.gemini_omni_service import GeminiOmniService
    from bot.services.kling_service import KlingService

    class Response:
        status = 400

        async def __aenter__(self):
            if failure == "exception":
                raise RuntimeError(BASE)
            return self

        async def __aexit__(self, *_args):
            return False

        async def text(self):
            return BASE if failure == "invalid_json" else json.dumps({"message": BASE})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: Session())
    service = (KlingService if adapter == "shared" else GeminiOmniService)(kie_key="synthetic-test-key")
    method = service._kie_post if adapter == "shared" else service._kie_post_once
    await method("/synthetic", {"input": {"prompt": BASE}})
    assert BASE not in caplog.text


@pytest.mark.parametrize("status", [500, BASE])
async def test_omni_retry_log_never_echoes_private_prompt(monkeypatch, caplog, status):
    import importlib

    module = importlib.import_module("bot.services.gemini_omni_service")

    service = module.GeminiOmniService(kie_key="synthetic-test-key")
    monkeypatch.setattr(service, "_kie_post_once", AsyncMock(side_effect=[
        {"error": "api_error", "status_code": status, "code": 500, "message": BASE},
        {"status_code": 200, "code": 200, "data": {"taskId": "synthetic"}},
    ]))
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    await service._kie_post_raw("/synthetic", {"input": {"prompt": BASE}})
    assert BASE not in caplog.text


@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
async def test_repeat_prelaunch_exception_is_redacted_by_installed_dispatch(
    repeat_endpoint, model, monkeypatch, caplog,
):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = model
    entry.source["feed_repeat_reference_selection"] = None
    failing_quote = AsyncMock(side_effect=RuntimeError(BASE))
    monkeypatch.setattr(miniapp, "quote_video_for_actor", failing_quote)
    monkeypatch.setattr(public, "quote_video_for_actor", failing_quote)
    response = await entry.call(Request({"source_feed_gen_id": 42, "v_model": model, "prompt": "12345"}))
    assert response.status == 500
    entry.transport.assert_not_awaited()
    entry.debit.assert_not_awaited()
    assert BASE not in response.text and BASE not in caplog.text


@pytest.mark.parametrize("typed", [False, True])
async def test_repeat_validation_errors_cannot_echo_private_base(
    repeat_endpoint, typed, monkeypatch, caplog,
):
    entry = repeat_endpoint
    entry.source["model"] = entry.card["model"] = "seedance_2_5"
    if not typed:
        entry.source["feed_repeat_reference_selection"] = None
    monkeypatch.setattr(public, "_validate_public_payload", AsyncMock(side_effect=ValueError(BASE)))
    response = await entry.call(Request({"source_feed_gen_id": 42, "v_model": "seedance_2_5", "prompt": "12345"}))
    assert response.status == 400
    entry.transport.assert_not_awaited()
    entry.debit.assert_not_awaited()
    assert BASE not in response.text and BASE not in caplog.text
