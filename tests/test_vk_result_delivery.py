"""A ready result has one verified VK chat delivery, never a second generation."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot import db as db_backend
from bot.services.vk_result_delivery import VKDeliveryQueue
from tests.test_shared_account_links import commit_link
from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
    vk_launch,
)

__all__ = ['account_database']


@asynccontextmanager
async def actor(monkeypatch):
    from bot.config import config

    monkeypatch.setattr(config, 'VK_GROUP_TOKEN', 'synthetic-group-secret')
    monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '456')
    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    user = await database.get_or_create_user(999999999)
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001, 2002], vk_community_id=456, vk_result_delivery_enabled=True)
        tg = await (await login(client)).json()
        vk = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        await commit_link(client, {'Authorization': 'Bearer ' + tg['session_token']}, {'Authorization': 'Bearer ' + vk['session_token']})
        session = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        yield client, {'Authorization': 'Bearer ' + session['session_token']}, user, session['account']['id']


async def ready(
    user,
    account_id,
    task_id='vk-delivery-ready',
    *,
    task_type='image',
    result_url=None,
    **metadata,
):
    model = 'seedance_2_5' if task_type == 'video' else 'banana_pro'
    result_url = result_url or (
        'https://example.test/result.mp4'
        if task_type == 'video'
        else 'https://example.test/result.png'
    )
    await database.add_generation_task(
        user.id,
        user.telegram_id,
        task_id,
        task_type,
        model,
        model=model,
        prompt='Synthetic VK result',
        request_data={
            'origin_platform': 'vk',
            'origin_vk_user_id': 2001,
            'origin_account_id': account_id,
            'vk_chat_delivery_requested': True,
            **metadata,
        },
    )
    await database.store_task_result_ready(task_id, result_url)
    return await database.get_task_by_id(task_id)


def transport():
    return SimpleNamespace(permission=AsyncMock(return_value=True), prepare=AsyncMock(return_value='photo-456_123'),
                           send=AsyncMock(return_value=789))


async def rows():
    async with db_backend.connect() as db:
        return await (await db.execute('SELECT state, attempts, random_id, receipt_id FROM vk_result_deliveries')).fetchall()


async def test_callback_race_has_one_durable_job_and_one_vk_receipt(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()
        queues = [VKDeliveryQueue(sender) for _ in range(2)]
        assert all(await asyncio.gather(*(queue.enqueue(task.task_id) for queue in queues)))
        await asyncio.gather(*(queue.tick() for queue in queues))
        stored = await rows()
        assert len(stored) == 1 and stored[0][0] == 'delivered' and stored[0][3] == 789
        assert sender.send.await_count == 1
        sent = sender.send.await_args.args[0]
        assert sent['vk_user_id'] == 2001 and sent['community_id'] == 456
        assert sent['random_id'] == stored[0][2] and sent['attachment'] == 'photo-456_123'
        assert -(2**31) < sent['random_id'] < 0  # Separate from native positive timestamps.
        assert (await database.get_task_by_id(task.task_id)).result_url == 'https://example.test/result.png'
        assert (await database.get_or_create_user(user.telegram_id)).credits == user.credits


async def test_completed_vk_video_is_delivered_as_one_saved_link(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(
            user,
            account,
            task_id='vk-video-delivery',
            task_type='video',
        )
        sender = transport()
        sender.prepare.return_value = None
        queue = VKDeliveryQueue(sender)

        assert await queue.enqueue(task.task_id)
        await queue.tick()

        assert (await rows())[0][0] == 'delivered'
        sender.prepare.assert_awaited_once()
        sender.send.assert_awaited_once()
        sent = sender.send.await_args.args[0]
        assert sent['result_url'].endswith('.mp4')
        assert sent['result_type'] == 'video'
        assert sent['attachment'] is None


async def test_old_or_forged_recipient_is_not_guessed_or_queued(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        queue = VKDeliveryQueue(transport())
        for index, metadata in enumerate(({'origin_vk_user_id': None}, {'origin_vk_user_id': 2002},
                                          {'origin_account_id': 'f' * 32}, {'origin_platform': 'telegram'},
                                          {'vk_chat_delivery_requested': False})):
            task = await ready(user, account, task_id=f'invalid-recipient-{index}', **metadata)
            assert not await queue.enqueue(task.task_id)
        assert await rows() == []


async def test_missing_permission_does_not_send_or_block_user_or_refund(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()
        sender.permission.return_value = False
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        await queue.tick()
        assert (await rows())[0][0] == 'permission_required'
        sender.prepare.assert_not_awaited()
        sender.send.assert_not_awaited()
        assert (await database.get_or_create_user(user.telegram_id)).credits == user.credits


async def test_lost_send_ack_is_uncertain_and_never_automatically_replayed(monkeypatch):
    from bot.services.vk_result_transport import VKSendUncertain

    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()
        sender.send.side_effect = VKSendUncertain()
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        await queue.tick()
        await queue.tick()
        await queue.enqueue(task.task_id)
        await queue.tick()
        assert (await rows())[0][0] == 'uncertain'
        assert sender.send.await_count == 1


async def test_completed_result_reconciliation_repairs_a_crash_before_enqueue(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        await ready(user, account)
        sender = transport()
        queue = VKDeliveryQueue(sender)
        await queue.reconcile()
        await queue.tick()
        assert (await rows())[0][0] == 'delivered'
        assert sender.send.await_count == 1


async def test_send_phase_crash_cannot_start_another_automatic_send(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        async with db_backend.connect() as db:
            await db.execute("UPDATE vk_result_deliveries SET state = 'sending', lease_until_epoch = 0")
            await db.commit()
        await queue.tick()
        assert (await rows())[0][0] == 'uncertain'
        sender.send.assert_not_awaited()


async def test_caption_snapshot_survives_admin_template_changes(monkeypatch):
    from bot.shared_accounts.policy import save_policy

    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        from bot.shared_accounts.policy import load_policy
        policy = await load_policy()
        await save_policy(user.telegram_id, {'vk_result_message_template': 'New copy {result_url}'}, policy.revision)
        await queue.tick()
        assert not sender.send.await_args.args[0]['message'].startswith('New copy')


async def test_reconciliation_progresses_past_a_full_page_of_ineligible_old_rows(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        for index in range(50):
            await ready(user, account, task_id=f'old-invalid-{index}', origin_account_id='f' * 32)
        await ready(user, account, task_id='later-valid')
        queue = VKDeliveryQueue(transport())
        await queue.reconcile()
        await queue.reconcile()
        await queue.tick()
        assert len(await rows()) == 1
        assert (await rows())[0][0] == 'delivered'


async def test_link_only_template_requires_a_real_result_field_not_escaped_text():
    from bot.shared_accounts.policy import PreviewPolicy

    with pytest.raises(ValueError):
        PreviewPolicy.parse({'vk_result_message_template': '{task_id} {{result_url}}'})


async def test_old_result_requires_explicit_fresh_owner_acceptance_and_rejects_recipient_json(monkeypatch):
    async with actor(monkeypatch) as (client, headers, user, account):
        task = await ready(user, account, origin_vk_user_id=None, origin_account_id=None)
        path = ROOT + '/vk-deliveries/' + task.task_id
        status = await client.get(path, headers=headers)
        assert status.status == 200
        assert (await status.json())['delivery']['state'] == 'not_requested'
        assert (await client.post(path, headers=headers, json={'vk_user_id': 2002})).status == 400
        accepted = await client.post(path, headers=headers, json={})
        assert accepted.status == 200, await accepted.text()
        assert (await accepted.json())['delivery']['state'] == 'pending'
        stored = json.loads((await database.get_task_by_id(task.task_id)).request_data)
        assert stored['origin_vk_user_id'] == 2001 and stored['origin_account_id'] == account
        assert stored['vk_delivery_explicit_requested_at_epoch'] > 0
        assert len(await rows()) == 1


async def test_delivery_status_and_retry_deny_other_vk_identity_or_query_token(monkeypatch):
    async with actor(monkeypatch) as (client, headers, user, account):
        task = await ready(user, account)
        path = ROOT + '/vk-deliveries/' + task.task_id
        other = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2002)})).json()
        other_headers = {'Authorization': 'Bearer ' + other['session_token']}
        assert (await client.get(path, headers=other_headers)).status == 404
        assert (await client.post(path, headers=other_headers, json={})).status == 404
        assert (await client.get(path + '?session_token=' + headers['Authorization'][7:])).status == 401


async def test_uncertain_receipt_is_visible_but_owner_cannot_trigger_another_send(monkeypatch):
    from bot.services.vk_result_transport import VKSendUncertain

    async with actor(monkeypatch) as (client, headers, user, account):
        task = await ready(user, account)
        sender = transport()
        sender.send.side_effect = VKSendUncertain()
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        await queue.tick()
        path = ROOT + '/vk-deliveries/' + task.task_id
        status = (await (await client.get(path, headers=headers)).json())['delivery']
        assert status['state'] == 'uncertain' and status['can_request'] is False
        assert (await client.post(path, headers=headers, json={})).status == 409
        await queue.tick()
        assert sender.send.await_count == 1


async def test_disabling_new_delivery_does_not_erase_a_confirmed_chat_receipt(monkeypatch):
    from bot.shared_accounts.policy import load_policy, save_policy

    async with actor(monkeypatch) as (client, _headers, user, account):
        task = await ready(user, account)
        queue = VKDeliveryQueue(transport())
        await queue.enqueue(task.task_id)
        await queue.tick()
        policy = await load_policy()
        await save_policy(user.telegram_id, {'vk_result_delivery_enabled': False}, policy.revision)
        session = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        status = (await (await client.get(ROOT + '/vk-deliveries/' + task.task_id,
                                        headers={'Authorization': 'Bearer ' + session['session_token']})).json())['delivery']
        assert status['state'] == 'delivered' and status['can_request'] is False


async def test_explicit_flood_rejection_retries_only_the_same_saved_payload(monkeypatch):
    from bot.services.vk_result_transport import VKRejected

    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        now = [1_000_000_000]
        sender = transport()
        sender.send.side_effect = [VKRejected(6), 789]
        queue = VKDeliveryQueue(sender, clock=lambda: now[0])
        await queue.enqueue(task.task_id)
        await queue.tick()
        assert (await rows())[0][0] == 'pending'
        first = dict(sender.send.await_args.args[0])
        await queue.tick()
        assert sender.send.await_count == 1
        now[0] += 30
        await queue.tick()
        assert (await rows())[0][0] == 'delivered'
        second = sender.send.await_args.args[0]
        assert {key: second[key] for key in ('random_id', 'message', 'attachment')} == {
            key: first[key] for key in ('random_id', 'message', 'attachment')}
        assert sender.prepare.await_count == 1


async def test_expired_preparing_worker_cannot_send_after_another_lease_wins(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        now = [1_000_000_000]
        entered, released = asyncio.Event(), asyncio.Event()
        sender = transport()
        calls = 0

        async def prepare(_job):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await released.wait()
            return 'photo-456_9'

        sender.prepare.side_effect = prepare
        first, second = (VKDeliveryQueue(sender, clock=lambda: now[0]) for _ in range(2))
        await first.enqueue(task.task_id)
        running = asyncio.create_task(first.tick())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            now[0] += 301
            await second.tick()
            released.set()
            await running
        finally:
            released.set()
            await asyncio.gather(running, return_exceptions=True)
        assert (await rows())[0][0] == 'delivered'
        assert sender.send.await_count == 1


async def test_ready_callback_replay_enqueues_once_without_a_new_charge(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        assert all(await asyncio.gather(*(database.complete_task_in_app(task.task_id, task.result_url) for _ in range(2))))
        sender = transport()
        await VKDeliveryQueue(sender).tick()
        assert len(await rows()) == 1 and sender.send.await_count == 1
        assert (await database.get_or_create_user(user.telegram_id)).credits == user.credits


async def test_account_revocation_during_preparation_prevents_the_chat_send(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        sender = transport()

        async def prepare(_job):
            async with db_backend.connect() as db:
                await db.execute("UPDATE shared_accounts SET status = 'blocked' WHERE id = ?", (account,))
                await db.commit()
            return 'photo-456_9'

        sender.prepare.side_effect = prepare
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        await queue.tick()
        assert (await rows())[0][0] == 'access_revoked'
        sender.send.assert_not_awaited()


async def test_random_id_collision_does_not_drop_a_second_owned_result(monkeypatch):
    import bot.services.vk_result_delivery as delivery

    async with actor(monkeypatch) as (_client, _headers, user, account):
        first = await ready(user, account, task_id='first-result')
        second = await ready(user, account, task_id='second-result')
        nonce = iter([0, 0, 1])
        monkeypatch.setattr(delivery.secrets, 'randbelow', lambda _limit: next(nonce))
        queue = VKDeliveryQueue(transport())
        assert await queue.enqueue(first.task_id)
        assert await queue.enqueue(second.task_id)
        assert len({row[2] for row in await rows()}) == 2


async def test_late_positive_receipt_upgrades_uncertainty_without_another_send(monkeypatch):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        now = [1_000_000_000]
        entered, released = asyncio.Event(), asyncio.Event()
        sender = transport()

        async def send(_job):
            entered.set()
            await released.wait()
            return 789

        sender.send.side_effect = send
        first, second = (VKDeliveryQueue(sender, clock=lambda: now[0]) for _ in range(2))
        await first.enqueue(task.task_id)
        running = asyncio.create_task(first.tick())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            now[0] += 301
            await second.tick()
            assert (await rows())[0][0] == 'uncertain'
            released.set()
            await running
        finally:
            released.set()
            await asyncio.gather(running, return_exceptions=True)
        stored = (await rows())[0]
        assert stored[0] == 'delivered' and stored[3] == 789
        assert sender.send.await_count == 1


async def test_delivery_cannot_be_enabled_with_an_unbound_sender_secret(monkeypatch):
    from bot.config import config
    from bot.shared_accounts.policy import load_policy, save_policy
    from tests.test_shared_accounts import telegram_launch

    async with actor(monkeypatch) as (client, _headers, user, _account):
        policy = await load_policy()
        disabled = await save_policy(user.telegram_id, {'vk_result_delivery_enabled': False}, policy.revision)
        monkeypatch.setattr(config, 'VK_GROUP_TOKEN_COMMUNITY_ID', '999')
        result = await client.put(ROOT + '/settings', json={'init_data': telegram_launch(),
                                  'expected_revision': disabled.revision, 'settings': {'vk_result_delivery_enabled': True}})
        assert result.status == 400
        assert (await result.json())['error_code'] == 'vk_sender_unconfigured'
        assert (await load_policy()).vk_result_delivery_enabled is False


async def test_owner_retry_after_permission_grant_sends_only_once(monkeypatch):
    async with actor(monkeypatch) as (client, headers, user, account):
        task = await ready(user, account)
        sender = transport()
        sender.permission.return_value = False
        queue = VKDeliveryQueue(sender)
        await queue.enqueue(task.task_id)
        await queue.tick()
        assert (await rows())[0][0] == 'permission_required'
        path = ROOT + '/vk-deliveries/' + task.task_id
        result = await client.post(path, headers=headers, json={})
        assert result.status == 200 and (await result.json())['delivery']['state'] == 'pending'
        sender.permission.return_value = True
        await queue.tick()
        assert (await rows())[0][0] == 'delivered'
        assert (await (await client.post(path, headers=headers, json={})).json())['delivery']['state'] == 'delivered'
        await queue.tick()
        assert sender.send.await_count == 1


async def test_delivery_settings_keep_the_previous_release_auth_policy_readable(monkeypatch):
    from bot.shared_accounts.policy import POLICY_KEY, load_policy, save_policy

    async with actor(monkeypatch) as (_client, _headers, user, _account):
        old_fields = {'enabled', 'revision', 'vk_app_id', 'vk_admin_ids', 'session_ttl_seconds',
                      'launch_max_age_seconds', 'link_ttl_seconds'}
        async with db_backend.connect() as db:
            raw = (await (await db.execute('SELECT value FROM bot_settings WHERE key = ?', (POLICY_KEY,))).fetchone())[0]
        assert set(json.loads(raw)) <= old_fields, 'The previous release rejects unknown authentication policy keys'
        policy = await load_policy()
        updated = await save_policy(user.telegram_id, {'launch_max_age_seconds': 700}, policy.revision)
        assert updated.vk_community_id == 456 and updated.vk_result_delivery_enabled is True


@pytest.mark.parametrize('scope', ['feed', 'profile'])
async def test_publication_does_not_expose_private_delivery_identity_metadata(monkeypatch, scope):
    async with actor(monkeypatch) as (_client, _headers, user, account):
        task = await ready(user, account)
        published = await database.share_to_feed(task.task_id, user.id, prompt_visible=True, publication_scope=scope)
        assert published is not None
        reader = database.get_feed_generation_card if scope == 'feed' else database.get_profile_generation_card
        public = await reader(published['id'], viewer_user_id=None)
        assert public is not None
        for card in (published, public):
            encoded = json.dumps(card)
            for field in ('origin_vk_user_id', 'origin_account_id', 'vk_chat_delivery_requested', 'request_data'):
                assert field not in encoded
            assert account not in encoded
