from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from bot.handlers import wan3_prime as wan
from tests.test_wan3_prime_telegram_fsm import (
    FakeCallback,
    FakeFile,
    FakeMessage,
    FakeRuntime,
    FakeState,
)


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()
    async def get_runtime():
        return fake
    monkeypatch.setattr(wan, '_runtime', get_runtime)
    return fake


@pytest.fixture(autouse=True)
def isolated_database():
    yield


@pytest.fixture(autouse=True)
def fresh_actor_locks():
    wan._ACTOR_LOCKS.clear()
    yield
    wan._ACTOR_LOCKS.clear()


async def dispatch(message, state):
    return await wan.router.message.trigger(message, state=state, raw_state=await state.get_state())


def media_message(kind, index=1):
    kwargs = {'photo': [FakeFile(f'image-{index}')]} if kind in {'first', 'last', 'image'} else (
        {'video': FakeFile(f'video-{index}', file_name='Видео.mov')} if kind in {'source_video', 'video'} else
        {'audio': FakeFile(f'audio-{index}', file_name='voice.mp3')} if kind == 'audio' else
        {'document': FakeFile(f'file-{index}', file_name='brief.pdf')} if kind == 'file' else
        {'text': 'https://example.test/page'}
    )
    message = FakeMessage(**kwargs)
    message.message_id = index
    message.caption = None
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind', 'scenario'), [
    ('first', 'first_frame'), ('last', 'first_last'), ('source_video', 'edit'),
    ('image', 'reference'), ('video', 'reference'), ('audio', 'reference'),
    ('file', 'file'), ('link', 'link'),
])
async def test_actual_router_accepts_every_explicit_media_state(runtime, kind, scenario):
    state = FakeState()
    draft = wan.Wan3PrimeDraft(scenario=scenario, auto_mode=False)
    await state.update_data(**wan.draft_to_state(draft))
    await state.set_state(wan._media_state_for_kind(kind))
    assert await dispatch(media_message(kind), state) is not UNHANDLED
    assert len(runtime.stored) + len(runtime.imported) == 1
    assert await state.get_state() == wan.Wan3PrimeStates.dashboard.state


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'video', 'audio', 'file', 'link'])
async def test_dashboard_accepts_media_without_selector_and_never_launches(runtime, kind):
    state = FakeState()
    callback = FakeCallback('wan3_open')
    await wan.open_wan3_prime(callback, state)
    assert await dispatch(media_message(kind), state) is not UNHANDLED
    draft = wan.draft_from_state(await state.get_data())
    assert draft.scenario == ('file' if kind == 'file' else 'link' if kind == 'link' else 'reference')
    assert len(runtime.stored) + len(runtime.imported) == 1
    assert not runtime.launches and not runtime.quotes


