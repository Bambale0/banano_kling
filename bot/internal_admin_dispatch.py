from __future__ import annotations

import re

from aiohttp import web

from bot.internal_admin_api import (
    finance_handler,
    generations_handler,
    health_handler,
    summary_handler,
)
from bot.internal_admin_user_commands import (
    adjust_user_balance_handler,
    block_user_handler,
    search_users_handler,
    unblock_user_handler,
)

_INTERNAL_HANDLERS = {
    "/internal/admin/health": health_handler,
    "/internal/admin/summary": summary_handler,
    "/internal/admin/users": search_users_handler,
    "/internal/admin/generations": generations_handler,
    "/internal/admin/finance": finance_handler,
}
_USER_COMMAND_PATH = re.compile(
    r"^/internal/admin/users/(?P<user_id>[1-9][0-9]*)/(?P<action>block|unblock|balance-adjustments)$"
)
_USER_COMMAND_HANDLERS = {
    "block": block_user_handler,
    "unblock": unblock_user_handler,
    "balance-adjustments": adjust_user_balance_handler,
}


async def dispatch_internal_admin_request(request: web.Request) -> web.StreamResponse:
    handler = _INTERNAL_HANDLERS.get(request.path)
    if handler is not None:
        return await handler(request)

    match = _USER_COMMAND_PATH.fullmatch(request.path)
    if match is None:
        return web.json_response({"error": "not_found"}, status=404)
    request.match_info["user_id"] = match.group("user_id")
    return await _USER_COMMAND_HANDLERS[match.group("action")](request)
