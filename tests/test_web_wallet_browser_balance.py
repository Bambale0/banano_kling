"""Web balance API may read only the verified independent owner's ledger."""
import json
from contextlib import asynccontextmanager
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import make_mocked_request

from bot import web_commerce


class WebWalletBalanceContract(IsolatedAsyncioTestCase):
    async def test_anonymous_browser_must_not_get_wallet(self):
        request = make_mocked_request("GET", "/mini-app/api/web-auth/web-payments/balance")
        with (
            patch("bot.web_auth._session_account", new=AsyncMock(return_value=None)),
            patch.object(web_commerce.WalletService, "snapshot", new=AsyncMock(
                side_effect=AssertionError("must not query wallet")
            )),
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 401)

    async def test_linked_telegram_without_verified_legacy_link_fails_closed(self):
        request = make_mocked_request("GET", "/mini-app/api/web-auth/web-payments/balance")
        with (
            patch("bot.web_auth._session_account", new=AsyncMock(return_value="a" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=["telegram"])),
            patch("bot.shared_accounts.store.linked_telegram_id",
                  new=AsyncMock(return_value=None)),
            patch.object(web_commerce.WalletService, "snapshot", new=AsyncMock(
                side_effect=AssertionError("must not query wallet")
            )),
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.body)["code"], "balance_unavailable")

    async def test_own_wallet_visible_after_checkout_disabled_for_recovery(self):
        request = make_mocked_request("GET", "/mini-app/api/web-auth/web-payments/balance")
        snapshot = {"scope": "live", "balance": {
            "available": "7.5000", "reserved": "2.0000", "revision": 14,
        }, "entries": [{"operation_key": "private-operation"}]}
        with (
            patch("bot.web_auth._session_account", new=AsyncMock(return_value="b" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=[])),
            patch.object(web_commerce, "_enabled", return_value=False),
            patch.object(web_commerce.WalletService, "snapshot",
                         new=AsyncMock(return_value=snapshot)) as read,
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 200)
        data = json.loads(response.body)
        self.assertEqual(data["balance"]["available"], "7.5000")
        self.assertEqual(data["balance"]["reserved"], "2.0000")
        self.assertNotIn("entries", data)
        read.assert_awaited_once_with("b" * 32)



class _LegacyCursor:
    def __init__(self, value):
        self.value = value

    async def fetchone(self):
        return self.value


class _LegacyDb:
    def __init__(self, value):
        self.value = value
        self.queries = []

    async def execute(self, sql, params=()):
        self.queries.append((sql, params))
        return _LegacyCursor(self.value)


def _legacy_db(value):
    db = _LegacyDb(value)

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield db

    return connect, db


class LinkedWebBalanceContract(IsolatedAsyncioTestCase):
    async def _request(self, raw, second_id=123456, web_available=0, web_reserved=0):
        request = make_mocked_request('GET', '/mini-app/api/web-auth/web-payments/balance')
        connect, db = _legacy_db(None if raw is None else (raw, web_available, web_reserved))
        with (
            patch('bot.web_auth._session_account', new=AsyncMock(return_value='a' * 32)),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['telegram'])),
            patch('bot.shared_accounts.store.linked_telegram_id',
                  new=AsyncMock(side_effect=[123456, second_id])),
            patch.object(web_commerce.db_backend, 'connect', new=connect),
            patch.object(web_commerce.WalletService, 'snapshot', new=AsyncMock(
                side_effect=AssertionError('must never open a duplicate shared wallet')
            )),
        ):
            response = await web_commerce.wallet_balance(request)
        return response, db

    async def test_linked_account_reads_exact_legacy_balance_with_verified_identity(self):
        response, db = await self._request(12.125)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload['scope'], 'telegram_legacy')
        self.assertEqual(payload['balance']['available'], '12.1250')
        self.assertEqual(payload['balance']['reserved'], None)
        self.assertFalse(payload['precision_review'])
        self.assertIsNone(payload['held_web_balance'])
        self.assertEqual(len(db.queries), 1)
        self.assertIn('users', db.queries[0][0])
        self.assertEqual(db.queries[0][1], ('a' * 32, 123456))

    async def test_linked_account_with_previous_web_funds_keeps_both_scopes_visible(self):
        response, db = await self._request(12.125, web_available=20000, web_reserved=3000)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload['balance']['available'], '12.1250')
        self.assertEqual(payload['held_web_balance'], {
            'available': '2.0000', 'reserved': '0.3000',
        })
        self.assertIn('LEFT JOIN shared_wallets', db.queries[0][0])
        # The response does not pretend these are one spendable balance.
        self.assertNotEqual(payload['balance']['available'], '14.1250')

    async def test_legacy_precision_is_marked_for_review_not_imported(self):
        response, _ = await self._request(0.30000000000000004)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload['balance']['available'], '0.3000')
        self.assertTrue(payload['precision_review'])

    async def test_missing_legacy_account_must_not_fabricate_zero_balance(self):
        response, _ = await self._request(None)
        self.assertEqual(response.status, 503)
        self.assertEqual(json.loads(response.body)['code'], 'balance_unavailable')

    async def test_identity_unlinked_mid_request_does_not_leak_private_balance(self):
        response, _ = await self._request(18.5, second_id=None)
        self.assertEqual(response.status, 403)

    async def test_revoked_session_during_balance_read_returns_no_funds(self):
        request = make_mocked_request('GET', '/mini-app/api/web-auth/web-payments/balance')
        connect, _ = _legacy_db((7.5, 0, 0))
        with (
            patch('bot.web_auth._session_account',
                  new=AsyncMock(side_effect=['a' * 32, None])),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['telegram'])),
            patch('bot.shared_accounts.store.linked_telegram_id',
                  new=AsyncMock(return_value=123456)),
            patch.object(web_commerce.db_backend, 'connect', new=connect),
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 401)
        self.assertNotIn('7.5000', response.text)

    async def test_nonfinite_and_negative_legacy_balance_fail_closed(self):
        for value in (float('nan'), float('inf'), -1):
            response, _ = await self._request(value)
            self.assertEqual(response.status, 503)

    async def test_vk_without_telegram_remains_financially_blocked(self):
        request = make_mocked_request('GET', '/mini-app/api/web-auth/web-payments/balance')
        with (
            patch('bot.web_auth._session_account', new=AsyncMock(return_value='a' * 32)),
            patch('bot.shared_accounts.store.linked_platforms',
                  new=AsyncMock(return_value=['vk'])),
            patch('bot.shared_accounts.store.linked_telegram_id',
                  new=AsyncMock(side_effect=AssertionError('VK must not spoof TG'))),
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 409)
