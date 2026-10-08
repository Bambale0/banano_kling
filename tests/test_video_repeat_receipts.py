"""Durable typed-repeat reservation and existing task lifecycle invariants."""
import asyncio
import json

import pytest

from bot import database
from bot.services import task_watchdog
from bot.services.task_watchdog import force_fail_task, get_stuck_tasks


@pytest.fixture(autouse=True)
def isolated_watchdog_path(monkeypatch, isolated_database):
    monkeypatch.setattr(task_watchdog, "DATABASE_PATH", database.DATABASE_PATH)


async def reserve(user, source=42):
    return await database.reserve_private_video_repeat(
        user_id=user.id, telegram_id=user.telegram_id, source_id=source,
        model='seedance_2_5', duration=5, aspect_ratio='9:16')


@pytest.mark.asyncio
async def test_same_user_source_atomic_receipt_and_independent_controls():
    user = await database.get_or_create_user(882001)
    other = await database.get_or_create_user(882002)
    receipts = await asyncio.gather(*(reserve(user) for _ in range(5)))
    assert sum(item['created'] for item in receipts) == 1
    assert len({item['task_id'] for item in receipts}) == 1
    receipt = receipts[0]
    task = await database.get_task_by_id(receipt['task_id'])
    assert task.status == 'processing'
    assert (await reserve(user, 43))['created']
    assert (await reserve(other))['created']
    assert await database.finish_private_video_repeat(receipt['task_id'], user.id, phase='rejected', terminal=True)
    assert (await reserve(user))['created']


@pytest.mark.asyncio
async def test_reserved_receipt_promotes_same_row_and_preserves_callback_alias():
    user = await database.get_or_create_user(882003)
    receipt = await reserve(user)
    initial = await database.get_task_by_id(receipt['task_id'])
    await database.finish_private_video_repeat(receipt['task_id'], user.id, phase='launching', cost=3)
    assert await database.add_generation_task(
        user.id, user.telegram_id, 'synthetic-accepted-id', 'video', 'miniapp_video',
        model='seedance_2_5', cost=3, request_data={'video_repeat_contract_version': 1},
        source_feed_gen_id=42, parent_generation_id=42, action_type='repeat',
        reserved_task_id=receipt['task_id'])
    current = await database.get_task_by_id('synthetic-accepted-id')
    alias = await database.get_task_by_id(receipt['task_id'])
    assert initial.id == current.id == alias.id
    assert current.status == 'pending'
    assert current.cost == 3
    assert json.loads(current.request_data)['video_repeat_receipt'] is True
    assert not (await reserve(user))['created']
    await database.complete_video_task('synthetic-accepted-id', 'https://example.test/result.mp4')
    assert (await reserve(user))['created']


@pytest.mark.asyncio
async def test_unknown_receipt_cannot_be_timed_out_or_taken_over():
    user = await database.get_or_create_user(882004)
    foreign = await database.get_or_create_user(882005)
    receipt = await reserve(user)
    task = await database.get_task_by_id(receipt['task_id'])
    assert not await database.finish_private_video_repeat(receipt['task_id'], foreign.id, phase='rejected', terminal=True)
    with pytest.raises(ValueError):
        await database.add_generation_task(foreign.id, foreign.telegram_id, 'foreign-task', 'video', 'miniapp_video',
            reserved_task_id=receipt['task_id'])
    assert not await force_fail_task(task.id, user.id, 3)
    assert not any(item['task_id'] == receipt['task_id'] for item in await get_stuck_tasks(minutes=0))
    assert not (await reserve(user))['created']


from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import db as db_backend
from bot import miniapp
from bot.handlers import seedance_25_public_release as public
from bot.services.seedance_service import seedance_service
from tests.test_video_repeat_private_contract import (
    REAL_GENERIC,
)
from tests.test_video_repeat_private_contract import (
    typed_video_entrypoint as typed_video_entrypoint,  # noqa: PLC0414 - pytest fixture re-export
)


