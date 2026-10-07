"""Hidden recipes stay private at Mini App and Telegram repeat boundaries."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import database, miniapp, trend_task_privacy
from bot.handlers import generation

repeat_compat = importlib.import_module("bot.handlers.repeat_result_compat")
SECRET = "SYNTHETIC PRIVATE RECIPE"
MARKERS = [
    pytest.param("trend", {}, id="trend-action"),
    pytest.param(None, {"prompt_hidden": True}, id="request-hidden"),
    pytest.param(None, {"prompt_actions_allowed": False}, id="request-actions-disabled"),
    pytest.param(None, {"private_recipe": True}, id="request-private-recipe"),
]


class Request(dict):
    def __init__(self, task_id):
        super().__init__()
        self.app = {}
        self.can_read_body = True
        self.query = {}
        self.match_info = {}
        self.headers = {}
        self.task_id = task_id

    async def json(self):
        return {"init_data": "signed", "task_id": self.task_id}


async def make_task(action_type=None, markers=None):
    owner = await database.get_or_create_user(840001)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "repeat-privacy", "image", "banana_pro",
        model="banana_pro", prompt=SECRET, action_type=action_type,
        request_data={"prompt": SECRET, "effective_prompt": SECRET,
                      "img_service": "banana_pro", **(markers or {})},
    )
    await database.complete_video_task("repeat-privacy", "https://example.test/result.png")
    return owner


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type,markers", MARKERS)
async def test_task_detail_redacts_explicit_private_recipe(monkeypatch, action_type, markers):
    owner = await make_task(action_type, markers)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner})))
    response = await miniapp.miniapp_task_detail(Request("repeat-privacy"))
    assert response.status == 200
    assert SECRET not in response.text
    task = json.loads(response.text)["task"]
    assert task["prompt_hidden"] is True
    assert task["prompt_actions_allowed"] is False
    assert task["request_data"]["img_service"] == "banana_pro"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["feed", "profile"])
@pytest.mark.parametrize("action_type,markers", MARKERS)
async def test_published_card_cannot_unhide_private_recipe(scope, action_type, markers):
    owner = await make_task(action_type, markers)
    card = await database.share_to_feed(
        "repeat-privacy", owner.id, prompt_visible=True, publication_scope=scope,
    )
    assert card is not None
    for viewer_id in (owner.id, None):
        get_card = (database.get_feed_generation_card if scope == "feed"
                    else database.get_profile_generation_card)
        result = await get_card(card["id"], viewer_user_id=viewer_id)
        assert result is not None
        assert result["prompt_hidden"] is True
        assert result["prompt"] == ""
        assert SECRET not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_prefix", ["repeat_image_", "repeat_result_"])
@pytest.mark.parametrize("action_type,markers", MARKERS + [
    pytest.param(None, {"prompt_hidden": False, "prompt_actions_allowed": True},
                 id="ordinary-own-prompt"),
])
async def test_repeat_callbacks_respect_recipe_privacy(callback_prefix, action_type, markers):
    owner = await make_task(action_type, markers)
    callback = MagicMock(spec=types.CallbackQuery)
    callback.data = callback_prefix + "repeat-privacy"
    callback.from_user = SimpleNamespace(id=owner.telegram_id)
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=types.Message)
    callback.message.answer = AsyncMock()
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(
        bot_id=1, chat_id=owner.telegram_id, user_id=owner.telegram_id,
    ))
    handler = (generation.repeat_image_generation if callback_prefix == "repeat_image_"
               else repeat_compat.repeat_result_compat)
    await handler(callback, state)
    callback.data = "repeat_prompt_repeat-privacy"
    await generation.repeat_image_wait_for_prompt(callback, state)
    data = await state.get_data()
    sent = "\n".join(call.args[0] for call in callback.message.answer.await_args_list)
    hidden = not (markers.get("prompt_hidden") is False)
    assert data["repeat_prompt_hidden"] is hidden
    assert (SECRET in sent) is not hidden
    # The server retains the recipe for repeating without sending it to Telegram.
    assert data["repeat_prompt"] == SECRET


@pytest.mark.asyncio
async def test_task_detail_preserves_ordinary_own_prompt(monkeypatch):
    owner = await make_task(markers={"prompt_hidden": False, "prompt_actions_allowed": True})
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner})))
    response = await miniapp.miniapp_task_detail(Request("repeat-privacy"))
    assert response.status == 200
    task = json.loads(response.text)["task"]
    assert task["prompt"] == SECRET
    assert task["prompt_hidden"] is False
    assert task["request_data"]["prompt"] == SECRET


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type,markers", MARKERS)
async def test_direct_bootstrap_redacts_private_history(monkeypatch, action_type, markers):
    owner = await make_task(action_type, markers)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "ordinary-history", "image", "banana_pro",
        prompt="My visible original prompt",
    )
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner, "payload": {"user": {}}})))
    monkeypatch.setattr(miniapp, "_cached_bot_me", AsyncMock(
        return_value=SimpleNamespace(username="synthetic_test_bot")))
    response = await miniapp.miniapp_bootstrap(Request("repeat-privacy"))
    assert response.status == 200
    assert SECRET not in response.text
    tasks = {task["task_id"]: task for task in json.loads(response.text)["recent_tasks"]}
    assert tasks["repeat-privacy"]["prompt_hidden"] is True
    assert tasks["repeat-privacy"]["prompt_actions_allowed"] is False
    assert tasks["ordinary-history"]["prompt_preview"] == "My visible original prompt"
    assert tasks["ordinary-history"]["prompt_hidden"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("request_data", [
    {"prompt_hidden": "true", "prompt": SECRET},
    {"prompt_actions_allowed": 0, "prompt": SECRET},
    {"prompt_hidden": "invalid-marker", "prompt": SECRET},
    json.dumps({"prompt_actions_allowed": False, "prompt": SECRET}),
])
async def test_payload_only_marker_is_fail_closed_without_stored_task(monkeypatch, request_data):
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    payload = {"task": {
        "task_id": "not-yet-stored", "prompt": SECRET, "request_data": request_data,
    }}
    result = await trend_task_privacy.sanitize_task_api_payload(payload)
    assert SECRET not in json.dumps(result)
    assert result["task"]["prompt_hidden"] is True
    assert result["task"]["prompt_actions_allowed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("markers", [
    {"prompt_hidden": "false", "prompt_actions_allowed": "true"},
    {"prompt_hidden": 0, "prompt_actions_allowed": 1},
])
async def test_legacy_visible_flags_preserve_ordinary_owner_prompt(monkeypatch, markers):
    owner = await make_task(markers=markers)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner})))
    response = await miniapp.miniapp_task_detail(Request("repeat-privacy"))
    assert response.status == 200
    task = json.loads(response.text)["task"]
    assert task["prompt"] == SECRET
    assert task["prompt_hidden"] is False
