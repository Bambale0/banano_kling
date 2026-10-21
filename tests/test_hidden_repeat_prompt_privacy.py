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
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(
        return_value=(owner.telegram_id, {"user": owner})))
    response = await miniapp.miniapp_task_detail(Request("repeat-privacy"))
    assert response.status == 200
    task = json.loads(response.text)["task"]
    assert task["prompt"] == SECRET
    assert task["prompt_hidden"] is False


@pytest.mark.asyncio
async def test_authored_original_stays_publishable_after_matching_trend_is_approved(monkeypatch):
    from bot import db as db_backend

    owner = await make_task()
    monkeypatch.setattr(miniapp, 'DATABASE_PATH', database.DATABASE_PATH)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO user_prompts (author_id,title,prompt_text,tags,status,is_public) VALUES (?,?,?,?,?,?)",
            (owner.id, 'Synthetic original trend', SECRET, '["trend"]', 'approved', 1),
        )
        await db.commit()
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(owner.telegram_id, {'user': owner})))
    response = await miniapp.miniapp_task_detail(Request('repeat-privacy'))
    task = json.loads(response.text)['task']
    assert response.status == 200
    assert task['prompt'] == SECRET
    assert task['prompt_hidden'] is False
    assert task['prompt_actions_allowed'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['feed', 'profile'])
@pytest.mark.parametrize('action,markers', [
    ('trend', {'private_recipe': True}),
    ('repeat', {'source_feed_gen_id': 420, 'parent_generation_id': 421}),
    ('remix', {'source_feed_gen_id': 420, 'private_repeat_reference_images': ['https://example.test/hidden-author.png']}),
])
async def test_completed_private_result_can_publish_without_disclosing_recipe(scope, action, markers):
    from bot import db as db_backend

    owner = await make_task(action, markers)
    if markers.get('source_feed_gen_id'):
        async with db_backend.connect(database.DATABASE_PATH) as db:
            await db.execute('UPDATE generation_tasks SET source_feed_gen_id=?,parent_generation_id=? WHERE task_id=?',
                             (markers['source_feed_gen_id'], markers.get('parent_generation_id'), 'repeat-privacy'))
            await db.commit()
    card = await database.share_to_feed('repeat-privacy', owner.id, publication_scope=scope, prompt_visible=True)
    assert card is not None
    fetch = database.get_feed_generation_card if scope == 'feed' else database.get_profile_generation_card
    public = await fetch(card['id'])
    assert public is not None
    assert public['prompt_hidden'] is True
    assert public['prompt'] == ''
    assert SECRET not in json.dumps(public)
    assert 'hidden-author.png' not in json.dumps(public)
    assert public.get('reference_images', []) == []
    assert await database.share_to_feed('repeat-privacy', owner.id + 1000, publication_scope=scope) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['feed', 'profile'])
