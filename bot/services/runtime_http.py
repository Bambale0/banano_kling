"""Expose transient database outages without replaying HTTP side effects."""
from __future__ import annotations

import logging

from aiohttp import web
from psycopg import OperationalError

logger = logging.getLogger(__name__)
_CONNECTION_STATES = {'57P01', '57P02', '57P03', '53300'}


def database_error_response(exc: Exception) -> web.Response | None:
    if not isinstance(exc, OperationalError):
        return None
    state = exc.sqlstate or ''
    if state and not state.startswith('08') and state not in _CONNECTION_STATES:
        return None
    return web.json_response(
        {'ok': False, 'code': 'database_unavailable', 'error': 'Сервис временно недоступен. Повторите запрос через несколько секунд.'},
        status=503, headers={'Retry-After': '2'},
    )


@web.middleware
async def database_availability_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except OperationalError as exc:
        response = database_error_response(exc)
        if response is None:
            raise
        logger.warning('Database unavailable: path=%s error_type=%s sqlstate=%s', request.path, type(exc).__name__, exc.sqlstate or 'connection_lost')
        return response
