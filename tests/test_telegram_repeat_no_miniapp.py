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

from bot import database, miniapp
from bot.handlers import generation
from bot.states import GenerationStates

SECRET = 'Synthetic hidden source recipe'
REFERENCE = 'https://example.test/synthetic-own-reference.png'
TASK_ID = 'native-repeat-source'


async def published_context(monkeypatch, *, scope='feed', rollout='all', model='banana_pro', kind='image', prompt=SECRET):
    monkeypatch.setattr(miniapp, '_resolve_image_unit_cost', lambda model, quality: 10)
    monkeypatch.setattr(generation, '_reference_upload_locks', {})
    owner = await database.get_or_create_user(840051)
    request = {'img_service': model, 'img_ratio': '9:16', 'img_quality': '2K',
               'prompt': prompt, 'prompt_hidden': True,
               'source_reference_images': [REFERENCE], 'reference_images': [REFERENCE]}
    await database.add_generation_task(owner.id, owner.telegram_id, TASK_ID, kind, model,
        model=model, prompt=prompt, cost=10, request_data=request)
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
    assert f'repeat_q_{data["repeat_quote_id"]}' in buttons


@pytest.mark.asyncio
async def test_legacy_result_entry_displays_current_cost_and_editable_uploads_without_charge(monkeypatch):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = f'repeat_result_{TASK_ID}'
    await generation.quick_repeat_image_result(ctx.callback, ctx.state)
    assert_no_handoff(ctx)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    markup = ctx.callback.message.answer.await_args.kwargs['reply_markup']
    data = await ctx.state.get_data()
    assert any(button.callback_data == f'repeat_q_{data["repeat_quote_id"]}'
               for row in markup.inline_keyboard for button in row)
    assert any(button.callback_data == f'repeat_refs_{TASK_ID}'
               for row in markup.inline_keyboard for button in row)
    assert '10' in ctx.callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('quick', [False, True])
@pytest.mark.parametrize('missing', [False, True])
async def test_confirmation_keeps_native_input_validation_and_source_model(monkeypatch, quick, missing):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = ('repeat_result_' if quick else 'repeat_image_') + TASK_ID
    opener = generation.quick_repeat_image_result if quick else generation.repeat_image_generation
    await opener(ctx.callback, ctx.state)
    if missing:
        monkeypatch.setattr(generation, '_available_reference_images', lambda refs: ([], refs))
    token = (await ctx.state.get_data())['repeat_quote_id']
    ctx.callback.data = f'repeat_q_{token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
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


@pytest.mark.asyncio
async def test_production_router_order_legacy_button_opens_editable_photo_flow(monkeypatch):
    from bot.handlers import generation_router
    ctx = await published_context(monkeypatch)
    viewer = await database.get_or_create_user(840052)
    ctx.callback.from_user = SimpleNamespace(id=viewer.telegram_id)
    ctx.callback.data = f'repeat_result_{TASK_ID}'
    await generation_router.propagate_event('callback_query', ctx.callback, state=ctx.state)
    assert await ctx.state.get_state() == GenerationStates.uploading_reference_images.state
    markup = ctx.callback.message.answer.await_args.kwargs['reply_markup']
    assert any(button.callback_data == f'repeat_refs_{TASK_ID}' for row in markup.inline_keyboard for button in row)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert_no_handoff(ctx)


@pytest.mark.asyncio
async def test_native_repeat_quotes_current_quality_price_and_requires_reconfirm_after_change(monkeypatch):
    from bot import miniapp
    ctx = await published_context(monkeypatch)
    price = {'value': 27}
    monkeypatch.setattr(miniapp, '_resolve_image_unit_cost', lambda model, quality: price['value'])
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    assert (await ctx.state.get_data())['repeat_unit_cost'] == 27
    assert '27' in ctx.callback.message.answer.await_args.args[0]
    price['value'] = 31
    old_token = (await ctx.state.get_data())['repeat_quote_id']
    ctx.callback.data = f'repeat_q_{old_token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    data = await ctx.state.get_data()
    assert data['repeat_unit_cost'] == 31
    assert data['repeat_quote_id'] != old_token
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.callback.data = f'repeat_q_{data["repeat_quote_id"]}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_awaited_once_with(ctx.owner.telegram_id, 31)
    assert ctx.launch.await_args.kwargs['unit_cost'] == 31


@pytest.mark.asyncio
@pytest.mark.parametrize('quick', [False, True])
async def test_stale_confirmation_without_fsm_never_charges(monkeypatch, quick):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = ('repeat_run_confirm_' if quick else 'repeat_run_') + TASK_ID
    handler = generation.quick_repeat_image_confirm if quick else generation.run_repeat_image_generation
    await handler(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert await ctx.state.get_state() == GenerationStates.uploading_reference_images.state


async def configure_named_template(ctx, *, advanced=False):
    from bot import smart_repeat_store as store
    from bot.smart_repeat_contract import public_template
    source = await database.get_generation_task_payload(TASK_ID)
    template = await store.get_template(source)
    submitted = public_template(template, author=True)
    submitted['slots'][0]['label'] = 'Ваше лицо'
    if advanced:
        # Exercise an author-added required slot without changing the source row.
        import uuid
        submitted['slots'].append({'slot_id': uuid.uuid4().hex, 'kind': 'image',
            'binding': 'upload', 'required': True, 'label': 'Обязательный предмет'})
    await store.save_template(ctx.owner, source, submitted)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['open', 'confirm', 'changed_after_open'])