@pytest.mark.parametrize('action', ['trend', 'remix', 'legacy'])
@pytest.mark.parametrize('has_upload', [False, True, 'ancestor'])
async def test_another_user_repeats_a_published_private_result_with_own_files(monkeypatch, scope, action, has_upload):
    hidden = 'https://example.test/synthetic-inherited-author.png'
    own = 'https://example.test/synthetic-viewer.png'
    markers = {'source_reference_images': [hidden]}
    if action != 'legacy':
        markers['private_recipe'] = True
    owner = await make_task(None if action == 'legacy' else action, markers)
    if action == 'legacy':
        from bot import db as db_backend
        curator = await database.get_or_create_user(840003)
        async with db_backend.connect() as db:
            await db.execute('INSERT INTO user_prompts (author_id,title,prompt_text,tags,status,is_public) VALUES (?,?,?,?,?,?)',
                             (curator.id, 'Legacy', SECRET, '["trend"]', 'approved', 1))
            await db.commit()
    viewer = await database.get_or_create_user(840002)
    monkeypatch.setattr(miniapp, 'DATABASE_PATH', database.DATABASE_PATH)
    card = await database.share_to_feed('repeat-privacy', owner.id, publication_scope=scope)
    assert card is not None
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(viewer.telegram_id, {'user': viewer})))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, 'deduct_credits', debit)
    launch = AsyncMock(return_value={'status': 'queued', 'task_id': 'synthetic-next-repeat'})
    monkeypatch.setattr(miniapp, '_start_image_generation_task_lazy', launch)
    monkeypatch.setattr(miniapp, 'touch_saved_references', AsyncMock())
    monkeypatch.setattr(miniapp, '_notify_miniapp_image_task_queued', AsyncMock())
    monkeypatch.setattr(miniapp, '_deliver_miniapp_direct_image_result', AsyncMock())
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', AsyncMock())
    request = Request('repeat-privacy')
    request.json = AsyncMock(return_value={
        'init_data': 'synthetic-signed', 'gen_id': card['id'], 'surface': scope,
        'reference_images': [hidden] if has_upload == 'ancestor' else [own] if has_upload else [],
    })
    response = await miniapp.miniapp_feed_remix(request)
    assert SECRET not in response.text and hidden not in response.text
    if has_upload is True:
        assert response.status == 200, response.text
        assert launch.await_args.kwargs['prompt'] == SECRET
        assert launch.await_args.kwargs['reference_images'] == [own]
        assert launch.await_args.kwargs['private_repeat_reference_images'] == []
        assert launch.await_args.kwargs['parent_generation_id'] == card['id']
        debit.assert_awaited_once()
    else:
        assert response.status == 400, response.text
        launch.assert_not_awaited()
        debit.assert_not_awaited()


@pytest.mark.asyncio
async def test_publishing_private_photo_cannot_grant_inherited_author_inputs():
    hidden = 'https://example.test/synthetic-author.png'
    owner = await make_task('remix', {'source_reference_images': [hidden], 'private_recipe': True})
    with pytest.raises(ValueError, match='чужие'):
        await database.share_to_feed('repeat-privacy', owner.id, repeat_reference_image_indices=[0])
    payload = await database.get_generation_task_payload('repeat-privacy')
    assert not payload['is_public_feed']
    assert database.generation_publication_references(payload) == {'images': [], 'videos': [], 'image_indices': [], 'video_indices': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['feed', 'profile'])
async def test_legacy_foreign_trend_publication_preserves_recipe_privacy(scope):
    from bot import db as db_backend

    owner = await make_task(markers={'source_reference_images': ['https://example.test/legacy-private.png']})
    curator = await database.get_or_create_user(840003)
    async with db_backend.connect() as db:
        await db.execute('INSERT INTO user_prompts (author_id,title,prompt_text,tags,status,is_public) VALUES (?,?,?,?,?,?)',
                         (curator.id, 'Legacy trend', SECRET, '["trend"]', 'approved', 1))
        await db.commit()
    with pytest.raises(ValueError, match='чужие'):
        await database.share_to_feed('repeat-privacy', owner.id, publication_scope=scope, repeat_reference_image_indices=[0])
    card = await database.share_to_feed('repeat-privacy', owner.id, publication_scope=scope,
                                        prompt_visible=True, references_visible=True, reference_image_indices=[0])
    assert card is not None
    assert card['prompt_hidden'] is True and card['prompt'] == ''
    assert card['reference_images'] == []
    assert 'legacy-private.png' not in json.dumps(card)
    stored = await database.get_generation_task_payload('repeat-privacy')
    assert not database.generation_has_private_recipe(stored)  # Classification does not rewrite historical metadata.
    # An already published historical row is protected on card reads too.
    async with db_backend.connect() as db:
        await db.execute('UPDATE generation_tasks SET request_data=? WHERE task_id=?',
                         (json.dumps({'source_reference_images': ['https://example.test/legacy-private.png']}), 'repeat-privacy'))
        await db.commit()
    get_card = database.get_feed_generation_card if scope == 'feed' else database.get_profile_generation_card
    historical = await get_card(card['id'], viewer_user_id=owner.id)
    assert historical['prompt_hidden'] is True and historical['prompt'] == ''
    assert historical['reference_images'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['trend', 'repeat'])
