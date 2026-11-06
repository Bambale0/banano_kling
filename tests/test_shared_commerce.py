"""Administrator-managed shared prices and individual partner agreements."""
from tests.test_shared_accounts import (
    ROOT,
    account_database,
    enable,
    login,
    preview_client,
)

__all__ = ['account_database']


async def test_commercial_catalog_is_empty_until_an_admin_configures_it():
    async with preview_client() as client:
        await enable(client)
        session = await (await login(client)).json()
        response = await client.get(ROOT + '/commerce', headers={'Authorization': 'Bearer ' + session['session_token']})
        assert response.status == 200
        assert (await response.json())['catalog'] == {
            'revision': 0, 'default_tariff_id': None, 'default_partner_group_id': None,
            'tariffs': {}, 'partner_groups': {},
        }


def catalog_settings():
    return {
        'default_tariff_id': 'ordinary', 'default_partner_group_id': 'base',
        'tariffs': {
            'ordinary': {'label': 'Обычный', 'prices': {'photo:test': {'amount': '2.5000', 'unit': 'job'}}},
            'creator': {'label': 'Креатор', 'prices': {'photo:test': {'amount': '1.2500', 'unit': 'job'}}},
        },
        'partner_groups': {
            'base': {'label': 'Базовые условия', 'first_level_percent': '30', 'second_level_percent': '7', 'repeat_reward_rub': '5'},
            'collaboration': {'label': 'Сотрудничество', 'first_level_percent': '40', 'second_level_percent': '7', 'repeat_reward_rub': '5'},
        },
    }


async def test_catalog_saved_in_vk_is_identical_in_telegram_and_revoked_sessions_cannot_write(monkeypatch):
    from tests.test_shared_accounts import vk_launch

    monkeypatch.setenv('VK_MINI_APP_SECRET', 'test-vk-app-secret')
    async with preview_client() as client:
        await enable(client, vk_app_id=123, vk_admin_ids=[2001])
        telegram = await (await login(client)).json()
        vk = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        tg_headers = {'Authorization': 'Bearer ' + telegram['session_token']}
        vk_headers = {'Authorization': 'Bearer ' + vk['session_token']}
        saved = await client.put(ROOT + '/commerce', headers=vk_headers, json={'expected_revision': 0, 'settings': catalog_settings()})
        assert saved.status == 200
        returned = (await saved.json())['catalog']
        assert returned['partner_groups']['collaboration']['first_level_percent'] == '40.0000'
        assert returned['tariffs']['creator']['prices']['photo:test']['amount'] == '1.2500'
        assert (await (await client.get(ROOT + '/commerce', headers=tg_headers)).json())['catalog'] == returned
        assert (await client.put(ROOT + '/commerce', json={'expected_revision': 1, 'settings': {}, 'is_admin': True})).status == 401
        await client.post(ROOT + '/logout', headers=vk_headers)
        assert (await client.put(ROOT + '/commerce', headers=vk_headers, json={'expected_revision': 1, 'settings': {}})).status == 401
        assert (await client.put(ROOT + '/commerce', headers=tg_headers, json={'expected_revision': 0, 'settings': {}})).status == 409


async def test_individual_terms_override_default_without_changing_old_quote():
    async with preview_client() as client:
        await enable(client)
        session = await (await login(client)).json()
        headers = {'Authorization': 'Bearer ' + session['session_token']}
        assert (await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 0, 'settings': catalog_settings()})).status == 200
        initial = await client.post(ROOT + '/commerce/quote', headers=headers, json={'price_key': 'photo:test', 'quantity': 1})
        assert initial.status == 200
        before = (await initial.json())['quote']
        assert before['total'] == '2.5000'
        assert before['terms']['first_level_percent'] == '30.0000'
        target = session['account']['id']
        changed = await client.put(ROOT + '/commerce/accounts/' + target, headers=headers, json={
            'expected_revision': 0, 'settings': {'tariff_id': 'creator', 'first_level_percent': '40'},
        })
        assert changed.status == 200
        quote = (await (await client.post(ROOT + '/commerce/quote', headers=headers, json={'price_key': 'photo:test', 'quantity': 1})).json())['quote']
        assert quote['total'] == '1.2500'
        assert quote['terms']['first_level_percent'] == '40.0000'
        original = await client.get(ROOT + '/commerce/quotes/' + before['id'], headers=headers)
        assert (await original.json())['quote'] == before


