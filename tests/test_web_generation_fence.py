"""Browser paid job safety gates; synthetic accounts only, no real provider."""
from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import make_mocked_request

from bot import web_generation


class PaidGenerationAvailability(TestCase):
    def test_generation_cannot_start_without_checkout_and_durable_storage(self):
        with (
            patch.dict(os.environ, {"WEB_NATIVE_GENERATION_ENABLED": "1",
                                   "WEB_NATIVE_PAYMENTS_ENABLED": "0"}),
            patch.object(web_generation.config, "KIE_AI_API_KEY", "test-key"),
        ):
            self.assertFalse(web_generation._enabled())
        with (
            patch.dict(os.environ, {"WEB_NATIVE_GENERATION_ENABLED": "1",
                                   "WEB_NATIVE_PAYMENTS_ENABLED": "1"}),
            patch.object(web_generation.config, "KIE_AI_API_KEY", ""),
        ):
            self.assertFalse(web_generation._enabled())


class LinkedLegacyWalletFence(IsolatedAsyncioTestCase):
    async def test_verified_telegram_linked_browser_cannot_reserve_new_wallet(self):
        request = make_mocked_request(
            "POST", "/mini-app/api/web-auth/web-generation/create",
        )
        with (
            patch("bot.web_auth._valid_browser_origin", return_value=True),
            patch("bot.web_auth._session_account",
                  new=AsyncMock(return_value="a" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=["telegram"])),
            patch.object(web_generation, "_enabled", return_value=True),
            patch.object(web_generation.config, "KIE_AI_API_KEY", "test-token"),
            patch.object(web_generation, "reserve_web_task",
                         new=AsyncMock(side_effect=AssertionError("must not spend"))),
        ):
            response = await web_generation.create_generation(request)
        self.assertEqual(response.status, 409)

    async def test_unlinked_web_actor_fails_closed_when_generation_disabled(self):
        request = make_mocked_request(
            "POST", "/mini-app/api/web-auth/web-generation/create",
        )
        with (
            patch("bot.web_auth._valid_browser_origin", return_value=True),
            patch("bot.web_auth._session_account",
                  new=AsyncMock(return_value="a" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=[])),
            patch.object(web_generation, "_enabled", return_value=False),
            patch.object(web_generation, "reserve_web_task",
                         new=AsyncMock(side_effect=AssertionError("must not spend"))),
        ):
            response = await web_generation.create_generation(request)
        self.assertEqual(response.status, 503)


class RollbackRecovery(IsolatedAsyncioTestCase):
    async def test_fallback_worker_probes_pending_jobs_while_off(self):
        """No new launches, but reserved prior orders must not be abandoned."""
        from unittest.mock import MagicMock

        database = AsyncMock()
        rows = AsyncMock()
        rows.fetchall.return_value = []
        database.execute.return_value = rows
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=database)
        context.__aexit__ = AsyncMock(return_value=None)
        with (
            patch.object(web_generation.config, "KIE_AI_API_KEY", "test-key"),
            patch.object(web_generation, "_enabled", return_value=False),
            patch.object(web_generation, "_pending_web_tasks_exist",
                         new=AsyncMock(return_value=True)),
            patch.object(web_generation, "ensure_web_tasks_schema",
                         new=AsyncMock()) as ensure,
            patch.object(web_generation.db_backend, "connect", return_value=context),
        ):
            self.assertEqual(await web_generation.run_worker_tick(), [])
            ensure.assert_awaited_once()


class DirectWalletReserveFence(IsolatedAsyncioTestCase):
    async def test_no_internal_paid_adapter_can_reserve_a_linked_legacy_wallet(self):
        with (
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=["telegram"])),
            patch.object(web_generation, "_enabled", return_value=True),
            patch.object(web_generation, "ensure_web_tasks_schema",
                         new=AsyncMock(side_effect=AssertionError("no schema/money"))),
        ):
            response = await web_generation.reserve_web_task(
                "a" * 32, {}, "1.0000", 10000,
            )
        self.assertEqual(response.status, 409)

    async def test_omni_asset_launch_uses_the_same_linked_wallet_fence(self):
        from bot import web_omni_assets

        request = make_mocked_request(
            "POST", "/mini-app/api/web-auth/web-omni/assets/create",
        )
        with (
            patch("bot.web_auth._valid_browser_origin", return_value=True),
            patch("bot.web_auth._session_account",
                  new=AsyncMock(return_value="a" * 32)),
            patch("bot.shared_accounts.store.linked_platforms",
                  new=AsyncMock(return_value=["telegram"])),
            patch.object(web_generation, "_enabled", return_value=True),
            patch.object(web_omni_assets, "_prepare",
                         new=AsyncMock(side_effect=AssertionError("no provider"))),
        ):
            response = await web_omni_assets.create_asset(request)
        self.assertEqual(response.status, 409)
