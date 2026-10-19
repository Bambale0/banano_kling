"""Durable public service seam: recover uploads and claim one paid operation."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from bot import database
from bot import db as db_backend
from bot.smart_repeat_contract import AUTHORIZED_REPEAT, SmartRepeatError
from bot.smart_repeat_store import (
    claim_launch, get_template, load_draft, mutate_draft, open_draft,
    repeat_finance, save_quote, validate_inputs,
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
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'miniapp_video', ?, ?, ?, ?, ?, ?)",
            (source['id'], owner.id, owner.telegram_id, 'smart-source', 'video', source['model'],
             'completed', 1, 0, 5, '9:16', source['prompt'], json.dumps(source['request_data']),
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
    results = await asyncio.gather(*(claim_launch(ctx.user, ctx.source, ctx.template, draft,
        quote['quote_id'], compiled) for _ in range(4)), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
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
