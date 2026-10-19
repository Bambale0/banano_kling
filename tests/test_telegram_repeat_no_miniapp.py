"""Telegram repeat routing stays native; no real Telegram/provider requests."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import database
from bot.handlers import generation
from bot.states import GenerationStates

SECRET = 'Synthetic hidden source recipe'
REFERENCE = 'https://example.test/synthetic-own-reference.png'
TASK_ID = 'native-repeat-source'


async def published_context(monkeypatch, *, scope='feed', rollout='all', model='banana_pro', kind='image'):
    owner = await database.get_or_create_user(840051)
    request = {'img_service': model, 'img_ratio': '9:16', 'img_quality': '2K',
               'prompt': SECRET, 'prompt_hidden': True,
               'source_reference_images': [REFERENCE], 'reference_images': [REFERENCE]}
    await database.add_generation_task(owner.id, owner.telegram_id, TASK_ID, kind, model,
        model=model, prompt=SECRET, cost=10, request_data=request)
    await database.complete_video_task(TASK_ID, 'https://example.test/synthetic-result.png')
    monkeypatch.setattr(database, '_is_feed_result_url_available', lambda *_: True)
    card = await database.share_to_feed(TASK_ID, owner.id, prompt_visible=False,
        references_visible=False, publication_scope=scope)
    assert card is not None
    await database.set_bot_setting('smart_repeat_rollout', json.dumps({
        'enabled': rollout == 'all',
        'telegram_ids': [owner.telegram_id] if rollout == 'pilot' else [],
    }))
    task = await database.get_task_by_id(TASK_ID)
    monkeypatch.setattr(generation, '_available_reference_images', lambda refs: (refs, []))
    monkeypatch.setattr(generation.config, 'is_admin', lambda _: False)
    debit = AsyncMock(return_value=True)
    launch = AsyncMock(return_value={'status': 'queued', 'task_id': 'synthetic-repeat-result'})
    monkeypatch.setattr(generation, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(generation, 'deduct_credits', debit)
    monkeypatch.setattr(generation, '_start_image_generation_task', launch)
    monkeypatch.setattr(generation, 'credit_feed_prompt_repeat', AsyncMock())
    callback = MagicMock(spec=types.CallbackQuery)
    callback.from_user = SimpleNamespace(id=owner.telegram_id)
    callback.answer = AsyncMock()
    callback.bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='synthetic_test_bot')))
    callback.message = MagicMock(spec=types.Message)
    callback.message.answer = AsyncMock(return_value=SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock()))
    callback.message.edit_text = AsyncMock()
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(
        bot_id=1, chat_id=owner.telegram_id, user_id=owner.telegram_id))
    return SimpleNamespace(owner=owner, task=task, card=card, callback=callback,
                           state=state, debit=debit, launch=launch)


def assert_no_handoff(ctx):
    ctx.callback.bot.get_me.assert_not_awaited()
    sent = str(ctx.callback.message.answer.await_args_list)
    assert 'подписанные поля' not in sent
    assert 'Mini App' not in sent
    assert SECRET not in sent
    for call in ctx.callback.message.answer.await_args_list:
        keyboard = call.kwargs.get('reply_markup')
        if keyboard:
            assert all(not button.url and not button.web_app
                       for row in keyboard.inline_keyboard for button in row)


@pytest.mark.asyncio
@pytest.mark.parametrize('rollout', ['all', 'pilot', 'off'])
@pytest.mark.parametrize('scope', ['feed', 'profile'])
@pytest.mark.parametrize('entry', ['direct', 'numeric', 'legacy'])
async def test_published_photo_repeat_opens_in_chat_before_any_charge(monkeypatch, rollout, scope, entry):
    ctx = await published_context(monkeypatch, rollout=rollout, scope=scope, model='seedream_5_pro')
    ctx.callback.data = ('repeat_result_' if entry == 'legacy' else 'repeat_image_') + (
        str(ctx.card['id']) if entry == 'numeric' else TASK_ID)
    handler = (importlib.import_module('bot.handlers.repeat_result_compat').repeat_result_compat
               if entry == 'legacy' else generation.repeat_image_generation)
    await handler(ctx.callback, ctx.state)
    data = await ctx.state.get_data()
    expected_id = str(ctx.card['id']) if entry == 'numeric' else TASK_ID
    assert data['repeat_source_task_id'] == expected_id
    assert data['img_service'] == 'seedream_5_pro'
    assert data['reference_images'] == [REFERENCE]
    assert data['repeat_prompt'] == SECRET
    assert data['repeat_prompt_hidden'] is True
    assert await ctx.state.get_state() == GenerationStates.uploading_reference_images.state
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert_no_handoff(ctx)
    buttons = [button.callback_data for row in
               ctx.callback.message.answer.await_args.kwargs['reply_markup'].inline_keyboard for button in row]
    assert f'repeat_refs_{expected_id}' in buttons
    assert f'repeat_run_{expected_id}' in buttons


@pytest.mark.asyncio
async def test_legacy_quick_confirmation_displays_cost_without_handoff_or_charge(monkeypatch):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = f'repeat_result_{TASK_ID}'
    await generation.quick_repeat_image_result(ctx.callback, ctx.state)
    assert_no_handoff(ctx)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    markup = ctx.callback.message.answer.await_args.kwargs['reply_markup']
    assert any(button.callback_data == f'repeat_run_confirm_{TASK_ID}'
               for row in markup.inline_keyboard for button in row)
    assert '10' in ctx.callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('quick', [False, True])
@pytest.mark.parametrize('missing', [False, True])
async def test_confirmation_keeps_native_input_validation_and_source_model(monkeypatch, quick, missing):
    ctx = await published_context(monkeypatch)
    await generation._restore_image_task_to_state(ctx.task, ctx.state,
        repeat_source_task_id=TASK_ID, hide_prompt=True)
    if missing:
        monkeypatch.setattr(generation, '_available_reference_images', lambda refs: ([], refs))
    ctx.callback.data = ('repeat_run_confirm_' if quick else 'repeat_run_') + TASK_ID
    handler = generation.quick_repeat_image_confirm if quick else generation.run_repeat_image_generation
    await handler(ctx.callback, ctx.state)
    assert_no_handoff(ctx)
    if missing:
        ctx.debit.assert_not_awaited()
        ctx.launch.assert_not_awaited()
        assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True
    else:
        ctx.debit.assert_awaited_once_with(ctx.owner.telegram_id, 10)
        ctx.launch.assert_awaited_once()
        args = ctx.launch.await_args.kwargs
        assert args['img_service'] == 'banana_pro'
        assert args['reference_images'] == [REFERENCE]
        assert SECRET in args['prompt']


@pytest.mark.asyncio
async def test_published_video_keeps_model_specific_guard_instead_of_generic_handoff(monkeypatch):
    from bot.genjutsu import feed
    from bot.handlers import miniapp_video_continuity_compat as continuity
    ctx = await published_context(monkeypatch, kind='video', model='wan_3')
    ctx.callback.data = f'repeat_video_result_{TASK_ID}'
    monkeypatch.setattr(feed, 'redirect_legacy_repeat', AsyncMock(return_value=False))
    typed = AsyncMock(return_value=True)
    monkeypatch.setattr(continuity, 'redirect_typed_video_repeat', typed)
    await generation.quick_repeat_video_result(ctx.callback, ctx.state)
    typed.assert_awaited_once()
    assert typed.await_args.args[0] is ctx.callback
    assert typed.await_args.args[1].task_id == TASK_ID
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert_no_handoff(ctx)