async def test_vk_quote_and_merge_preserve_individual_agreement_and_origin(monkeypatch):
    from tests.test_shared_account_links import commit_link, pair

    async with pair(monkeypatch) as (client, telegram, vk):
        settings = catalog_settings()
        assert (await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 0, 'settings': settings})).status == 200
        target = (await (await client.get(ROOT + '/me', headers=telegram)).json())['account']['id']
        assert (await client.put(ROOT + '/commerce/accounts/' + target, headers=telegram, json={
            'expected_revision': 0, 'settings': {'tariff_id': 'creator', 'first_level_percent': '40'},
        })).status == 200
        merged, _ = await commit_link(client, telegram, vk)
        assert merged.status == 200
        from tests.test_shared_accounts import vk_launch
        session = await (await client.post(ROOT + '/session', json={'platform': 'vk', 'launch_data': vk_launch(2001)})).json()
        headers = {'Authorization': 'Bearer ' + session['session_token']}
        quote = (await (await client.post(ROOT + '/commerce/quote', headers=headers, json={'price_key': 'photo:test', 'quantity': 1})).json())['quote']
        assert quote['terms']['first_level_percent'] == '40.0000'
        assert quote['total'] == '1.2500'
        assert quote['platform'] == 'vk' and quote['allowed_payment_providers'] == ['lava']
        forged = await client.post(ROOT + '/commerce/quote', headers=headers, json={
            'price_key': 'photo:test', 'quantity': 1, 'platform': 'telegram', 'provider': 'yookassa',
        })
        assert forged.status == 400


async def test_conflicting_individual_terms_abort_merge_without_moving_money(monkeypatch):
    from tests.test_shared_account_links import commit_link, pair

    async with pair(monkeypatch) as (client, telegram, vk):
        assert (await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 0, 'settings': catalog_settings()})).status == 200
        for headers, percent in [(telegram, '40'), (vk, '35')]:
            target = (await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id']
            assert (await client.put(ROOT + '/commerce/accounts/' + target, headers=telegram, json={
                'expected_revision': 0, 'settings': {'first_level_percent': percent},
            })).status == 200
        result, _ = await commit_link(client, telegram, vk)
        assert result.status == 409
        assert (await (await client.get(ROOT + '/wallet', headers=telegram)).json())['balance']['available'] == '2.0000'
        assert (await (await client.get(ROOT + '/wallet', headers=vk)).json())['balance']['available'] == '3.0000'


async def test_catalog_and_terms_cas_do_not_lose_concurrent_updates():
    import asyncio

    async with preview_client() as client:
        await enable(client)
        session = await (await login(client)).json()
        headers = {'Authorization': 'Bearer ' + session['session_token']}
        responses = await asyncio.gather(*[client.put(ROOT + '/commerce', headers=headers, json={
            'expected_revision': 0, 'settings': catalog_settings(),
        }) for _ in range(2)])
        assert sorted(response.status for response in responses) == [200, 409]
        path = ROOT + '/commerce/accounts/' + session['account']['id']
        responses = await asyncio.gather(*[client.put(path, headers=headers, json={
            'expected_revision': 0, 'settings': {'first_level_percent': rate},
        }) for rate in ['40', '45']])
        assert sorted(response.status for response in responses) == [200, 409]
        result = (await (await client.get(path, headers=headers)).json())['target']
        assert result['settings']['revision'] == 1
        assert result['effective']['first_level_percent'] in {'40.0000', '45.0000'}


async def test_referenced_tariff_cannot_be_deleted_and_quotes_are_private(monkeypatch):
    from tests.test_shared_account_links import pair

    async with pair(monkeypatch) as (client, telegram, vk):
        settings = catalog_settings()
        await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 0, 'settings': settings})
        target = (await (await client.get(ROOT + '/me', headers=telegram)).json())['account']['id']
        await client.put(ROOT + '/commerce/accounts/' + target, headers=telegram, json={'expected_revision': 0, 'settings': {'tariff_id': 'creator'}})
        quote = (await (await client.post(ROOT + '/commerce/quote', headers=telegram, json={'price_key': 'photo:test'})).json())['quote']
        settings['tariffs'].pop('creator')
        rejected = await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 1, 'settings': settings})
        assert rejected.status == 400
        assert (await client.get(ROOT + '/commerce/quotes/' + quote['id'], headers=vk)).status == 403
        assert (await (await client.get(ROOT + '/commerce', headers=telegram)).json())['catalog']['revision'] == 1


async def test_unknown_role_fields_and_imprecise_or_invalid_prices_are_rejected():
    import copy

    async with preview_client() as client:
        await enable(client)
        session = await (await login(client)).json()
        headers = {'Authorization': 'Bearer ' + session['session_token']}
        for amount in [2.5, True, '-1', 'NaN', '1e2', '1.00001', '9223372036854775808']:
            settings = copy.deepcopy(catalog_settings())
            settings['tariffs']['ordinary']['prices']['photo:test']['amount'] = amount
            assert (await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 0, 'settings': settings})).status == 400
        for rate in ['100.0001', '-1', 40.5, True]:
            settings = copy.deepcopy(catalog_settings())
            settings['partner_groups']['base']['first_level_percent'] = rate
            assert (await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 0, 'settings': settings})).status == 400
        assert (await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 0, 'settings': {'payment_providers': {'vk': ['yookassa']}}})).status == 400
        assert (await (await client.get(ROOT + '/commerce', headers=headers)).json())['catalog']['revision'] == 0


