"""Native repeat durability and pre-debit access regression tests; no providers."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import types

from bot import database
from bot import db as db_backend
from bot import smart_repeat_store as store
from bot.handlers import generation, native_repeat_contract, native_repeat_receipt
from bot.smart_repeat_contract import AUTHORIZED_REPEAT, SmartRepeatError
from tests.test_telegram_repeat_no_miniapp import (
    TASK_ID,
    configure_named_template,
    published_context,
)


async def real_finance_context(monkeypatch):
    ctx = await published_context(monkeypatch)
    await database.add_credits(ctx.owner.telegram_id, 100)
    ctx.start_credits = (await database.get_or_create_user(ctx.owner.telegram_id)).credits
    monkeypatch.setattr(generation, 'deduct_credits', database.deduct_credits)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    data = await ctx.state.get_data()
    ctx.token = data['repeat_quote_id']
    ctx.data = data
    ctx.contract = await native_repeat_contract.load_contract(ctx.task, ctx.owner.telegram_id)
    ctx.callback.data = f'repeat_q_{ctx.token}'
    return ctx


@pytest.mark.asyncio
async def test_cancel_after_atomic_debit_has_durable_receipt_and_refunds_once_on_reopen(monkeypatch):
    ctx = await real_finance_context(monkeypatch)
    ctx.launch.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    receipt = await store.load_draft(ctx.owner.id, 'tg:' + ctx.token)
    assert receipt['charge_amount'] == 10 and receipt['refund_amount'] == 0
    assert receipt['task_id'] is None and receipt['provider_accepted'] == 0
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits - 10
    await ctx.state.clear()  # emulate a lost worker/FSM, not a normal in-process retry
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    receipt = await store.load_draft(ctx.owner.id, 'tg:' + ctx.token)
    assert receipt['status'] == 'rejected' and receipt['refund_amount'] == 10
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits
    assert await native_repeat_receipt.recover_unsubmitted(ctx.owner, ctx.task.id) == 0
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits


@pytest.mark.asyncio
async def test_refunded_receipt_fences_a_suspended_worker_before_task_and_provider(monkeypatch):
    ctx = await real_finance_context(monkeypatch)
    async with native_repeat_receipt.authorized_launch(ctx.owner, ctx.contract, ctx.data, ctx.token, 10):
        assert await database.deduct_credits(ctx.owner.telegram_id, 10)
        assert await native_repeat_receipt.recover_unsubmitted(ctx.owner, ctx.task.id) == 10
        with pytest.raises(SmartRepeatError):
            await database.add_generation_task(ctx.owner.id, ctx.owner.telegram_id,
                'late-task', 'image', 'banana_pro', model='banana_pro', cost=10)
    assert await database.get_task_by_id('late-task') is None
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits
    assert AUTHORIZED_REPEAT.get() is None


@pytest.mark.asyncio
async def test_cancel_after_task_capture_never_guesses_provider_failure_or_refunds(monkeypatch):
    ctx = await real_finance_context(monkeypatch)
    async def accepted_then_cancelled(**kwargs):
        await database.add_generation_task(ctx.owner.id, ctx.owner.telegram_id,
            'captured-task', 'image', 'banana_pro', model='banana_pro', cost=10,
            source_feed_gen_id=ctx.task.id)
        raise asyncio.CancelledError
    ctx.launch.side_effect = accepted_then_cancelled
    with pytest.raises(asyncio.CancelledError):
        await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    receipt = await store.load_draft(ctx.owner.id, 'tg:' + ctx.token)
    assert receipt['task_id'] == 'captured-task' and receipt['charge_amount'] == 10
    assert await native_repeat_receipt.recover_unsubmitted(ctx.owner, ctx.task.id) == 0
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits - 10
    assert await native_repeat_receipt.replay_message(ctx.owner.telegram_id, ctx.token)


@pytest.mark.asyncio
async def test_native_claim_is_atomic_across_independent_contexts_and_hidden_from_miniapp(monkeypatch):
    ctx = await real_finance_context(monkeypatch)
    async def attempt():
        try:
            async with native_repeat_receipt.authorized_launch(ctx.owner, ctx.contract, ctx.data, ctx.token, 10):
                assert await database.deduct_credits(ctx.owner.telegram_id, 10)
            return True
        except SmartRepeatError as exc:
            assert exc.code == 'OPERATION_ALREADY_CREATED'
            return False
    results = await asyncio.gather(attempt(), attempt())
    assert results.count(True) == 1 and results.count(False) == 1
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits - 10
    assert await store.latest_draft(ctx.owner.id, ctx.task.id) is None
    template = await store.get_template(ctx.contract['source'])
    normal = await store.open_draft(ctx.owner, ctx.contract['source'], template)
    assert not normal['id'].startswith('tg:') and normal['status'] == 'draft'
    assert (await store.latest_draft(ctx.owner.id, ctx.task.id))['id'] == normal['id']


@pytest.mark.asyncio
async def test_template_less_withdrawn_source_rejected_before_debit(monkeypatch):
    ctx = await published_context(monkeypatch)
    viewer = await database.get_or_create_user(840052)
    ctx.callback.from_user = SimpleNamespace(id=viewer.telegram_id)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    data = await ctx.state.get_data()
    assert data['repeat_native_template_marker']
    async with db_backend.connect() as db:
        await db.execute('UPDATE generation_tasks SET is_public_feed = 0, is_profile_visible = 0 WHERE task_id = ?', (TASK_ID,))
        await db.commit()
    ctx.callback.data = f'repeat_q_{data["repeat_quote_id"]}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.debit.assert_not_awaited()
    ctx.launch.assert_not_awaited()
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True


@pytest.mark.asyncio
async def test_named_slot_hint_is_escaped_and_shown_in_chat(monkeypatch):
    from bot.smart_repeat_contract import public_template
    ctx = await published_context(monkeypatch)
    await configure_named_template(ctx)
    source = await database.get_generation_task_payload(TASK_ID)
    template = await store.get_template(source)
    body = public_template(template, author=True)
    body['slots'][0]['hint'] = 'Only <one face> & no glasses'
    await store.save_template(ctx.owner, source, body)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    rendered = ctx.callback.message.answer.await_args.args[0]
    assert 'Only &lt;one face&gt; &amp; no glasses' in rendered


@pytest.mark.asyncio
async def test_admin_feed_deeplink_quote_launches_without_reconfirmation_loop(monkeypatch):
    from bot.handlers.common import _open_repeat_screen_from_feed_deeplink
    ctx = await published_context(monkeypatch)
    monkeypatch.setattr(generation.config, 'is_admin', lambda _: True)
    message = MagicMock(spec=types.Message)
    message.from_user = ctx.callback.from_user
    message.answer = AsyncMock()
    await _open_repeat_screen_from_feed_deeplink(message, ctx.state, ctx.owner, str(ctx.task.id))
    data = await ctx.state.get_data()
    assert data['repeat_pricing_actor_id'] == ctx.owner.telegram_id
    assert data['repeat_unit_cost'] == 0
    ctx.callback.data = f'repeat_q_{data["repeat_quote_id"]}'
    await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    ctx.launch.assert_awaited_once()
    ctx.debit.assert_not_awaited()
    assert ctx.launch.await_args.kwargs['unit_cost'] == 0


@pytest.mark.asyncio
async def test_refund_is_not_blocked_by_new_unsupported_author_fields(monkeypatch):
    ctx = await real_finance_context(monkeypatch)
    ctx.launch.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await generation.confirm_native_repeat_quote(ctx.callback, ctx.state)
    await configure_named_template(ctx, advanced=True)
    ctx.callback.data = f'repeat_image_{TASK_ID}'
    await generation.repeat_image_generation(ctx.callback, ctx.state)
    assert ctx.callback.answer.await_args.kwargs.get('show_alert') is True
    assert (await database.get_or_create_user(ctx.owner.telegram_id)).credits == ctx.start_credits
    assert (await store.load_draft(ctx.owner.id, 'tg:' + ctx.token))['refund_amount'] == 10