async def test_unrepresentable_author_template_never_falls_through_to_generic_paid_repeat(monkeypatch, phase):
    ctx = await published_context(monkeypatch)
    if phase == 'changed_after_open':
        ctx.callback.data = f'repeat_image_{TASK_ID}'
        await generation.repeat_image_generation(ctx.callback, ctx.state)
    await configure_named_template(ctx, advanced=True)
    if phase == 'open':
        ctx.callback.data = f'repeat_image_{TASK_ID}'
        await generation.repeat_image_generation(ctx.callback, ctx.state)
        assert (await ctx.state.get_data()).get('repeat_source_task_id') is None
    else:
        ctx.callback.data = f'repeat_run_{TASK_ID}'
        await generation.run_repeat_image_generation(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True
    assert_no_handoff(ctx)


@pytest.mark.asyncio
async def test_named_required_photo_is_not_silently_omitted_in_native_launch(monkeypatch):
    ctx = await published_context(monkeypatch)
    await configure_named_template(ctx)
    viewer = await database.get_or_create_user(840052)
    ctx.callback.from_user = SimpleNamespace(id=viewer.telegram_id)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    assert 'Ваше лицо' in ctx.callback.message.answer.await_args.args[0]
    token = (await ctx.state.get_data())['repeat_quote_id']
    ctx.callback.data = f'repeat_q_{token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True


@pytest.mark.asyncio
async def test_duplicate_bound_confirmation_debits_and_launches_once(monkeypatch):
    import asyncio
    ctx = await published_context(monkeypatch)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    token = (await ctx.state.get_data())['repeat_quote_id']
    ctx.callback.data = f'repeat_q_{token}'
    await asyncio.gather(generation.confirm_native_repeat_quote(ctx.callback, ctx.state),
                         generation.confirm_native_repeat_quote(ctx.callback, ctx.state))
    ctx.debit.assert_awaited_once()
    ctx.launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_native_quote_matches_free_launch(monkeypatch):
    ctx = await published_context(monkeypatch)
    monkeypatch.setattr(generation.config, 'is_admin', lambda _: True)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    data = await ctx.state.get_data()
    assert data['repeat_unit_cost'] == 0
    ctx.callback.data = f'repeat_q_{data["repeat_quote_id"]}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_awaited_once()
    assert ctx.launch.await_args.kwargs['unit_cost'] == 0


@pytest.mark.asyncio
async def test_supported_named_photo_validates_actual_local_image_and_preserves_binding(monkeypatch, tmp_path):
    from PIL import Image

    from bot.services import media_input_utils
    ctx = await published_context(monkeypatch)
    await configure_named_template(ctx)
    image_path = tmp_path / 'own-photo.png'
    Image.new('RGB', (32, 32)).save(image_path)
    monkeypatch.setattr(media_input_utils, 'resolve_local_upload_path', lambda url: str(image_path))
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    token = (await ctx.state.get_data())['repeat_quote_id']
    ctx.callback.data = f'repeat_q_{token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_awaited_once()
    assert ctx.launch.await_args.kwargs['reference_images'] == [REFERENCE]


@pytest.mark.asyncio
async def test_new_author_template_invalidates_already_rendered_quote_before_debit(monkeypatch):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    token = (await ctx.state.get_data())['repeat_quote_id']
    await configure_named_template(ctx, advanced=True)
    ctx.callback.data = f'repeat_q_{token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True


@pytest.mark.asyncio
async def test_variable_template_never_submits_literal_placeholders_or_charges(monkeypatch):
    from bot import smart_repeat_store as store
    from bot.smart_repeat_contract import public_template
    ctx = await published_context(monkeypatch, prompt=SECRET + ' age {{age}}')
    source = await database.get_generation_task_payload(TASK_ID)
    template = await store.get_template(source)
    submitted = public_template(template, author=True)
    submitted['variables'] = [{'id': 'age', 'label': 'Age', 'required': True, 'max_length': 3}]
    await store.save_template(ctx.owner, source, submitted)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    assert (await ctx.state.get_data()).get('repeat_source_task_id') is None
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True
    assert_no_handoff(ctx)


@pytest.mark.asyncio
async def test_reference_or_prompt_change_invalidates_old_confirmation(monkeypatch):
    ctx = await published_context(monkeypatch)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    old_token = (await ctx.state.get_data())['repeat_quote_id']
    await ctx.state.update_data(reference_images=['https://example.test/new-photo.png'],
                                repeat_prompt=SECRET + ' additional requested details')
    ctx.callback.data = f'repeat_q_{old_token}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert (await ctx.state.get_data())['repeat_quote_id'] != old_token
