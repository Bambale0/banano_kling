from __future__ import annotations

import logging
import re

from aiohttp import web

from bot.internal_admin_api import (
    finance_handler,
    generations_handler,
    health_handler,
    summary_handler,
)
from bot.internal_admin_command_schema import ensure_internal_admin_command_schema
from bot.internal_admin_user_commands import (
    _authorize_request,
    adjust_user_balance_handler,
    block_user_handler,
    search_users_handler,
    unblock_user_handler,
)

logger = logging.getLogger(__name__)

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


async def _dispatch_user_command(
    request: web.Request,
    *,
    user_id: str,
    action: str,
) -> web.StreamResponse:
    # Do not touch PostgreSQL schema until the caller passed both network and
    # HMAC authentication. The decorated command handler verifies it again.
    body, authorization_error = await _authorize_request(request)
    if authorization_error is not None:
        return authorization_error
    request["internal_body"] = body

    try:
        await ensure_internal_admin_command_schema()
    except Exception:
        logger.exception("Internal admin command schema is unavailable")
        return web.json_response({"error": "service_unavailable"}, status=503)

    request.match_info["user_id"] = user_id
    return await _USER_COMMAND_HANDLERS[action](request)


async def dispatch_internal_admin_request(request: web.Request) -> web.StreamResponse:
    handler = _INTERNAL_HANDLERS.get(request.path)
    if handler is not None:
        return await handler(request)

    match = _USER_COMMAND_PATH.fullmatch(request.path)
    if match is None:
        return web.json_response({"error": "not_found"}, status=404)
    return await _dispatch_user_command(
        request,
        user_id=match.group("user_id"),
        action=match.group("action"),
    )
