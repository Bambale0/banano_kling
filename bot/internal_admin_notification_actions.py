from __future__ import annotations

import json

from aiohttp import web

from bot import internal_admin_notifications as notifications
from bot.internal_admin_user_commands import internal_user_endpoint


@internal_user_endpoint
async def test_campaign_handler(request: web.Request) -> web.Response:
    """Preserve the original HTTP result for idempotent test-send retries."""

    response = await notifications.test_campaign_handler.__wrapped__(request)
    if response.status != 200:
        return response

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        return response

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict) and data.get("status") == "failed":
        return web.json_response(payload, status=502)
    return response