@pytest.mark.parametrize('scope', ['feed', 'profile'])
@pytest.mark.parametrize('has_upload', [False, True])
async def test_private_video_owner_gets_and_uses_replacement_slots(monkeypatch, action, scope, has_upload):
    from bot.handlers import miniapp_video_continuity_compat as continuity

    owner = await database.get_or_create_user(840011)
    hidden, own = 'https://example.test/hidden-author.png', 'https://example.test/own-consumer.png'
    await database.add_generation_task(
        owner.id, owner.telegram_id, 'owned-private-video', 'video', 'seedance_2_5',
        model='seedance_2_5', prompt=SECRET, action_type=action,
        source_feed_gen_id=420 if action == 'repeat' else None,
        request_data={'seedance25_scenario': 'multimodal', 'v_type': 'video', 'reference_images': [hidden]},
    )
    await database.complete_video_task('owned-private-video', 'https://example.test/output.mp4')
    card = await database.share_to_feed('owned-private-video', owner.id, publication_scope=scope)
    assert card is not None
    assert card['repeat_reference_slots']['images'] == [{'index': 0, 'role': 'reference', 'binding': 'upload'}]
    assert hidden not in json.dumps(card)
    monkeypatch.setattr(miniapp, 'DATABASE_PATH', database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(owner.telegram_id, {'user': owner})))
    request = Request('owned-private-video')
    body = {'source_feed_gen_id': card['id'], 'v_model': 'seedance_2_5', 'v_type': 'video',
            'reference_images': [own] if has_upload else []}
    request.json = AsyncMock(return_value=body)
    if has_upload:
        normalized = await continuity._restore_repeat_request(request, body)
        assert normalized['reference_images'] == [own]
        assert normalized['prompt'] == SECRET
        assert hidden not in json.dumps(normalized)
    else:
        with pytest.raises(continuity.VideoRepeatReferenceError):
            await continuity._restore_repeat_request(request, body)


@pytest.mark.asyncio
async def test_private_video_owner_may_explicitly_select_their_existing_saved_photo(monkeypatch):
    from bot.handlers import miniapp_video_continuity_compat as continuity

    owner = await database.get_or_create_user(840021)
    own = f'https://tanyapi.chillcreative.ru/uploads/refs/image/{owner.telegram_id}/synthetic.png'
    await database.add_generation_task(owner.id, owner.telegram_id, 'private-own-photo', 'video', 'seedance_2_5',
        model='seedance_2_5', prompt=SECRET, action_type='trend',
        request_data={'seedance25_scenario': 'multimodal', 'v_type': 'video', 'reference_images': [own]})
    await database.complete_video_task('private-own-photo', 'https://example.test/output.mp4')
    card = await database.share_to_feed('private-own-photo', owner.id)
    monkeypatch.setattr(miniapp, 'DATABASE_PATH', database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(owner.telegram_id, {'user': owner})))
    monkeypatch.setattr(continuity, 'missing_local_upload_sources', lambda _: [])
    request = Request('private-own-photo')
    body = {'source_feed_gen_id': card['id'], 'v_model': 'seedance_2_5', 'v_type': 'video', 'reference_images': [own]}
    normalized = await continuity._restore_repeat_request(request, body)
    assert normalized['reference_images'] == [own]


def test_reference_upload_owner_does_not_trust_external_or_traversal_lookalikes():
    from bot.services.media_input_utils import reference_upload_owner_telegram_id

    assert reference_upload_owner_telegram_id('https://tanyapi.chillcreative.ru/uploads/refs/image/123/file.png') == 123
    assert reference_upload_owner_telegram_id('https://evil.example/uploads/refs/image/123/file.png') is None
    assert reference_upload_owner_telegram_id('/uploads/refs/image/123/../../../other.png') is None


def test_private_profile_photo_repeat_requires_explicit_file_selection():
    own = 'https://tanyapi.chillcreative.ru/uploads/refs/image/840021/synthetic.png'
    card = {'is_mine': True, 'publication_scope': 'profile', 'references_hidden': True}
    source = {'private_recipe': True, 'request_data': {'source_reference_images': [own]}}
    assert miniapp._merge_remix_image_references(card, source, []) == ([], 0)
    assert miniapp._merge_remix_image_references(card, source, [own]) == ([own], 0)
