from __future__ import annotations

from aiohttp import web

from bot.internal_admin_api import (
    finance_handler,
    generations_handler,
    health_handler,
    summary_handler,
    users_handler,
)

_INTERNAL_HANDLERS = {
    "/internal/admin/health": health_handler,
    "/internal/admin/summary": summary_handler,
    "/internal/admin/users": users_handler,
    "/internal/admin/generations": generations_handler,
    "/internal/admin/finance": finance_handler,
}


async def dispatch_internal_admin_request(request: web.Request) -> web.StreamResponse:
    handler = _INTERNAL_HANDLERS.get(request.path)
    if handler is None:
        return web.json_response({"error": "not_found"}, status=404)
    return await handler(request)
