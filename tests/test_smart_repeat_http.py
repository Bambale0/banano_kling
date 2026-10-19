"""Signed-user HTTP boundary through the real image engine, synthetic provider."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp
from bot import db as db_backend
from bot.smart_repeat_api import setup_smart_repeat_routes
from tests.test_smart_repeat_store import setup_repeat


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['queued', 'rejected', 'lost_response'])
@pytest.mark.parametrize('source_inputs', [False, True])
@pytest.mark.parametrize('reference_store', ['saved', 'wan'])
async def test_http_image_preflight_upload_reload_quote_launch_and_replay(monkeypatch, tmp_path, outcome, source_inputs, reference_store):
    from bot.handlers import generation
    ctx = await setup_repeat(monkeypatch, tmp_path)
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET type = 'image', model = 'banana_pro', prompt = 'Private synthetic recipe', "
            'result_url = ?, request_data = ? WHERE id = ?', ('https://example.test/result.png',
            json.dumps({'source_reference_images': ['/uploads/refs/source.png']} if source_inputs else {}), ctx.source['id']))
        # Fresh model/source is a new fixture, not a migration of a published template.
        await db.execute('DELETE FROM smart_repeat_drafts')
        await db.execute('DELETE FROM smart_repeat_templates')
        await db.commit()
    reference = (await database.list_saved_references(ctx.user.telegram_id))[0]
    identity = {'saved_reference_id': str(reference.id)}
    if reference_store == 'wan':
        from bot.services.wan3_prime_storage import Wan3PrimeStorage
        await Wan3PrimeStorage().init_schema()
        async with db_backend.connect() as db:
            await db.execute('INSERT INTO wan3_prime_media (id,user_id,telegram_id,kind,public_url,local_path,filename,content_type,size_bytes,sha256,media_info) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (reference.id,ctx.user.id,ctx.user.telegram_id,'image','/uploads/wan3/own.png',str(ctx.path),'wan-portrait.png','image/png',ctx.path.stat().st_size,'synthetic','{}'))
            await db.commit()
        identity = {'wan3_media_id': str(reference.id)}
    expected_url = '/uploads/wan3/own.png' if reference_store == 'wan' else '/uploads/refs/own.png'
    await database.set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': True}))
    monkeypatch.setattr(database, '_is_feed_result_url_available', lambda *args: True)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(ctx.user.telegram_id, {'user': ctx.user})))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, '_resolve_image_unit_cost', lambda *_: 10)
    monkeypatch.setattr(generation, '_available_reference_images', lambda refs: (refs, []))
    provider = AsyncMock(return_value={'task_id': 'http-image-accepted'} if outcome != 'rejected' else None)
    monkeypatch.setattr(generation.nano_banana_pro_service, 'generate_image', provider)
    if outcome == 'lost_response':
        monkeypatch.setattr(generation, '_merge_task_id_aliases', lambda *args: (_ for _ in ()).throw(OSError('persistence unavailable')))
    app = web.Application()
    setup_smart_repeat_routes(app, '/mini-app')
    async with TestClient(TestServer(app)) as client:
        async def call(action, **payload):
            response = await client.post('/mini-app/api/repeat/' + action, json={'init_data': 'signed', **payload})
            return response.status, await response.json()
        status, draft = await call('open', source_id=ctx.source['id'])
        assert status == 200, draft
        did, sid = draft['draft_id'], draft['template']['slots'][0]['slot_id']
        assert 'Private synthetic' not in json.dumps(draft) and 'source.png' not in json.dumps(draft)
        status, error = await call('quote', draft_id=did)
        assert status == 409 and error['code'] == 'REFERENCES_NOT_READY'
        status, begun = await call('update', draft_id=did, operation='begin', slot_id=sid)
        assert status == 200
        status, error = await call('launch', draft_id=did, quote_id='forged')
        assert status == 409 and error['code'] == 'REFERENCES_NOT_READY'
        provider.assert_not_awaited()
        assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100
        status, ready = await call('update', draft_id=did, operation='ready', slot_id=sid,
            upload_token=begun['slots'][sid]['upload_token'], **identity,
            url='https://example.test/forged-url-is-ignored.png')
        assert status == 200, ready
        _, restored = await call('open', source_id=ctx.source['id'])
        assert restored['slots'][sid]['asset_id'] == ready['slots'][sid]['asset_id']
        assert restored['slots'][sid][next(iter(identity))] == next(iter(identity.values()))
        assert restored['slots'][sid]['url'] == expected_url
        status, changed = await call('update', draft_id=did, operation='changes', prompt_changes='Make the car blue')
        assert status == 200, changed
        _, restored = await call('open', source_id=ctx.source['id'])
        assert restored['prompt_changes'] == 'Make the car blue'
        assert 'Private synthetic recipe' not in json.dumps(restored)
        status, quoted = await call('quote', draft_id=did)
        assert status == 200 and quoted['quote']['cost'] == 10, quoted
        responses = await asyncio.gather(*(call('launch', draft_id=did, quote_id=quoted['quote']['quote_id']) for _ in range(2)))
        assert provider.await_count == 1, responses
        if outcome == 'queued':
            assert any(status < 400 for status, result in responses), responses
        provider.assert_awaited_once()
        assert provider.await_args.kwargs['image_input'] == [expected_url]
        assert 'Private synthetic recipe' in provider.await_args.kwargs['prompt']
        assert provider.await_args.kwargs['prompt'].count('Make the car blue') == 1
        _, recovered = await call('open', source_id=ctx.source['id'])
        assert recovered['status'] == ('rejected' if outcome == 'rejected' else 'launched'), recovered
        await call('launch', draft_id=did, quote_id=quoted['quote']['quote_id'])
        provider.assert_awaited_once()
        assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == (100 if outcome == 'rejected' else 90)
        if outcome == 'rejected':
            _, fresh = await call('open', source_id=ctx.source['id'], new=True)
            assert fresh['status'] == 'draft' and fresh['draft_id'] != did
        # Another user cannot inspect assets, launch state or diagnostic snapshots.
        monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(ctx.owner.telegram_id, {'user': ctx.owner})))
        status, _ = await call('diagnostics', draft_id=did)
        assert status == 404
        # Authenticated administrators may inspect expected/actual bindings, no URLs.
        monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: True)
        status, diagnostic = await call('diagnostics', draft_id=did)
        assert status == 200 and diagnostic['expected_slots'][0]['slot_id'] == sid
        assert '/uploads/' not in json.dumps(diagnostic)


@pytest.mark.asyncio
async def test_rollout_gateway_covers_aliases_nested_wan_and_rest(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(ctx.user.telegram_id, {'user': ctx.user})))
    delegated = AsyncMock(side_effect=lambda _request: web.json_response({'ok': True}))
    app = web.Application()
    setup_smart_repeat_routes(app, '/mini-app')
    for path in ('/mini-app/api/generate-image', '/mini-app/api/generate-video', '/mini-app/api/wan3/generate', '/api/v1/feed/{gen_id}/remix'):
        app.router.add_post(path, delegated)
    async with TestClient(TestServer(app)) as client:
        for enabled in (False, True):
            await database.set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': enabled}))
            cases = [('/mini-app/api/generate-image', {'sourceFeedGenId': ctx.source['id']}),
                ('/mini-app/api/generate-video', {'source_feed_gen_id': ctx.source['id']}),
                ('/mini-app/api/wan3/generate', {'recipe': {'source_feed_gen_id': ctx.source['id']}}),
                (f'/api/v1/feed/{ctx.source["id"]}/remix', {}),
                (f'/mini-app/api/generate-image?sourceFeedGenId={ctx.source["id"]}', {})]
            for path, body in cases:
                response = await client.post(path, json={'init_data': 'signed', **body})
                assert response.status == (409 if enabled else 200), await response.text()
                if enabled:
                    assert (await response.json())['code'] == 'SMART_REPEAT_REQUIRED'
        assert delegated.await_count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['edit', 'identity'])
async def test_seedance_edit_http_compiles_ready_media_and_uses_existing_adapter(monkeypatch, tmp_path, mode):
    import subprocess

    from PIL import Image

    from bot.handlers import miniapp_video_continuity_compat as continuity
    from bot.handlers import seedance_25_public_release as public
    ctx = await setup_repeat(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    image = tmp_path / f'static/uploads/refs/image/{ctx.user.telegram_id}/own.png'
    image.parent.mkdir(parents=True)
    Image.new('RGB', (600, 600), 'blue').save(image)
    base = public.config.static_base_url.rstrip('/')
    image_url = f'{base}/uploads/refs/image/{ctx.user.telegram_id}/own.png'
    video_url = f'{base}/uploads/refs/video/{ctx.user.telegram_id}/own.mp4'
    video = tmp_path / f'static/uploads/refs/video/{ctx.user.telegram_id}/own.mp4'
    video.parent.mkdir(parents=True)
    await asyncio.to_thread(subprocess.run, ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'color=blue:s=640x640:r=24:d=5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True, timeout=20)
    resolver = lambda url: str(video if url.endswith('.mp4') else image)
    monkeypatch.setattr('bot.services.media_input_utils.resolve_local_upload_path', resolver)
    monkeypatch.setattr('bot.services.media_input_utils._resolve_local_upload_path', resolver)
    monkeypatch.setattr(public.fullstack, 'resolve_local_upload_path', resolver)
    monkeypatch.setattr('bot.video_reference_policy.resolve_local_upload_path', resolver)
    async with db_backend.connect() as db:
        await db.execute('UPDATE generation_tasks SET prompt = ?, result_url = ?, request_data = ? WHERE id = ?',
            ('Use @Image1 to edit @Video1', 'https://example.test/result.mp4', json.dumps({
                'v_type': 'video', 'seedance25_scenario': 'multimodal', 'seedance25_video_editing': True,
                'seedance25_resolution': '720p', 'seedance25_identity_transfer': mode == 'identity', 'reference_images': ['/uploads/refs/source.png'],
                'v_reference_videos': ['/uploads/refs/source.mp4']}), ctx.source['id']))
        await db.execute('DELETE FROM smart_repeat_drafts')
        await db.execute('DELETE FROM smart_repeat_templates')
        await db.commit()
    await database.save_user_reference(ctx.user.telegram_id, kind='video', file_url=video_url, file_hash='video')
    await database.save_user_reference(ctx.user.telegram_id, kind='image', file_url=image_url, file_hash='managed-image')
    await database.set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': True}))
    monkeypatch.setattr(database, '_is_feed_result_url_available', lambda *args: True)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(ctx.user.telegram_id, {'user': ctx.user})))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    async def installed_engine(request):
        body = await continuity._restore_repeat_request(request, await request.json())
        continuity._replace_cached_json(request, body)
        return await public._public_miniapp_generate(request, body)
    monkeypatch.setattr(miniapp, 'miniapp_generate_video', installed_engine)
    provider = AsyncMock(return_value={'task_id': 'smart-seedance-edit'})
    monkeypatch.setattr(public, '_launch_provider', provider)
    app = web.Application()
    setup_smart_repeat_routes(app, '/mini-app')
    async with TestClient(TestServer(app)) as client:
        async def call(action, **body):
            response = await client.post('/mini-app/api/repeat/' + action, json={'init_data': 'signed', **body})
            return response.status, await response.json()
        status, draft = await call('open', source_id=ctx.source['id'])
        assert status == 200, draft
        did = draft['draft_id']
        for slot in draft['template']['slots']:
            _, begun = await call('update', draft_id=did, operation='begin', slot_id=slot['slot_id'])
            status, ready = await call('update', draft_id=did, operation='ready', slot_id=slot['slot_id'],
                upload_token=begun['slots'][slot['slot_id']]['upload_token'], url=image_url if slot['kind'] == 'image' else video_url)
            assert status == 200, ready
        status, quote = await call('quote', draft_id=did)
        assert status == 200, quote
        provider.assert_not_awaited()
        status, result = await call('launch', draft_id=did, quote_id=quote['quote']['quote_id'])
        assert status < 400 and result['task_id'] == 'smart-seedance-edit', result
        provider.assert_awaited_once()
        payload = provider.await_args.args[0]
        assert payload['image_urls'] == [image_url]
        assert payload['video_urls'] == [video_url] and payload['seedance25_video_editing'] is True
        assert payload['billing_duration'] == 5
        assert payload['seedance25_identity_transfer'] is (mode == 'identity')
        assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100 - quote['quote']['cost']


@pytest.mark.asyncio
async def test_generic_seedance_engine_receives_each_configured_audio_slot(monkeypatch, tmp_path):
    import inspect
    import subprocess
    import uuid

    from bot.handlers import miniapp_video_continuity_compat as continuity
    from bot.services.seedance_service import seedance_service
    ctx = await setup_repeat(monkeypatch, tmp_path)
    audios = {}
    for index in (1, 2):
        path = tmp_path / f'audio{index}.wav'
        await asyncio.to_thread(subprocess.run, ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            f'sine=frequency={440 * index}:duration=2', str(path)], check=True, timeout=10)
        audios[f'https://tanyapi.chillcreative.ru/uploads/refs/audio{index}.wav'] = path
        await database.save_user_reference(ctx.user.telegram_id, kind='audio', file_url=list(audios)[-1], file_hash=f'audio{index}')
    resolver = lambda url: str(audios.get(url, ctx.path))
    monkeypatch.setattr('bot.services.media_input_utils.resolve_local_upload_path', resolver)
    monkeypatch.setattr('bot.services.media_input_utils._resolve_local_upload_path', resolver)
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET model = 'seedance_2', prompt = 'Use @Image1 with @Audio1 and @Audio2', "
            'result_url = ?, request_data = ? WHERE id = ?', ('https://example.test/result.mp4', json.dumps({
                'v_model': 'seedance_2', 'v_type': 'imgtxt', 'reference_images': ['/uploads/refs/source.png'],
                'v_reference_audio': ['/uploads/refs/source.wav']}), ctx.source['id']))
        await db.execute('DELETE FROM smart_repeat_drafts')
        await db.execute('DELETE FROM smart_repeat_templates')
        await db.commit()
    await database.set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': True}))
    monkeypatch.setattr(database, '_is_feed_result_url_available', lambda *args: True)
    actor = [ctx.owner]
    async def auth(*args, **kwargs):
        return actor[0].telegram_id, {'user': actor[0]}
    monkeypatch.setattr(miniapp, '_get_user_context', auth)
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    base_engine = inspect.unwrap(miniapp.miniapp_generate_video)
    async def installed_engine(request):
        body = await continuity._restore_repeat_request(request, await request.json())
        continuity._replace_cached_json(request, body)
        return await base_engine(request)
    monkeypatch.setattr(miniapp, 'miniapp_generate_video', installed_engine)
    provider = AsyncMock(return_value={'task_id': 'generic-multi-audio'})
    monkeypatch.setattr(seedance_service, 'generate_video', provider)
    app = web.Application()
    setup_smart_repeat_routes(app, '/mini-app')
    async with TestClient(TestServer(app)) as client:
        async def call(action, **body):
            response = await client.post('/mini-app/api/repeat/' + action, json={'init_data': 'signed', **body})
            return response.status, await response.json()
        status, response = await call('template', source_id=ctx.source['id'], author=True)
        assert status == 200, response
        schema = response['template']
        schema['slots'].append({'slot_id': uuid.uuid4().hex, 'kind': 'audio', 'binding': 'upload', 'required': True, 'label': 'Audio2'})
        status, response = await call('configure', source_id=ctx.source['id'], template=schema)
        assert status == 200, response
        actor[0] = ctx.user
        status, draft = await call('open', source_id=ctx.source['id'])
        assert status == 200, draft
        did = draft['draft_id']
        audio_urls = iter(audios)
        for slot in draft['template']['slots']:
            url = next(audio_urls) if slot['kind'] == 'audio' else '/uploads/refs/own.png'
            _, begun = await call('update', draft_id=did, operation='begin', slot_id=slot['slot_id'])
            status, result = await call('update', draft_id=did, operation='ready', slot_id=slot['slot_id'],
                upload_token=begun['slots'][slot['slot_id']]['upload_token'], url=url)
            assert status == 200, result
        status, quote = await call('quote', draft_id=did)
        assert status == 200, quote
        status, result = await call('launch', draft_id=did, quote_id=quote['quote']['quote_id'])
        assert status < 400 and result.get('task_id') == 'generic-multi-audio', result
        provider.assert_awaited_once()
        from bot.services.media_input_utils import reference_source_identity
        expected = [reference_source_identity(url) for url in audios]
        assert [reference_source_identity(url) for url in provider.await_args.kwargs['reference_audio_urls']] == expected
        task = await database.get_generation_task_payload('generic-multi-audio')
        assert [reference_source_identity(url) for url in task['request_data']['v_reference_audio']] == expected
