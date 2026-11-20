"""Finance boundary: never enable standalone paid checkout before generation parity.

These public request seam tests use only synthetic identities. Production money,
credentials, provider API and DB are never touched.
"""
from __future__ import annotations

import json
import os
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import make_mocked_request

from bot import web_commerce


class WebsitePaymentSafety(TestCase):
    def test_enabling_flags_without_generation_handler_still_fails_closed(self):
        with patch.dict(os.environ, {
            "WEB_NATIVE_PAYMENTS_ENABLED": "1",
            "WEB_NATIVE_GENERATION_ENABLED": "1",
        }):
            self.assertFalse(web_commerce._enabled())

    def test_lava_amount_must_match_exact_minor_units_and_currency(self):
        order = (
            'web_' + 'a' * 32, 'account-id', 'mini', 10000, '110',
            'pending', 'invoice-a', 'contract-a', None,
        )
        self.assertTrue(web_commerce._external_invoice({
            'amount': '100.00', 'currency': 'RUB',
        }, order))
        for wrong in [
            {'amount': '100.01', 'currency': 'RUB'},
            {'amount': '100.00', 'currency': 'USD'},
            {'amount': 'NaN', 'currency': 'RUB'},
            {'amount': '100.001', 'currency': 'RUB'},
            {'currency': 'RUB'},
            {'amount': '100.00'},
        ]:
            with self.subTest(wrong=wrong):
                self.assertFalse(web_commerce._external_invoice(wrong, order))


class WebsitePaymentActor(IsolatedAsyncioTestCase):
    async def test_verified_linked_telegram_account_cannot_open_second_wallet(self):
        request = make_mocked_request('POST', '/mini-app/api/web-auth/web-payments/create')
        with (
            patch('bot.web_auth._valid_browser_origin', return_value=True),
            patch('bot.web_auth._session_account', new=AsyncMock(return_value='a'*32)),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['telegram'])),
            patch.object(web_commerce, 'ensure_web_payment_schema',
                         new=AsyncMock(side_effect=AssertionError('must not touch money'))),
            patch.object(web_commerce.lava_service, 'create_invoice',
                         new=AsyncMock(side_effect=AssertionError('provider must not be called'))),
        ):
            response = await web_commerce.create_payment(request)
        self.assertEqual(response.status, 409)
        self.assertEqual(json.loads(response.body)['code'], 'FINANCIAL_CUTOVER_REQUIRED')

    async def test_anonymous_account_never_reaches_payment_provider(self):
        request = make_mocked_request('POST', '/mini-app/api/web-auth/web-payments/create')
        with (
            patch('bot.web_auth._valid_browser_origin', return_value=True),
            patch('bot.web_auth._session_account', new=AsyncMock(return_value=None)),
            patch.object(web_commerce.lava_service, 'create_invoice',
                         new=AsyncMock(side_effect=AssertionError('provider must not be called'))),
        ):
            response = await web_commerce.create_payment(request)
        self.assertEqual(response.status, 401)
        self.assertEqual(json.loads(response.body)['error'], 'session_required')

    async def test_browser_with_vk_legacy_identity_cannot_open_second_wallet(self):
        request = make_mocked_request('POST', '/mini-app/api/web-auth/web-payments/create')
        with (
            patch('bot.web_auth._valid_browser_origin', return_value=True),
            patch('bot.web_auth._session_account', new=AsyncMock(return_value='b'*32)),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['vk'])),
        ):
            response = await web_commerce.create_payment(request)
        self.assertEqual(response.status, 409)

    async def test_linked_users_cannot_see_standalone_checkout_as_available(self):
        request = make_mocked_request('GET', '/mini-app/api/web-auth/web-payments/packages')
        with (
            patch('bot.web_auth._session_account', new=AsyncMock(return_value='a'*32)),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['telegram'])),
            patch.object(web_commerce.preset_manager, 'get_packages',
                         return_value=[{'id':'mini'}]),
            patch.object(web_commerce, '_package',
                         return_value=(10000, '110', 'offer-test', 'Mini')),
        ):
            response = await web_commerce.list_packages(request)
        self.assertEqual(response.status, 200)
        self.assertFalse(json.loads(response.body)['available'])
