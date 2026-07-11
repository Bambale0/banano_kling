from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from aiohttp import web

from bot.internal_admin_api import (
    finance_handler,
    generations_handler,
    health_handler,
    summary_handler,
)
from bot.internal_admin_command_schema import ensure_internal_admin_command_schema
from bot.internal_admin_operation_schema import ensure_internal_admin_operation_schema
from bot.internal_admin_operations import (
    operation_detail_handler,
    operation_timeline_handler,
    operations_handler,
    refund_operation_handler,
    replay_operation_handler,
)
from bot.internal_admin_user_commands import (
    _authorize_request,
    adjust_user_balance_handler,
    block_user_handler,
    search_users_handler,
    unblock_user_handler,
)

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class _AuthenticatedBody(bytes):
    """Signed request body that is usable as bytes and JSON text."""

    def __str__(self) -> str:
        return self.decode("utf-8")


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
_OPERATION_PATH = re.compile(
    r"^/internal/admin/operations/(?P<operation_id>[1-9][0-9]*)(?:/(?P<action>timeline|replay|refund))?$"
)
_OPERATION_HANDLERS: dict[str, Handler] = {
    "list": operations_handler,
    "detail": operation_detail_handler,
    "timeline": operation_timeline_handler,
    "replay": replay_operation_handler,
    "refund": refund_operation_handler,
}


async def _authenticate_and_prepare(
    request: web.Request,
    *,
    operations: bool,
) -> web.Response | None:
    # Schema initialization is deliberately delayed until after both the private
    # network check and exact-body HMAC verification have succeeded.
    body, authorization_error = await _authorize_request(request)
    if authorization_error is not None:
        return authorization_error
    request["internal_body"] = _AuthenticatedBody(body)

    try:
        await ensure_internal_admin_command_schema()
        if operations:
            await ensure_internal_admin_operation_schema()
    except Exception:
        logger.exception("Internal admin schema is unavailable")
        return web.json_response({"error": "service_unavailable"}, status=503)
    return None


async def _dispatch_user_command(
    request: web.Request,
    *,
    user_id: str,
    action: str,
) -> web.StreamResponse:
    preparation_error = await _authenticate_and_prepare(request, operations=False)
    if preparation_error is not None:
        return preparation_error
    request.match_info["user_id"] = user_id
    return await _USER_COMMAND_HANDLERS[action](request)


async def _dispatch_operation(
    request: web.Request,
    *,
    operation_id: str | None,
    action: str,
) -> web.StreamResponse:
    preparation_error = await _authenticate_and_prepare(request, operations=True)
    if preparation_error is not None:
        return preparation_error
    if operation_id is not None:
        request.match_info["operation_id"] = operation_id

    handler = _OPERATION_HANDLERS[action]
    undecorated = getattr(handler, "__wrapped__", handler)
    return await undecorated(request)


async def dispatch_internal_admin_request(request: web.Request) -> web.StreamResponse:
    if request.path == "/internal/admin/operations":
        return await _dispatch_operation(request, operation_id=None, action="list")

    handler = _INTERNAL_HANDLERS.get(request.path)
    if handler is not None:
        return await handler(request)

    user_match = _USER_COMMAND_PATH.fullmatch(request.path)
    if user_match is not None:
        return await _dispatch_user_command(
            request,
            user_id=user_match.group("user_id"),
            action=user_match.group("action"),
        )

    operation_match = _OPERATION_PATH.fullmatch(request.path)
    if operation_match is not None:
        return await _dispatch_operation(
            request,
            operation_id=operation_match.group("operation_id"),
            action=operation_match.group("action") or "detail",
        )
    return web.json_response({"error": "not_found"}, status=404)
