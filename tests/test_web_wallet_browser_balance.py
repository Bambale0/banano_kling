"""Web balance API may read only the verified independent owner's ledger."""
import json
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

    async def test_linked_telegram_actor_has_no_second_balance_read(self):
        request = make_mocked_request("GET", "/mini-app/api/web-auth/web-payments/balance")
        with (
            patch("bot.web_auth._session_account", new=AsyncMock(return_value="a" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=["telegram"])),
            patch.object(web_commerce.WalletService, "snapshot", new=AsyncMock(
                side_effect=AssertionError("must not query wallet")
            )),
        ):
            response = await web_commerce.wallet_balance(request)
        self.assertEqual(response.status, 409)
        self.assertEqual(json.loads(response.body)["code"], "FINANCIAL_CUTOVER_REQUIRED")

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
