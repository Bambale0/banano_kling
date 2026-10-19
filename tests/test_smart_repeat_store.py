"""Durable public service seam: recover uploads and claim one paid operation."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from bot import database
from bot import db as db_backend
from bot.smart_repeat_contract import AUTHORIZED_REPEAT, SmartRepeatError
from bot.smart_repeat_store import (
    claim_launch,
    get_template,
    load_draft,
    mutate_draft,
    open_draft,
    repeat_finance,
    save_quote,
    validate_inputs,
)


async def setup_repeat(monkeypatch, tmp_path):
    owner = await database.get_or_create_user(9911001)
    user = await database.get_or_create_user(9911002)
    source = {'id': 9100, 'user_id': owner.id, 'telegram_id': owner.telegram_id,
        'model': 'seedance_2_5', 'type': 'video', 'status': 'completed', 'is_public_feed': 1,
        'is_profile_visible': 0, 'duration': 5, 'aspect_ratio': '9:16', 'prompt': 'Use @Image1',
        'request_data': {'v_type': 'video', 'seedance25_scenario': 'multimodal',
                         'reference_images': ['/uploads/refs/source.png']},
        'feed_repeat_reference_selection': json.dumps({'version': 1, 'images': [], 'videos': []})}
    async with db_backend.connect() as db:
        await db.execute('INSERT INTO generation_tasks '
            '(id, user_id, telegram_id, task_id, type, model, status, is_public_feed, preset_id, '
            'is_profile_visible, duration, aspect_ratio, prompt, request_data, feed_repeat_reference_selection) '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'miniapp_video', ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (source['id'], owner.id, owner.telegram_id, 'smart-source', 'video', source['model'],
             'completed', 1, 1, 5, '9:16', source['prompt'], json.dumps(source['request_data']),
             source['feed_repeat_reference_selection']))
        await db.execute('UPDATE users SET credits = 100 WHERE id = ?', (user.id,))
        await db.commit()
    source = await database.get_generation_task_payload(9100)
    template = await get_template(source)
    draft = await open_draft(user, source, template)
    path = tmp_path / 'own.png'
    from PIL import Image
    Image.new('RGB', (32, 32), 'blue').save(path)
    monkeypatch.setattr('bot.services.media_input_utils.resolve_local_upload_path', lambda _: str(path))
    monkeypatch.setattr('bot.services.media_input_utils._resolve_local_upload_path', lambda _: str(path) if path.exists() else None)
    await database.save_user_reference(user.telegram_id, kind='image', file_url='/uploads/refs/own.png', file_hash='own')
    return SimpleNamespace(owner=owner, user=user, source=source, template=template,
                           draft=draft, slot=template['slots'][0]['slot_id'], path=path)


@pytest.mark.asyncio
async def test_upload_fencing_reload_delete_and_no_early_quote(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    first = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=ctx.slot)
    token = first['state']['slots'][ctx.slot]['upload_token']
    with pytest.raises(SmartRepeatError, match='REFERENCES_NOT_READY'):
        await validate_inputs(ctx.user, ctx.source, ctx.template, first)
    await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'remove', slot_id=ctx.slot)
    with pytest.raises(SmartRepeatError, match='UPLOAD_SUPERSEDED'):
        await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=ctx.slot,
                           upload_token=token, url='/uploads/refs/own.png')
    second = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=ctx.slot)
    second = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=ctx.slot,
        upload_token=second['state']['slots'][ctx.slot]['upload_token'], url='/uploads/refs/own.png')
    reloaded = await open_draft(ctx.user, ctx.source, ctx.template)
    assert reloaded['id'] == second['id']
    assert reloaded['state']['slots'][ctx.slot]['asset_id'] == second['state']['slots'][ctx.slot]['asset_id']
    await validate_inputs(ctx.user, ctx.source, ctx.template, reloaded)
    ctx.path.unlink()
    with pytest.raises(SmartRepeatError, match='REFERENCES_NOT_READY'):
        await validate_inputs(ctx.user, ctx.source, ctx.template, reloaded)
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100


@pytest.mark.asyncio
async def test_foreign_asset_and_extra_slot_never_enter_draft(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    await database.save_user_reference(ctx.owner.telegram_id, kind='image', file_url='/uploads/refs/foreign.png', file_hash='foreign')
    begun = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=ctx.slot)
    with pytest.raises(SmartRepeatError, match='ASSET_NOT_OWNED'):
        await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=ctx.slot,
            upload_token=begun['state']['slots'][ctx.slot]['upload_token'], url='/uploads/refs/foreign.png')
    with pytest.raises(SmartRepeatError, match='INVALID_SLOTS'):
        await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id='third-image')


@pytest.mark.asyncio
async def test_concurrent_launch_one_debit_and_refund_only_once(monkeypatch, tmp_path):
    ctx = await setup_repeat(monkeypatch, tmp_path)
    begun = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=ctx.slot)
    draft = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=ctx.slot,
        upload_token=begun['state']['slots'][ctx.slot]['upload_token'], url='/uploads/refs/own.png')
    compiled = await validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    quote = await save_quote(ctx.user, draft, ctx.template, {'cost': 10})
    draft = await load_draft(ctx.user.id, draft['id'])
    from bot.smart_repeat_store import _current_source
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        actual = await _current_source(db, ctx.source['id'])
    from bot.smart_repeat_contract import source_fingerprint
    assert source_fingerprint(actual) == source_fingerprint(ctx.source), {key: (type(actual.get(key)).__name__, actual.get(key), type(value).__name__, value) for key, value in ctx.source.items() if actual.get(key) != value}
    results = await asyncio.gather(*(claim_launch(ctx.user, ctx.source, ctx.template, draft,
        quote['quote_id'], compiled) for _ in range(4)), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert all(isinstance(result, (dict, SmartRepeatError)) for result in results)
    token = AUTHORIZED_REPEAT.set({'draft_id': draft['id'], 'user_id': ctx.user.id,
        'telegram_id': ctx.user.telegram_id, 'source_id': ctx.source['id'],
        'source_hash': ctx.template['source_hash']})
    try:
        assert not await repeat_finance(ctx.user.telegram_id, 10, refund=True)
        assert await repeat_finance(ctx.user.telegram_id, 10)
        with pytest.raises(SmartRepeatError, match='PRICE_CHANGED'):
            await repeat_finance(ctx.user.telegram_id, 10)
        refunds = await asyncio.gather(*(repeat_finance(ctx.user.telegram_id, 10, refund=True) for _ in range(4)))
        assert sum(refunds) == 1
    finally:
        AUTHORIZED_REPEAT.reset(token)
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100


async def claimed(ctx):
    begun = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'begin', slot_id=ctx.slot)
    draft = await mutate_draft(ctx.user, ctx.draft['id'], ctx.template, 'ready', slot_id=ctx.slot,
        upload_token=begun['state']['slots'][ctx.slot]['upload_token'], url='/uploads/refs/own.png')
    compiled = await validate_inputs(ctx.user, ctx.source, ctx.template, draft)
    quote = await save_quote(ctx.user, draft, ctx.template, {'cost': 10})
    draft = await load_draft(ctx.user.id, draft['id'])
    await claim_launch(ctx.user, ctx.source, ctx.template, draft, quote['quote_id'], compiled)
    return {'draft_id': draft['id'], 'user_id': ctx.user.id, 'telegram_id': ctx.user.telegram_id,
        'source_id': ctx.source['id'], 'source_hash': ctx.template['source_hash'],
        'template_version': ctx.template['version']}


@pytest.mark.asyncio
@pytest.mark.parametrize('accepted', [False, True])
async def test_real_image_engine_acceptance_controls_refund_and_recovery(monkeypatch, tmp_path, accepted):
    from unittest.mock import AsyncMock

    from bot.handlers import generation
    from bot.smart_repeat_store import recover_draft
    ctx = await setup_repeat(monkeypatch, tmp_path)
    token = AUTHORIZED_REPEAT.set(await claimed(ctx))
    provider = AsyncMock(return_value={'task_id': 'smart-image-provider'} if accepted else None)
    monkeypatch.setattr(generation.nano_banana_pro_service, 'generate_image', provider)
    monkeypatch.setattr(generation, '_available_reference_images', lambda refs: (refs, []))
    if accepted:
        # Acceptance survives a subsequent persistence exception; no resubmit.
        monkeypatch.setattr(generation, '_merge_task_id_aliases', lambda *args: (_ for _ in ()).throw(OSError('write failed')))
    try:
        assert await database.deduct_credits(ctx.user.telegram_id, 10)
        launch = generation._start_image_generation_task(user=ctx.user, telegram_id=ctx.user.telegram_id,
            img_service='banana_pro', prompt='Synthetic reference', img_ratio='1:1',
            reference_images=['/uploads/refs/own.png'], private_repeat_reference_images=[], unit_cost=10)
        if accepted:
            with pytest.raises(OSError):
                await launch
            assert not await repeat_finance(ctx.user.telegram_id, 10, refund=True)
        else:
            assert (await launch)['status'] == 'failed'
            # An overlapping reload may observe failure before the original
            # request refunds. Recovery must not revoke refund eligibility.
            await recover_draft(ctx.user, await load_draft(ctx.user.id, ctx.draft['id']))
            assert await repeat_finance(ctx.user.telegram_id, 10, refund=True)
    finally:
        AUTHORIZED_REPEAT.reset(token)
    draft = await load_draft(ctx.user.id, ctx.draft['id'])
    assert bool(draft['provider_accepted']) is accepted
    draft = await recover_draft(ctx.user, draft)
    assert draft['status'] == ('launched' if accepted else 'rejected')
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == (90 if accepted else 100)
    provider.assert_awaited_once()
    async with db_backend.connect() as db:
        count = await (await db.execute('SELECT COUNT(*) FROM generation_tasks WHERE user_id = ?', (ctx.user.id,))).fetchone()
    assert count[0] == 1
    if not accepted:
        fresh = await open_draft(ctx.user, ctx.source, ctx.template, new=True)
        assert fresh['status'] == 'draft' and fresh['id'] != draft['id']


@pytest.mark.asyncio
async def test_insufficient_balance_rejection_allows_explicit_new_operation(monkeypatch, tmp_path):
    from aiohttp import web

    from bot.smart_repeat_store import finish_launch
    ctx = await setup_repeat(monkeypatch, tmp_path)
    token = AUTHORIZED_REPEAT.set(await claimed(ctx))
    try:
        async with db_backend.connect() as db:
            await db.execute('UPDATE users SET credits = 0 WHERE id = ?', (ctx.user.id,))
            await db.commit()
        assert not await database.deduct_credits(ctx.user.telegram_id, 10)
        await finish_launch(ctx.user, ctx.draft['id'], web.json_response({'ok': False, 'code': 'insufficient_credits'}, status=400))
    finally:
        AUTHORIZED_REPEAT.reset(token)
    previous = await load_draft(ctx.user.id, ctx.draft['id'])
    assert previous['status'] == 'rejected'
    fresh = await open_draft(ctx.user, ctx.source, ctx.template, new=True)
    assert fresh['id'] != previous['id'] and fresh['status'] == 'draft'


@pytest.mark.asyncio
async def test_wan_committed_intent_remains_linked_after_submission_cancellation(monkeypatch, tmp_path):
    from bot.services.wan3_prime_lifecycle import Wan3PrimeActor, Wan3PrimeLifecycle
    from bot.smart_repeat_store import recover_draft
    from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider
    ctx = await setup_repeat(monkeypatch, tmp_path)
    async with db_backend.connect() as db:
        await db.execute("UPDATE generation_tasks SET model = 'wan_3_prime', prompt = 'Use @Image1', request_data = ? WHERE id = ?",
            (json.dumps({'model': 'wan_3_prime', 'scenario': 'reference', 'prompt': 'Use @Image1',
                'duration': 5, 'resolution': '720P', 'reference_image_urls': ['/uploads/refs/source.png']}), ctx.source['id']))
        await db.execute('DELETE FROM smart_repeat_drafts')
        await db.execute('DELETE FROM smart_repeat_templates')
        await db.commit()
    ctx.source = await database.get_generation_task_payload(ctx.source['id'])
    ctx.template = await get_template(ctx.source)
    ctx.slot = ctx.template['slots'][0]['slot_id']
    ctx.draft = await open_draft(ctx.user, ctx.source, ctx.template)
    context = await claimed(ctx)
    actor = Wan3PrimeActor(ctx.user.id, ctx.user.telegram_id, is_admin=False)
    provider = Provider()
    async def interrupted(*args, **kwargs):
        provider.creates += 1
        raise asyncio.CancelledError()
    provider.create_task = interrupted
    lifecycle = Wan3PrimeLifecycle(transport=provider, probe=Probe(), preset_manager=Prices())
    await lifecycle.init_schema()
    body = {'model': 'wan_3_prime', 'scenario': 'reference', 'prompt': 'Use @Image1',
        'duration': 5, 'resolution': '720P', 'reference_image_urls': ['https://example.test/own.png'],
        'idempotency_key': ctx.draft['id']}
    quote = (await lifecycle.quote(actor, body)).as_response()
    body['quote_hash'] = quote['quote_hash']
    token = AUTHORIZED_REPEAT.set(context)
    try:
        with pytest.raises(asyncio.CancelledError):
            await lifecycle.launch(actor, body, quote, ctx.draft['id'])
    finally:
        AUTHORIZED_REPEAT.reset(token)
    draft = await load_draft(ctx.user.id, ctx.draft['id'])
    assert draft['task_id'] and draft['charge_amount'] == quote['reserve_credits']
    assert not draft['provider_accepted']
    restored = await recover_draft(ctx.user, draft)
    assert restored['task_id'] == draft['task_id'] and restored['result']['body']['task_id'] == draft['task_id']
    assert provider.creates == 1
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100 - quote['reserve_credits']
    # Diagnostics reads the authoritative later settlement without crediting a
    # second refund or treating the original draft reservation as final charge.
    async with db_backend.connect() as db:
        await db.execute('UPDATE wan3_prime_intents SET settled = 1, charged_credits = 6, refunded_credits = 4 '
            'WHERE internal_task_id = ?', (draft['task_id'],))
        await db.commit()
    from bot.smart_repeat_store import diagnostic_finance
    finance = await diagnostic_finance(draft)
    assert finance['billing_source'] == 'wan_intent'
    assert finance['charge_amount'] == 6 and finance['refund_amount'] == 4
    assert (await database.get_or_create_user(ctx.user.telegram_id)).credits == 100 - quote['reserve_credits']