async def test_stale_default_terms_from_merged_alias_cannot_erase_individual_agreement(monkeypatch):
    from tests.test_shared_account_links import commit_link, pair

    async with pair(monkeypatch) as (client, telegram, vk):
        await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 0, 'settings': catalog_settings()})
        ids = [(await (await client.get(ROOT + '/me', headers=headers)).json())['account']['id'] for headers in (telegram, vk)]
        canonical, alias = sorted(ids)
        for account_id, settings in [(canonical, {'first_level_percent': '40'}), (alias, {})]:
            assert (await client.put(ROOT + '/commerce/accounts/' + account_id, headers=telegram, json={'expected_revision': 0, 'settings': settings})).status == 200
        merged, _ = await commit_link(client, telegram, vk)
        assert merged.status == 200
        session = await (await login(client)).json()
        fresh = {'Authorization': 'Bearer ' + session['session_token']}
        stale = await client.put(ROOT + '/commerce/accounts/' + alias, headers=fresh, json={
            'expected_revision': 1, 'settings': {'first_level_percent': None},
        })
        assert stale.status == 409
        target = (await (await client.get(ROOT + '/commerce/accounts/' + canonical, headers=fresh)).json())['target']
        assert target['effective']['first_level_percent'] == '40.0000'
        assert target['settings']['revision'] == 2


async def test_commercial_quote_history_is_append_only_and_failed_audit_rolls_back():
    import pytest

    from bot import db as db_backend

    async with preview_client() as client:
        await enable(client)
        session = await (await login(client)).json()
        headers = {'Authorization': 'Bearer ' + session['session_token']}
        await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 0, 'settings': catalog_settings()})
        quote = (await (await client.post(ROOT + '/commerce/quote', headers=headers, json={'price_key': 'photo:test'})).json())['quote']
        async with db_backend.connect() as db:
            with pytest.raises(Exception, match='append-only'):
                await db.execute('UPDATE shared_commercial_quotes SET snapshot = ? WHERE id = ?', ('{}', quote['id']))
            await db.rollback()
            execute = getattr(db, 'execute_native_ddl', db.execute)
            if db_backend.is_postgres():
                await execute("CREATE FUNCTION reject_commercial_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test audit unavailable'; END; $$")
                await execute('CREATE TRIGGER reject_commercial_audit BEFORE INSERT ON shared_commercial_audit FOR EACH ROW EXECUTE FUNCTION reject_commercial_audit()')
            else:
                await execute("CREATE TRIGGER reject_commercial_audit BEFORE INSERT ON shared_commercial_audit BEGIN SELECT RAISE(ABORT, 'test audit unavailable'); END")
            await db.commit()
        rejected = await client.put(ROOT + '/commerce', headers=headers, json={'expected_revision': 1, 'settings': {'default_tariff_id': 'creator'}})
        assert rejected.status == 503
        unchanged = (await (await client.get(ROOT + '/commerce', headers=headers)).json())['catalog']
        assert unchanged['revision'] == 1 and unchanged['default_tariff_id'] == 'ordinary'
        assert (await (await client.get(ROOT + '/commerce/quotes/' + quote['id'], headers=headers)).json())['quote'] == quote


async def test_lookup_and_effective_zero_do_not_confuse_identity_or_inheritance(monkeypatch):
    from tests.test_shared_account_links import pair

    async with pair(monkeypatch) as (client, telegram, vk):
        await client.put(ROOT + '/commerce', headers=telegram, json={'expected_revision': 0, 'settings': catalog_settings()})
        target = (await (await client.get(ROOT + '/me', headers=vk)).json())['account']['id']
        await client.put(ROOT + '/commerce/accounts/' + target, headers=telegram, json={
            'expected_revision': 0, 'settings': {'first_level_percent': '0', 'repeat_reward_rub': '0'},
        })
        looked_up = await client.get(ROOT + '/commerce/accounts?platform=vk&external_id=2001', headers=telegram)
        result = (await looked_up.json())['target']
        assert result['account_id'] == target
        assert result['effective']['first_level_percent'] == '0.0000'
        assert result['effective']['repeat_reward_rub'] == '0.00'
        assert (await client.get(ROOT + '/commerce/accounts?platform=vk&external_id=0', headers=telegram)).status == 400
        assert (await client.get(ROOT + '/commerce/accounts?platform=telegram&external_id=2001', headers=telegram)).status == 400
        assert (await client.get(ROOT + '/commerce')).status == 401