@pytest.mark.asyncio
async def test_real_router_album_rapid_uploads_and_prompt_preserve_all_inputs(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.store_telegram_wan3_prime_media
    async def storage(**kwargs):
        if kwargs['file_id'] == 'image-2':
            started.set()
            await release.wait()
        return await original(**kwargs)
    runtime.store_telegram_wan3_prime_media = storage
    first, second = media_message('image', 2), media_message('image', 1)
    first.media_group_id = second.media_group_id = 'synthetic-album'
    first.caption = 'Подпись альбома'
    a = asyncio.create_task(dispatch(first, state))
    await started.wait()
    b = asyncio.create_task(dispatch(second, state))
    prompt = asyncio.create_task(dispatch(FakeMessage(text='Новый промпт'), state))
    release.set()
    await asyncio.gather(a, b, prompt)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.reference_image_urls == ['https://owned.test/image/image-1', 'https://owned.test/image/image-2']
    assert draft.prompt == 'Новый промпт'
    assert draft.scenario == 'reference'
    assert not runtime.launches


@pytest.mark.asyncio
async def test_prompt_and_settings_during_upload_survive_and_quote_is_blocked(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.store_telegram_wan3_prime_media
    async def storage(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)
    runtime.store_telegram_wan3_prime_media = storage
    upload = asyncio.create_task(dispatch(media_message('video'), state))
    await started.wait()
    quote = FakeCallback('wan3_quote')
    await wan.quote_wan3_prime(quote, state)
    assert not runtime.quotes and 'Дождитесь' in quote.answers[-1][0]
    option = asyncio.create_task(wan.set_wan3_option(FakeCallback('wan3_set:ratio:9:16'), state))
    prompt = asyncio.create_task(dispatch(FakeMessage(text='Сохранить движение'), state))
    release.set()
    await asyncio.gather(upload, option, prompt)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.reference_video_urls == ['https://owned.test/video/video-1']
    assert draft.prompt == 'Сохранить движение' and draft.aspect_ratio == '9:16'
    await wan.quote_wan3_prime(FakeCallback('wan3_quote'), state)
    assert runtime.quotes[-1]['recipe']['scenario'] == 'reference'
    assert not runtime.launches


@pytest.mark.asyncio
async def test_new_task_during_upload_does_not_resurrect_old_reference(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.store_telegram_wan3_prime_media
    async def storage(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)
    runtime.store_telegram_wan3_prime_media = storage
    message = media_message('image')
    upload = asyncio.create_task(dispatch(message, state))
    await started.wait()
    new_task = asyncio.create_task(wan.new_wan3_prime(FakeCallback('wan3_new'), state))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(upload, new_task)
    new_id = wan.draft_from_state(await state.get_data()).client_request_id
    draft = wan.draft_from_state(await state.get_data())
    assert draft.client_request_id == new_id and not draft.reference_image_urls
    assert any('предыдущей' in text for text, _ in message.answers)


@pytest.mark.asyncio
async def test_errors_are_immediate_and_retry_preserves_existing_media(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(media_message('image'), state)
    original = runtime.store_telegram_wan3_prime_media
    runtime.store_telegram_wan3_prime_media = AsyncMock(side_effect=RuntimeError('private upstream detail'))
    failed = media_message('video')
    await dispatch(failed, state)
    assert any('Не удалось сохранить материал' in text for text, _ in failed.answers)
    assert not any('private upstream' in text for text, _ in failed.answers)
    assert not (await state.get_data()).get('wan3_uploading')
    runtime.store_telegram_wan3_prime_media = original
    await dispatch(media_message('video'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert len(draft.reference_image_urls) == len(draft.reference_video_urls) == 1


@pytest.mark.asyncio
async def test_short_dashboard_advanced_roles_remove_back_and_reenter(runtime):
    state = FakeState()
    callback = FakeCallback('wan3_open')
    await wan.open_wan3_prime(callback, state)
    buttons = [b for row in wan.dashboard_keyboard(wan.Wan3PrimeDraft()).inline_keyboard for b in row]
    assert len(buttons) <= 10
    assert not any(b.callback_data.startswith(('wan3_set:', 'wan3_mode:')) for b in buttons)
    await dispatch(media_message('image'), state)
    await dispatch(FakeMessage(text='Промпт'), state)
    await wan.show_wan3_settings(FakeCallback('wan3_settings'), state)
    await wan.open_wan3_prime(FakeCallback('wan3_dashboard'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert len(draft.reference_image_urls) == 1 and draft.prompt == 'Промпт'
    await wan.remove_wan3_media(FakeCallback('wan3_remove:image:0'), state)
    assert wan.draft_from_state(await state.get_data()).scenario == 'text'
    await wan.choose_wan3_mode(FakeCallback('wan3_mode:first_last'), state)
    assert wan.draft_from_state(await state.get_data()).auto_mode is False
    blocked = media_message('image')
    await dispatch(blocked, state)
    assert any('выберите роль' in text for text, _ in blocked.answers)


@pytest.mark.asyncio
async def test_delayed_quote_cannot_restore_stale_prompt_or_media(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(FakeMessage(text='Синтетическая сцена'), state)
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.quote_telegram_wan3_prime
    async def quote(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)
    runtime.quote_telegram_wan3_prime = quote
    callback = FakeCallback('wan3_quote')
    pending = asyncio.create_task(wan.quote_wan3_prime(callback, state))
    await started.wait()
    await dispatch(media_message('image'), state)
    await dispatch(FakeMessage(text='Другой промпт на 24 секунды'), state)
    release.set()
    await pending
    draft = wan.draft_from_state(await state.get_data())
    assert draft.reference_image_urls and draft.prompt == 'Другой промпт на 24 секунды'
    assert draft.duration == 5 and draft.quote_hash is None
    assert 'изменились' in callback.answers[-1][0]
    assert not runtime.launches


@pytest.mark.asyncio
async def test_photo_as_document_and_mixed_image_audio_prompt_are_automatic(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(FakeMessage(document=FakeFile('unicode-photo', file_name='Фото.JPG')), state)
    await dispatch(media_message('audio'), state)
    await dispatch(FakeMessage(text='Image1 задаёт стиль, Audio1 задаёт настроение'), state)
    await wan.quote_wan3_prime(FakeCallback('wan3_quote'), state)
    recipe = runtime.quotes[-1]['recipe']
    assert recipe['scenario'] == 'reference'
    assert recipe['reference_image_urls'] == ['https://owned.test/image/unicode-photo']
    assert recipe['reference_audio_urls'] == ['https://owned.test/audio/audio-1']
    assert recipe['duration'] == 5
    assert not runtime.launches


@pytest.mark.asyncio
async def test_explicit_frame_roles_return_to_auto_without_losing_saved_references(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(media_message('image'), state)
    await dispatch(media_message('audio'), state)
    await wan.choose_wan3_mode(FakeCallback('wan3_mode:first_frame'), state)
    await wan.ask_wan3_media(FakeCallback('wan3_media:first'), state)
    await dispatch(media_message('image', 2), state)
    await wan.choose_wan3_mode(FakeCallback('wan3_mode:auto'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.scenario == 'reference' and draft.auto_mode
    assert draft.reference_image_urls == ['https://owned.test/image/image-1', 'https://owned.test/image/image-2']
    assert draft.reference_audio_urls == ['https://owned.test/audio/audio-1']
    assert not draft.first_frame_url and not draft.last_frame_url


@pytest.mark.asyncio
async def test_queued_album_and_text_cannot_enter_new_task(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    old_id = wan.draft_from_state(await state.get_data()).client_request_id
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.store_telegram_wan3_prime_media
    async def storage(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)
    runtime.store_telegram_wan3_prime_media = storage
    first = asyncio.create_task(dispatch(media_message('image', 1), state))
    await started.wait()
    second = asyncio.create_task(dispatch(media_message('image', 2), state))
    text = asyncio.create_task(dispatch(FakeMessage(text='Old queued prompt'), state))
    option = asyncio.create_task(wan.set_wan3_option(FakeCallback('wan3_set:ratio:9:16'), state))
    await asyncio.sleep(0.02)
    reset = asyncio.create_task(wan.new_wan3_prime(FakeCallback('wan3_new'), state))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second, text, option, reset)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.client_request_id != old_id
    assert not draft.reference_image_urls and not draft.prompt
    assert draft.aspect_ratio == 'adaptive'
    assert len(runtime.stored) == 1


@pytest.mark.asyncio
async def test_quote_commit_serializes_concurrent_prompt(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(FakeMessage(text='Original prompt'), state)
    reached, release = asyncio.Event(), asyncio.Event()
    original = state.set_state
    async def gated_set_state(value):
        if value == wan.Wan3PrimeStates.reviewing:
            reached.set()
            await release.wait()
        await original(value)
    state.set_state = gated_set_state
    quote = asyncio.create_task(wan.quote_wan3_prime(FakeCallback('wan3_quote'), state))
    await reached.wait()
    prompt = asyncio.create_task(dispatch(FakeMessage(text='Concurrent prompt'), state))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(quote, prompt)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.prompt == 'Concurrent prompt'
    assert draft.quote_hash is None and draft.last_quote is None
    assert not runtime.launches


@pytest.mark.parametrize('scenario', ['first_frame', 'first_last', 'edit'])
def test_advanced_auto_round_trip_preserves_roles(scenario):
    draft = wan.Wan3PrimeDraft(scenario=scenario, auto_mode=False, prompt='Synthetic scene')
    if scenario == 'edit':
        draft.reference_video_urls = ['https://owned.test/source', 'https://owned.test/ref']
    else:
        draft.first_frame_url = 'https://owned.test/first'
        if scenario == 'first_last':
            draft.last_frame_url = 'https://owned.test/last'
    original = wan._snapshot_mode(draft)
    draft = wan.apply_wan3_mode(draft, 'auto')
    draft = wan.apply_wan3_mode(draft, scenario)
    assert draft.first_frame_url == original['first_frame_url']
    assert draft.last_frame_url == original['last_frame_url']
    assert draft.reference_video_urls == original['reference_video_urls']
    assert not draft.auto_mode


@pytest.mark.asyncio
async def test_duration_steps_auto_and_number_invalidate_quote(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(FakeMessage(text='Synthetic 24 second story'), state)
    await wan.quote_wan3_prime(FakeCallback('wan3_quote'), state)
    await wan.step_wan3_duration(FakeCallback('wan3_duration_step:6'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.duration == 6 and draft.quote_hash is None
    await wan.step_wan3_duration(FakeCallback('wan3_duration_step:-1'), state)
    assert wan.draft_from_state(await state.get_data()).duration == -1
    await dispatch(FakeMessage(text='12'), state)
    assert wan.draft_from_state(await state.get_data()).duration == 12
    await wan.ask_wan3_duration(FakeCallback('wan3_duration'), state)
    await dispatch(FakeMessage(text='31'), state)
    assert wan.draft_from_state(await state.get_data()).duration == 12
    await wan.quote_wan3_prime(FakeCallback('wan3_quote'), state)
    assert runtime.quotes[-1]['recipe']['duration'] == 12
    assert not runtime.launches


@pytest.mark.asyncio
async def test_restored_owner_recipe_accepts_text_and_media_without_losing_audio(runtime):
    state = FakeState()
    await wan.restore_wan3_owner_recipe(FakeCallback('wan3_recipe:synthetic-task'), state)
    await dispatch(media_message('image'), state)
    await dispatch(FakeMessage(text='Synthetic restored prompt'), state)
    await wan.open_wan3_prime(FakeCallback('wan3_dashboard'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.reference_audio_urls == ['https://owned.test/audio/a.mp3']
    assert draft.reference_image_urls == ['https://owned.test/image/image-1']
    assert draft.prompt == 'Synthetic restored prompt' and draft.auto_mode
    assert not runtime.launches


@pytest.mark.asyncio
async def test_duration_screen_requested_during_upload_keeps_numeric_input_role(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    started, release = asyncio.Event(), asyncio.Event()
    original = runtime.store_telegram_wan3_prime_media
    async def storage(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)
    runtime.store_telegram_wan3_prime_media = storage
    upload = asyncio.create_task(dispatch(media_message('image'), state))
    await started.wait()
    settings = asyncio.create_task(wan.ask_wan3_duration(FakeCallback('wan3_duration'), state))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(upload, settings)
    assert await state.get_state() == wan.Wan3PrimeStates.waiting_duration.state
    await dispatch(FakeMessage(text='12'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.duration == 12 and not draft.prompt and len(draft.reference_image_urls) == 1


@pytest.mark.asyncio
async def test_compact_dashboard_duration_and_audio_controls_preserve_refs(runtime):
    state = FakeState()
    await wan.open_wan3_prime(FakeCallback('wan3_open'), state)
    await dispatch(media_message('image'), state)
    await wan.quote_wan3_prime(FakeCallback('wan3_quote'), state)
    await wan.step_wan3_duration(FakeCallback('wan3_quick_duration:6'), state)
    await wan.toggle_wan3_option(FakeCallback('wan3_toggle:audio'), state)
    draft = wan.draft_from_state(await state.get_data())
    assert draft.duration == 6 and not draft.audio and draft.quote_hash is None
    assert len(draft.reference_image_urls) == 1
    keyboard = wan.dashboard_keyboard(draft).inline_keyboard
    assert [button.text for button in keyboard[1]] == ['− 1 с', '⏱ 6 с', '+ 1 с']
    assert keyboard[2][0].text == '🔇 Звук: выкл'
    assert await state.get_state() == wan.Wan3PrimeStates.dashboard.state
    assert not runtime.launches
