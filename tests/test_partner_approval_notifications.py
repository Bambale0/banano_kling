from unittest.mock import AsyncMock

import pytest

from bot.services import partner_approval_service as approval


@pytest.mark.asyncio
async def test_retired_application_hooks_never_send_activation_messages():
    bot = AsyncMock()
    await approval.notify_admins_about_partner_application(bot, 505)
    await approval.notify_user_about_partner_review(bot, {"telegram_id": 710505}, approved=True)
    await approval.notify_user_about_partner_review(bot, {"telegram_id": 710505}, approved=False)
    bot.send_message.assert_not_awaited()
