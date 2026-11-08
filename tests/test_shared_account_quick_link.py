"""One-tap TG/VK linking: each authenticated platform must explicitly opt in."""
from bot.shared_accounts.store import linked_telegram_id
from tests.test_shared_account_links import pair, ROOT
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
        assert (await client.post(
            ROOT + '/links/accept', headers=target,
            json={'token': invitation['token'], 'confirm': True},
        )).status == 200
        telegram_session = (await (await login(client)).json())['account']
        vk_session = (await (await client.post(
            ROOT + '/session',
            json={'platform': 'vk', 'launch_data': vk_launch(2001)},
        )).json())['account']
        assert telegram_session['id'] == vk_session['id'] == link['account_id']
        check_wallet = await client.get(ROOT + '/wallet', headers=source)
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
