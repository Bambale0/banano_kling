"""Optional photo inputs: actual HTTP image adapter and durable upload state."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database, miniapp
from bot import db as db_backend
from bot import smart_repeat_store as store
from bot.smart_repeat_api import setup_smart_repeat_routes
from bot.smart_repeat_contract import SmartRepeatError
from tests.test_smart_repeat_store import setup_repeat


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    # Even a production-like host must never supply a real Redis cache to these fixtures.
    monkeypatch.setattr('bot.services.redis_service.redis_service.get_client', AsyncMock(return_value=None))


async def image_fixture(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    from bot.handlers import generation
    # Two original positions, the second is an explicitly authorized fixed input.
    monkeypatch.setattr(generation, '_get_max_image_references', lambda _: 4)
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET type='image', model='banana_pro', prompt=?, "
            "result_url=?, request_data=?, feed_repeat_reference_selection=? WHERE id=?",
            ('Private @Image1 face @Image2 scene', 'https://example.test/result.png',
             json.dumps({'source_reference_images': ['/uploads/refs/face.png', '/uploads/refs/scene.png']}),
             json.dumps({'images': ['/uploads/refs/scene.png']}), ctx.source['id']))
        await db.execute('DELETE FROM smart_repeat_drafts')
        await db.execute('DELETE FROM smart_repeat_templates')
        await db.commit()
    ctx.source = await database.get_generation_task_payload(ctx.source['id'])
    ctx.template = await store.get_template(ctx.source)
    ctx.draft = await store.open_draft(ctx.user, ctx.source, ctx.template)
    ctx.slot = ctx.template['slots'][0]['slot_id']
    for name in ('phone', 'nails'):
        await database.save_user_reference(ctx.user.telegram_id, kind='image',
            file_url=f'/uploads/refs/{name}.png', file_hash=name, original_filename=f'{name}.png')
    return ctx


async def attach(ctx, sid, url):
    begun = await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=sid)
    return await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=sid,
        upload_token=begun['state']['slots'][sid]['upload_token'], url=url)


@pytest.mark.asyncio
async def test_optional_photo_budget_and_fixed_positions_survive_remove_reload(monkeypatch, tmp_path):
    ctx = await image_fixture(monkeypatch, tmp_path)
    public = store.public_draft(ctx.draft, ctx.template)
    assert public['additional_image_limit'] == 2
    extra = public['additional_image_slots']
    assert len(extra) == 2 and all(not s['required'] for s in extra)
    assert 'scene.png' not in json.dumps(public) and 'Private' not in json.dumps(public)
    # Empty extras are optional and don't appear in provider inputs.
    draft = await attach(ctx, ctx.slot, '/uploads/refs/own.png')
    compiled = await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    assert compiled['body']['reference_images'] == ['/uploads/refs/own.png']
    # Upload in reverse order; named original positions must never move.
    await attach(ctx, extra[1]['slot_id'], '/uploads/refs/nails.png')
    draft = await attach(ctx, extra[0]['slot_id'], '/uploads/refs/phone.png')
    compiled = await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    assert compiled['source']['request_data']['source_reference_images'] == [
        '/uploads/refs/own.png', '/uploads/refs/scene.png', '/uploads/refs/phone.png', '/uploads/refs/nails.png']
    await store.save_quote(ctx.user, draft, ctx.template, {'cost': 10})
    draft = await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'remove', slot_id=extra[0]['slot_id'])
    assert draft['quote'] is None
    draft = await store.refresh_draft_media(ctx.user, await store.open_draft(ctx.user, ctx.source, ctx.template))
    compiled = await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    assert compiled['source']['request_data']['source_reference_images'] == [
        '/uploads/refs/own.png', '/uploads/refs/scene.png', '/uploads/refs/nails.png']
    assert compiled['snapshot']['references'][extra[1]['slot_id']]['index'] == 2
    assert len((await store.get_template(ctx.source))['slots']) == 2


@pytest.mark.asyncio
async def test_extra_pending_foreign_duplicate_and_superseded_media_are_rejected(monkeypatch, tmp_path):
    ctx = await image_fixture(monkeypatch, tmp_path)
    extra = store.public_draft(ctx.draft, ctx.template)['additional_image_slots'][0]['slot_id']
    await attach(ctx, ctx.slot, '/uploads/refs/own.png')
    begun = await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=extra)
    token = begun['state']['slots'][extra]['upload_token']
    with pytest.raises(SmartRepeatError, match='REFERENCES_NOT_READY'):
        await store.validate_inputs(ctx.user, ctx.source, ctx.template, begun)
    await database.save_user_reference(ctx.owner.telegram_id, kind='image', file_url='/uploads/foreign.png', file_hash='foreign')
    with pytest.raises(SmartRepeatError, match='ASSET_NOT_OWNED'):
        await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=extra,
            upload_token=token, url='/uploads/foreign.png')
    await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'remove', slot_id=extra)
    with pytest.raises(SmartRepeatError, match='UPLOAD_SUPERSEDED'):
        await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=extra,
            upload_token=token, url='/uploads/refs/phone.png')
    draft = await attach(ctx, extra, '/uploads/refs/own.png')
    with pytest.raises(SmartRepeatError, match='DUPLICATE_ASSET'):
        await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    with pytest.raises(SmartRepeatError, match='INVALID_SLOTS'):
        await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id='extra_image_99')
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100


@pytest.mark.asyncio
async def test_reduced_budget_preserves_existing_extras_for_removal_without_truncation(monkeypatch, tmp_path):
    from bot.handlers import generation
    ctx = await image_fixture(monkeypatch, tmp_path)
    extras = store.public_draft(ctx.draft, ctx.template)['additional_image_slots']
    await attach(ctx, ctx.slot, '/uploads/refs/own.png')
    await attach(ctx, extras[0]['slot_id'], '/uploads/refs/phone.png')
    draft = await attach(ctx, extras[1]['slot_id'], '/uploads/refs/nails.png')
    monkeypatch.setattr(generation, '_get_max_image_references', lambda _: 3)
    public = store.public_draft(draft, ctx.template)
    assert public['additional_image_limit'] == 1
    assert len(public['additional_image_slots']) == 2
    with pytest.raises(SmartRepeatError, match='MODEL_CONSTRAINTS_INVALID'):
        await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    draft = await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'remove', slot_id=extras[0]['slot_id'])
    compiled = await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    assert compiled['body']['reference_images'] == ['/uploads/refs/own.png', '/uploads/refs/nails.png']
    assert len(compiled['snapshot']['references']) == 3


@pytest.mark.asyncio
async def test_video_repeat_never_accepts_optional_photo_slots(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    public = store.public_draft(ctx.draft, ctx.template)
    assert public['additional_image_limit'] == 0 and public['additional_image_slots'] == []
    with pytest.raises(SmartRepeatError, match='INVALID_SLOTS'):
        await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id='extra_image_0')


@pytest.mark.asyncio
async def test_http_extras_reach_real_image_engine_after_main_and_fixed_refs_once(monkeypatch, tmp_path):
    from bot.handlers import generation
    ctx = await image_fixture(monkeypatch, tmp_path)
    await database.set_bot_setting('smart_repeat_rollout', json.dumps({'enabled': True}))
    monkeypatch.setattr(database, '_is_feed_result_url_available', lambda *args: True)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(ctx.user.telegram_id, {'user': ctx.user})))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, '_resolve_image_unit_cost', lambda *_: 10)
    monkeypatch.setattr(generation, '_available_reference_images', lambda refs: (refs, []))
    provider = AsyncMock(return_value={'task_id': 'extra-photo-synthetic'})
    monkeypatch.setattr(generation.nano_banana_pro_service, 'generate_image', provider)
    references = {ref.file_url: str(ref.id) for ref in await database.list_saved_references(ctx.user.telegram_id)}
    app = web.Application()
    setup_smart_repeat_routes(app, '/mini-app')
    async with TestClient(TestServer(app)) as client:
        async def call(action, **payload):
            response = await client.post('/mini-app/api/repeat/' + action, json={'init_data': 'signed', **payload})
            return response.status, await response.json()
        _, draft = await call('open', source_id=ctx.source['id'])
        did = draft['draft_id']
        main = draft['template']['slots'][0]['slot_id']
        extras = draft['additional_image_slots']
        for sid, name in ((main, 'own'), (extras[1]['slot_id'], 'nails'), (extras[0]['slot_id'], 'phone')):
            status, begun = await call('update', draft_id=did, operation='begin', slot_id=sid)
            assert status == 200, begun
            status, draft = await call('update', draft_id=did, operation='ready', slot_id=sid,
                upload_token=begun['slots'][sid]['upload_token'], saved_reference_id=references[f'/uploads/refs/{name}.png'])
            assert status == 200, draft
            if sid == main:
                status, old_quote = await call('quote', draft_id=did)
                assert status == 200, old_quote
        status, stale = await call('launch', draft_id=did, quote_id=old_quote['quote']['quote_id'])
        assert status == 409 and stale['code'] == 'PRICE_CHANGED'
        provider.assert_not_awaited()
        status, restored = await call('open', source_id=ctx.source['id'])
        assert status == 200 and restored['slots'] == draft['slots']
        status, quote = await call('quote', draft_id=did)
        assert status == 200, quote
        provider.assert_not_awaited()
        results = await asyncio.gather(*(call('launch', draft_id=did, quote_id=quote['quote']['quote_id']) for _ in range(2)))
        assert any(code < 400 for code, _ in results), results
        provider.assert_awaited_once()
        assert provider.await_args.kwargs['image_input'] == [
            '/uploads/refs/own.png', '/uploads/refs/scene.png', '/uploads/refs/phone.png', '/uploads/refs/nails.png']
        assert provider.await_args.kwargs['prompt'].startswith('Private @Image1 face @Image2 scene')
        assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 90


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['none', 'forged', 'wrong_user', 'wrong_source', 'valid'])
async def test_source_filter_exception_requires_exact_server_capability(mode):
    from bot.smart_repeat_contract import AUTHORIZED_REPEAT
    source = {'id': 42, 'request_data': {'source_reference_images': ['/uploads/own.png', '/uploads/private.png']}}
    capability = {'source_id': 99 if mode == 'wrong_source' else 42, 'telegram_id': 99 if mode == 'wrong_user' else 7,
                  'owned_inputs': {'/uploads/own.png'}}
    if mode != 'none':
        source['_smart_repeat_authorization'] = dict(capability) if mode == 'forged' else capability
    token = AUTHORIZED_REPEAT.set(None if mode == 'none' else capability)
    try:
        result = miniapp._filter_foreign_feed_source_references({'is_mine': False}, source,
            ['/uploads/own.png', '/uploads/private.png'], viewer_telegram_id=7)
        assert result == (['/uploads/own.png'] if mode == 'valid' else [])
    finally:
        AUTHORIZED_REPEAT.reset(token)


@pytest.mark.asyncio
async def test_optional_images_survive_preset_change_and_are_in_retention_graph(monkeypatch, tmp_path):
    from bot.services.reference_retention import reference_snapshot_query
    from bot.smart_repeat_contract import public_template
    ctx = await image_fixture(monkeypatch, tmp_path)
    submitted = public_template(ctx.template, author=True)
    submitted['presets'] = [{'id': 'face', 'label': 'Face', 'slot_ids': [ctx.slot]}]
    ctx.template = await store.save_template(ctx.owner, ctx.source, submitted)
    ctx.draft = await store.open_draft(ctx.user, ctx.source, ctx.template)
    extra = store.public_draft(ctx.draft, ctx.template)['additional_image_slots'][0]['slot_id']
    await attach(ctx, ctx.slot, '/uploads/refs/own.png')
    await attach(ctx, extra, '/uploads/refs/phone.png')
    draft = await store.mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'preset', preset_id='face')
    assert draft['state']['slots'][extra]['state'] == 'READY'
    compiled = await store.validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    assert compiled['body']['reference_images'] == ['/uploads/refs/own.png', '/uploads/refs/phone.png']
    async with db_backend.connect() as db:
        rows = await (await db.execute(reference_snapshot_query(postgres=db_backend.is_postgres()))).fetchall()
    assert '/uploads/refs/phone.png' in {row[0] for row in rows}
