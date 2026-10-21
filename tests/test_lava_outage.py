"""Payment outage behavior through real invoice HTTP and transaction seams."""
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import database
from bot.services import lava_payment_safety as safety
from bot.services.lava_service import lava_service


@pytest.fixture(autouse=True)
def reset_database_schema_cache(monkeypatch):
    from bot.services import lava_binding_schema_compat
    from bot.handlers import miniapp_regression_safety
    monkeypatch.setattr(lava_binding_schema_compat, '_BINDINGS_SCHEMA_READY', False)
    monkeypatch.setattr(miniapp_regression_safety, '_PAYMENT_EMAIL_SCHEMA_READY', False)


@pytest.mark.asyncio
async def test_invoice_outage_stops_batch_without_discovery_or_balance_mutation(monkeypatch):
    # Import the same compatibility stack used by production.
    import bot.handlers  # noqa: F401

    paths = []

    async def unavailable(request):
        paths.append(request.path)
        return web.json_response({'error': 'Something went wrong'}, status=500)

    app = web.Application()
    app.router.add_get('/{path:.*}', unavailable)
    async with TestServer(app) as server:
        await lava_service.close()
        monkeypatch.setattr(lava_service, 'api_key', 'synthetic-test-key')
        monkeypatch.setattr(lava_service, 'base_url', str(server.make_url('')).rstrip('/'))
        user = await database.get_or_create_user(1234567)
        for index in range(2):
            await database.create_transaction(
                order_id=f'outage-{index}', user_id=user.id, payment_id=f'invoice-{index}',
                provider='lava', credits=50, amount_rub=500,
            )

        async def must_not_complete(*args, **kwargs):
            pytest.fail('Unconfirmed invoice must never credit a balance')

        try:
            result = await safety.safe_reconcile_lava_pending_transactions(
                payments_module=SimpleNamespace(_complete_transaction=must_not_complete), limit=40,
            )
        finally:
            await lava_service.close()

    assert len(result) == 1
    assert result[0]['action'] == 'error'
    assert result[0]['error'] == 'provider_unavailable'
    assert len(set(paths)) == 1
    assert paths[0] in {'/api/v2/invoices/invoice-0', '/api/v2/invoices/invoice-1'}
    assert len(paths) <= 3
    for index in range(2):
        assert (await database.get_transaction_by_order(f'outage-{index}')).status == 'pending'


@pytest.mark.asyncio
async def test_missing_invoice_is_lookup_error_and_never_a_confirmed_pending_state(monkeypatch):
    async def missing(request):
        return web.json_response({'error': 'not found'}, status=404)

    provider_app = web.Application()
    provider_app.router.add_get('/{path:.*}', missing)
    user = await database.get_or_create_user(1234570)
    await database.create_transaction(order_id='missing-order', user_id=user.id,
        payment_id='missing-invoice', provider='lava', credits=50, amount_rub=500)
    async with TestServer(provider_app) as provider:
        await lava_service.close()
        monkeypatch.setattr(lava_service, 'api_key', 'test-key')
        monkeypatch.setattr(lava_service, 'base_url', str(provider.make_url('')).rstrip('/'))
        try:
            result = await safety.safe_reconcile_lava_pending_transactions(payments_module=SimpleNamespace(), limit=40)
            assert result[0]['action'] == 'error'
            assert result[0]['error'] == 'invoice_lookup_failed'
            assert (await database.get_transaction_by_order('missing-order')).status == 'pending'
        finally:
            await lava_service.close()



@pytest.mark.asyncio
async def test_webhook_retries_outage_then_credits_once_after_provider_recovery(monkeypatch):
    import bot.handlers  # noqa: F401
    from bot.handlers import payments

    provider_state = {'status': 500}
    paths = []

    async def invoice(request):
        paths.append(request.path)
        if provider_state['status'] != 200:
            return web.json_response({'error': 'Something went wrong'}, status=500)
        return web.json_response({'id': 'invoice-paid', 'status': 'COMPLETED'})

    provider_app = web.Application()
    provider_app.router.add_get('/api/v2/invoices/{invoice}', invoice)
    user = await database.get_or_create_user(1234568)
    before = float(user.credits)
    await database.create_transaction(order_id='verified-order', user_id=user.id,
        payment_id='invoice-paid', provider='lava', credits=50, amount_rub=500)
    monkeypatch.setenv('LAVA_WEBHOOK_ALLOWED_IPS', '192.0.2.10')
    app = web.Application()
    app.router.add_post('/lava/webhook', payments.handle_lava_webhook)
    payload = {'eventType': 'payment.success', 'contractId': 'invoice-paid',
        'amount': 500, 'currency': 'RUB', 'status': 'completed'}
    async with TestServer(provider_app) as provider, TestClient(TestServer(app)) as client:
        await lava_service.close()
        monkeypatch.setattr(lava_service, 'api_key', 'test-key')
        monkeypatch.setattr(lava_service, 'base_url', str(provider.make_url('')).rstrip('/'))
        try:
            response = await client.post('/lava/webhook', json=payload, headers={'X-Real-IP': '192.0.2.10'})
            assert response.status == 503
            assert (await database.get_transaction_by_order('verified-order')).status == 'pending'
            assert float((await database.get_or_create_user(1234568)).credits) == before
            provider_state['status'] = 200
            for _ in range(2):
                response = await client.post('/lava/webhook', json=payload, headers={'X-Real-IP': '192.0.2.10'})
                assert response.status == 200
            assert (await database.get_transaction_by_order('verified-order')).status == 'completed'
            assert float((await database.get_or_create_user(1234568)).credits) == before + 50
            # A forged sender cannot reach the provider or credit again.
            count = len(paths)
            response = await client.post('/lava/webhook', json=payload, headers={'X-Real-IP': '192.0.2.99'})
            assert response.status == 403
            assert len(paths) == count
        finally:
            await lava_service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['lava_card', 'lava_sbp'])
async def test_signed_checkout_outage_has_safe_503_without_post_replay(monkeypatch, method):
    import bot.handlers  # noqa: F401
    from bot import miniapp
    from tests.test_miniapp_task_history import signed

    posts = []

    async def create(request):
        posts.append(await request.json())
        return web.json_response({'error': 'upstream-internal-detail'}, status=500)

    provider_app = web.Application()
    provider_app.router.add_post('/api/v3/invoice', create)
    monkeypatch.setattr(miniapp.preset_manager, 'get_package', lambda _: {
        'id': 'test', 'name': 'Test', 'credits': 50, 'price_rub': 500,
        'lava_offer_id': 'test-offer', 'lava_currency': 'RUB',
    })
    app = web.Application()
    app.router.add_post('/mini-app/api/create-payment', miniapp.miniapp_create_payment)
    async with TestServer(provider_app) as provider, TestClient(TestServer(app)) as client:
        await lava_service.close()
        monkeypatch.setattr(lava_service, 'api_key', 'test-key')
        monkeypatch.setattr(lava_service, 'base_url', str(provider.make_url('')).rstrip('/'))
        try:
            response = await client.post('/mini-app/api/create-payment', json={
                'init_data': signed(1234569), 'package_id': 'test', 'provider': method,
                'customer_email': 'synthetic@gmail.com',
            })
            body = await response.json()
            assert response.status == 503, body
            assert body['code'] == 'payment_provider_unavailable'
            assert 'upstream-internal-detail' not in str(body)
            assert len(posts) == 1
        finally:
            await lava_service.close()