async def configure_actual_entry(monkeypatch, entry, model):
    owner = await database.get_or_create_user(882101)
    viewer = await database.get_or_create_user(882102)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute('UPDATE users SET credits = 100 WHERE id = ?', (viewer.id,))
        await db.commit()
    monkeypatch.setattr(miniapp, 'DATABASE_PATH', database.DATABASE_PATH)
    entry.context.return_value = (viewer.telegram_id, {'user': SimpleNamespace(id=viewer.id, credits=100)})
    entry.source.update(user_id=owner.id, model=model, is_public_feed=True)
    miniapp._get_repeat_source_card.return_value.update(model=model)
    monkeypatch.setattr(miniapp, 'get_generation_task_payload', AsyncMock(side_effect=lambda *_: dict(entry.source)))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, 'missing_local_upload_sources', lambda _: [])
    monkeypatch.setattr(miniapp, 'touch_saved_references', AsyncMock())
    monkeypatch.setattr(miniapp.preset_manager, 'get_video_cost_with_quality', lambda *_: 1)
    monkeypatch.setattr(public.preview_module, '_price_quote', lambda _: 2)
    monkeypatch.setattr(public, '_validate_public_payload', AsyncMock())
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', AsyncMock())
    debit = AsyncMock(wraps=database.deduct_credits)
    refund = AsyncMock(wraps=database.add_credits)
    monkeypatch.setattr(miniapp, 'deduct_credits', debit)
    monkeypatch.setattr(miniapp, 'add_credits', refund)
    provider = AsyncMock(return_value={'task_id': 'synthetic-receipt-provider'})
    service = public.seedance_25_service if model == 'seedance_2_5' else seedance_service
    monkeypatch.setattr(service, 'generate_video', provider)
    async def delegate(request):
        if model == 'seedance_2_5':
            return await public._public_miniapp_generate(request, await request.json())
        return await REAL_GENERIC(request)
    entry.delegate.side_effect = delegate
    def request():
        return entry.request({'v_model': model, 'v_type': 'video', 'v_duration': 5, 'v_ratio': '9:16',
            'reference_images': ['https://example.test/own.png'], 'v_reference_videos': ['https://example.test/own.mp4']})
    return viewer, debit, refund, provider, request


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
async def test_two_device_requests_share_one_durable_charge_and_provider(monkeypatch, typed_video_entrypoint, model):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    responses = await asyncio.gather(entry.call(request()), entry.call(request()))
    assert sorted(response.status for response in responses) == [200, 409]
    debit.assert_awaited_once_with(viewer.telegram_id, 2)
    provider.assert_awaited_once()
    refund.assert_not_awaited()
    task = await database.get_task_by_id('synthetic-receipt-provider')
    assert task.status == 'pending' and task.cost == 2
    aliases = json.loads(task.request_data)['task_id_aliases']
    receipt_id = next(alias for alias in aliases if alias.startswith('video_repeat_receipt_'))
    assert (await database.get_task_by_id(receipt_id)).id == task.id
    # The existing provider callback loader sees the promoted canonical ID.
    if model == 'seedance_2_5':
        loaded = await public.fullstack._load_task_row('synthetic-receipt-provider')
        assert loaded['id'] == task.id
    await database.complete_video_task(task.task_id, 'https://example.test/result.mp4')
    detail = await miniapp.miniapp_task_detail(entry.request({'task_id': receipt_id}))
    assert detail.status == 200
    detail_payload = json.loads(detail.text)['task']
    assert detail_payload['task_id'] == task.task_id
    assert detail_payload['status'] == 'completed'
    entry.context.return_value = (882101, {'user': SimpleNamespace(id=entry.source['user_id'])})
    assert (await miniapp.miniapp_task_detail(entry.request({'task_id': receipt_id}))).status == 404
    entry.context.return_value = (viewer.telegram_id, {'user': SimpleNamespace(id=viewer.id, credits=98)})
    provider.return_value = {'task_id': 'synthetic-next-intended-repeat'}
    assert (await entry.call(request())).status == 200
    assert provider.await_count == debit.await_count == 2
    assert (await database.get_task_by_id('synthetic-next-intended-repeat')).id != task.id


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
@pytest.mark.parametrize('case', ['binding_failure', 'binding_false', 'provider_exception', 'debit_before_error', 'debit_after_error', 'debit_cancelled_before', 'debit_cancelled_after', 'provider_cancelled', 'refund_uncertain'])
async def test_unknown_receipt_survives_new_session_without_second_charge(monkeypatch, typed_video_entrypoint, model, case):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    if case in {'binding_failure', 'binding_false'}:
        target = public.generation_module if model == 'seedance_2_5' else miniapp
        monkeypatch.setattr(target, 'add_generation_task',
            AsyncMock(return_value=False) if case == 'binding_false'
            else AsyncMock(side_effect=RuntimeError('synthetic binding failure')))
    elif case == 'provider_exception':
        provider.side_effect = RuntimeError('synthetic uncertain transport')
    elif case in {'debit_before_error', 'debit_after_error', 'debit_cancelled_before', 'debit_cancelled_after'}:
        async def uncertain_debit(telegram_id, amount):
            if case in {'debit_after_error', 'debit_cancelled_after'}:
                await database.deduct_credits(telegram_id, amount)
            if case.startswith('debit_cancelled'):
                raise asyncio.CancelledError()
            raise RuntimeError('synthetic uncertain debit')
        debit.side_effect = uncertain_debit
    elif case == 'provider_cancelled':
        provider.side_effect = asyncio.CancelledError()
    elif case == 'refund_uncertain':
        provider.return_value = {'error': 'synthetic rejected'}
        async def uncertain_refund(telegram_id, amount):
            await database.add_credits(telegram_id, amount)
            raise RuntimeError('synthetic uncertain refund acknowledgement')
        refund.side_effect = uncertain_refund
    if case == 'provider_cancelled' or case.startswith('debit_cancelled'):
        with pytest.raises(asyncio.CancelledError):
            await entry.call(request())
    else:
        first = await entry.call(request())
        assert first.status >= 400
    second = await entry.call(request())
    assert second.status == 409
    payload = json.loads(second.text)
    assert payload['code'] == 'video_status_pending'
    task = await database.get_task_by_id(payload['task_id'])
    assert task.user_id == viewer.id and task.status == 'processing'
    debit.assert_awaited_once()
    assert provider.await_count == (0 if case.startswith('debit_') else 1)
    assert refund.await_count == (1 if case in {'provider_exception', 'refund_uncertain'} else 0)
    balance = (await database.get_or_create_user(viewer.telegram_id)).credits
    assert balance == (100 if case in {'provider_exception', 'refund_uncertain', 'debit_before_error', 'debit_cancelled_before'} else 98)
    if case.startswith('debit_'):
        assert json.loads(task.request_data)['repeat_attempted_cost'] == 2
        assert json.loads(task.request_data)['repeat_receipt_phase'] == ('debit_pending' if 'cancelled' in case else 'debit_unknown')
    assert not await force_fail_task(task.id, viewer.id, task.cost)


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
@pytest.mark.parametrize('case', ['reservation_error', 'debit_refused', 'rejected'])
async def test_known_no_launch_can_release_receipt_without_double_refund(monkeypatch, typed_video_entrypoint, model, case):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    if case == 'reservation_error':
        monkeypatch.setattr(database, 'reserve_private_video_repeat', AsyncMock(side_effect=RuntimeError('synthetic storage unavailable')))
    elif case == 'debit_refused':
        debit.return_value = False
        debit.side_effect = None
    else:
        provider.return_value = {'error': 'synthetic rejected'}
    response = await entry.call(request())
    assert response.status >= 400
    if case == 'reservation_error':
        debit.assert_not_awaited()
    if case != 'rejected':
        provider.assert_not_awaited()
        refund.assert_not_awaited()
    else:
        refund.assert_awaited_once_with(viewer.telegram_id, 2)
    if case != 'reservation_error':
        assert (await reserve(viewer))['created']


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
async def test_preprovider_receipt_history_and_detail_never_expose_source_recipe(monkeypatch, typed_video_entrypoint, model):
    entry = typed_video_entrypoint
    viewer, _debit, _refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed_provider(**_kwargs):
        entered.set()
        await release.wait()
        return {'task_id': 'synthetic-receipt-provider'}
    provider.side_effect = delayed_provider
    launch = asyncio.create_task(entry.call(request()))
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        history = await miniapp._fetch_recent_tasks(viewer.telegram_id)
        assert len(history) == 1
        item = history[0]
        assert item['status'] == 'pending'
        assert (await database.get_task_by_id(item['task_id'])).status == 'processing'
        assert item['prompt_hidden'] is True
        assert not item.get('prompt')
        detail = await miniapp.miniapp_task_detail(entry.request({'task_id': item['task_id']}))
        assert detail.status == 200
        assert json.loads(detail.text)['task']['status'] == 'pending'
        for secret in ('Synthetic private recipe', 'author-face.png', 'fixed-cake.png', 'author-motion.mp4', 'fixed-style.mp4'):
            assert secret not in json.dumps(history)
            assert secret not in detail.text
    finally:
        release.set()
        await launch


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
async def test_source_withdrawal_while_reserving_stops_before_charge(monkeypatch, typed_video_entrypoint, model):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    original = database.reserve_private_video_repeat
    async def withdraw_after_reservation(**kwargs):
        receipt = await original(**kwargs)
        entry.source['is_public_feed'] = False
        return receipt
    monkeypatch.setattr(database, 'reserve_private_video_repeat', withdraw_after_reservation)
    response = await entry.call(request())
    assert response.status in (400, 403, 404)
    debit.assert_not_awaited()
    refund.assert_not_awaited()
    provider.assert_not_awaited()
    assert (await original(user_id=viewer.id, telegram_id=viewer.telegram_id, source_id=42,
        model=model, duration=5, aspect_ratio='9:16'))['created']


