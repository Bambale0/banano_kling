from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)

_connections: dict[int, set[web.WebSocketResponse]] = defaultdict(set)


async def register_ws(telegram_id: int, ws: web.WebSocketResponse) -> None:
    _connections[telegram_id].add(ws)


async def unregister_ws(telegram_id: int, ws: web.WebSocketResponse) -> None:
    sockets = _connections.get(telegram_id)
    if not sockets:
        return
    sockets.discard(ws)
    if not sockets:
        _connections.pop(telegram_id, None)


async def notify_task_update(telegram_id: int, task: dict[str, Any]) -> None:
    sockets = list(_connections.get(int(telegram_id) or 0, set()))
    if not sockets:
        return
    payload = json.dumps({"type": "task_update", "task": task}, ensure_ascii=False, default=str)
    stale: list[web.WebSocketResponse] = []
    for ws in sockets:
        if ws.closed:
            stale.append(ws)
            continue
        try:
            await ws.send_str(payload)
        except Exception:
            logger.exception("Failed to push TMA task update to %s", telegram_id)
            stale.append(ws)
    for ws in stale:
        await unregister_ws(telegram_id, ws)


async def keep_ws_alive(ws: web.WebSocketResponse) -> None:
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            if msg.data == "ping":
                await ws.send_str('{"type":"pong"}')
        elif msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
            break
