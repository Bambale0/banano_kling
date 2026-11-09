"""One-tap TG/VK linking: each authenticated platform must explicitly opt in."""
from tests.test_shared_account_links import ROOT, pair
from tests.test_shared_accounts import login, vk_launch


async def test_one_tap_link_only_commits_after_verified_recipient_click(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        created = await client.post(
            ROOT + '/links', headers=source,
            json={'target_platform': 'vk', 'confirm_source': True},
        )
        assert created.status == 200
        invitation = (await created.json())['link']
        assert invitation['source_confirmed'] is True
        assert invitation['target_confirmed'] is False
        assert invitation['state'] == 'pending'
        # Merely opening an invitation is not permission to bind accounts.
        before = await client.get(ROOT + '/links/' + invitation['id'], headers=source)
        assert (await before.json())['link']['state'] == 'pending'
        wrong_token = await client.post(
            ROOT + '/links/accept', headers=target,
            json={'token': 'x' * 43, 'confirm': True},
        )
        assert wrong_token.status == 401
        still_pending = await client.get(ROOT + '/links/' + invitation['id'], headers=source)
        assert (await still_pending.json())['link']['state'] == 'pending'

        confirmed = await client.post(
            ROOT + '/links/accept', headers=target,
            json={'token': invitation['token'], 'confirm': True},
        )
        assert confirmed.status == 200
        link = (await confirmed.json())['link']
        assert link['state'] == 'committed'
        assert link['source_confirmed'] is True and link['target_confirmed'] is True
        # Merging may retire the target's old account/session. A fresh signed
        # login must work, and replay must not transfer funds a second time.
        fresh_vk = (await (await client.post(
            ROOT + '/session',
            json={'platform': 'vk', 'launch_data': vk_launch(2001)},
        )).json())
        replay = await client.post(
            ROOT + '/links/accept',
            headers={'Authorization': 'Bearer ' + fresh_vk['session_token']},
            json={'token': invitation['token'], 'confirm': True},
        )
        assert replay.status == 200
        telegram_session = (await (await login(client)).json())['account']
        vk_session = (await (await client.post(
            ROOT + '/session',
            json={'platform': 'vk', 'launch_data': vk_launch(2001)},
        )).json())['account']
        assert telegram_session['id'] == vk_session['id'] == link['account_id']
        # The source account remains canonical, so its existing session
        # may remain valid. It must still resolve to the consolidated wallet;
        # a newly authenticated session must see the same funds.
        existing_wallet = await client.get(ROOT + '/wallet', headers=source)
        assert existing_wallet.status == 200
        assert (await existing_wallet.json())['balance']['available'] == '5.0000'
        fresh_telegram = await login(client)
        assert fresh_telegram.status == 200
        fresh_source_token = (await fresh_telegram.json())['session_token']
        check_wallet = await client.get(
            ROOT + '/wallet', headers={'Authorization': 'Bearer ' + fresh_source_token},
        )
        assert check_wallet.status == 200
        assert (await check_wallet.json())['balance']['available'] == '5.0000'


async def test_one_tap_link_rejects_invalid_confirmation_and_still_supports_manual_pair(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        for value in ['yes', 1, None]:
            response = await client.post(
                ROOT + '/links', headers=source,
                json={'target_platform': 'vk', 'confirm_source': value},
            )
            assert response.status == 400

        created = await client.post(
            ROOT + '/links', headers=source,
            json={'target_platform': 'vk'},
        )
        link = (await created.json())['link']
        assert link.get('source_confirmed') is False
        bad_confirm = await client.post(
            ROOT + '/links/accept', headers=target,
            json={'token': link['token'], 'confirm': 'yes'},
        )
        assert bad_confirm.status == 400

        accepted = await client.post(
            ROOT + '/links/accept', headers=target,
            json={'token': link['token'], 'confirm': True},
        )
        assert accepted.status == 200
        state = (await accepted.json())['link']
        assert state['state'] == 'awaiting_confirmation'
        assert state['source_confirmed'] is False and state['target_confirmed'] is True
        # Non-initiated source did not opt in, so target alone cannot merge.
        old_session = (await (await login(client)).json())['account']['id']
        assert old_session != (await (await client.post(
            ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)},
        )).json())['account']['id']

async def test_invitation_preview_does_not_accept_and_shows_verified_source(monkeypatch):
    async with pair(monkeypatch) as (client, source, target):
        created = (await (await client.post(
            ROOT + '/links', headers=source,
            json={'target_platform': 'vk', 'confirm_source': True},
        )).json())['link']
        response = await client.post(
            ROOT + '/links/preview', headers=target, json={'token': created['token']},
        )
        assert response.status == 200
        preview = (await response.json())['link']
        assert preview['source_identity']['platform'] == 'telegram'
        assert preview['source_confirmed'] is True
        assert preview['target_confirmed'] is False
        assert preview['target_identity'] is None
        state = (await (await client.get(
            ROOT + '/links/' + created['id'], headers=source,
        )).json())['link']
        assert state['state'] == 'pending'
        assert state['revision'] == 0
        assert (await client.post(
            ROOT + '/links/preview', json={'token': created['token']},
        )).status == 401
        assert (await client.post(
            ROOT + '/links/preview', headers=target,
            json={'token': 'x' * 43},
        )).status == 401