@pytest.mark.asyncio
async def test_provider_id_collision_preserves_both_tasks_and_receipt_blocker():
    user = await database.get_or_create_user(882020)
    foreign = await database.get_or_create_user(882021)
    await database.add_generation_task(foreign.id, foreign.telegram_id, 'synthetic-existing-provider', 'video', 'miniapp_video')
    receipt = await reserve(user)
    with pytest.raises(db_backend.IntegrityError):
        await database.add_generation_task(user.id, user.telegram_id, 'synthetic-existing-provider', 'video', 'miniapp_video',
            reserved_task_id=receipt['task_id'])
    assert (await database.get_task_by_id('synthetic-existing-provider')).user_id == foreign.id
    assert (await database.get_task_by_id(receipt['task_id'])).status == 'processing'
    assert not (await reserve(user))['created']


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['seedance_2', 'seedance_2_5'])
async def test_typed_admin_receipt_is_durable_without_any_charge(monkeypatch, typed_video_entrypoint, model):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, model)
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: True)
    assert (await entry.call(request())).status == 200
    assert (await entry.call(request())).status == 409
    debit.assert_not_awaited()
    refund.assert_not_awaited()
    provider.assert_awaited_once()
    task = await database.get_task_by_id('synthetic-receipt-provider')
    assert task.cost == 0
    assert json.loads(task.request_data).get('repeat_attempted_cost', 0) == 0
    assert (await database.get_or_create_user(viewer.telegram_id)).credits == 100


@pytest.mark.asyncio
async def test_completed_bytes_save_failure_returns_bound_canonical_receipt_id(monkeypatch, typed_video_entrypoint):
    entry = typed_video_entrypoint
    viewer, debit, refund, provider, request = await configure_actual_entry(monkeypatch, entry, 'seedance_2')
    provider.return_value = b'synthetic completed bytes'
    def failed_save(*_args):
        raise RuntimeError('synthetic storage failure')
    monkeypatch.setattr(miniapp, '_save_uploaded_file_lazy', failed_save)
    response = await entry.call(request())
    assert response.status == 500
    payload = json.loads(response.text)
    assert payload['code'] == 'video_status_pending'
    history = await miniapp._fetch_recent_tasks(viewer.telegram_id)
    assert payload['task_id'] == history[0]['task_id']
    assert (await database.get_task_by_id(payload['task_id'])).status == 'pending'
    debit.assert_awaited_once_with(viewer.telegram_id, 2)
    provider.assert_awaited_once()
    refund.assert_not_awaited()
