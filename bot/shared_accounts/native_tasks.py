"""Platform-neutral task history views backed by VK's actual native SQLite.

These methods have the *same* history/detail JSON shape as Telegram's shared
Mini App. They do not grant the whole studio access or invent TG actor IDs.
"""
from __future__ import annotations

import re
from typing import Any

from aiohttp import web

from .actor import PlatformActor
from .task_view import serialize_native_vk_tasks
from .vk_native import (
    NativeVkTaskNotFound,
    fetch_native_vk_task_detail,
    fetch_native_vk_task_history,
)

_TASK_ID = re.compile(r"vk:([1-9][0-9]{0,18})\Z")


def _vk_actor_id(actor: PlatformActor) -> int:
    if not isinstance(actor, PlatformActor) or actor.platform != "vk":
        raise PermissionError("Native VK history requires a signed VK actor")
    if type(actor.external_id) is not int or not 0 < actor.external_id < 2**63:
        raise PermissionError("Invalid verified VK actor")
    return actor.external_id


def _native_task_id(value: str) -> int:
    if not isinstance(value, str):
        raise TypeError("VK task ID must be namespaced")
    match = _TASK_ID.fullmatch(value)
    if not match:
        raise ValueError("VK task ID must be namespaced")
    task_id = int(match.group(1))
    if task_id >= 2**63:
        raise ValueError("VK task ID out of range")
    return task_id


class VkNativeTaskService:
    async def history(self, actor: PlatformActor, cursor: str | None = None) -> dict:
        owner = _vk_actor_id(actor)
        index = _native_task_id(cursor) if cursor is not None else None
        native = await fetch_native_vk_task_history(owner, cursor=index)
        tasks = serialize_native_vk_tasks(native["tasks"])
        following = native["next_cursor"]
        return {
            "ok": True,
            "recent_tasks": tasks,
            "next_cursor": f"vk:{following}" if following is not None else None,
            "cursor_reset": native["cursor_reset"],
        }

    async def detail(self, actor: PlatformActor, task_id: str) -> dict | None:
        owner = _vk_actor_id(actor)
        native_id = _native_task_id(task_id)
        try:
            native = await fetch_native_vk_task_detail(owner, native_id)
        except NativeVkTaskNotFound:
            return None
        tasks = serialize_native_vk_tasks([native["task"]])
        if len(tasks) != 1 or tasks[0]["task_id"] != task_id:
            raise RuntimeError("Native VK task detail integrity error")
        # The native DB does not yet identify copied protected trend recipes.
        # Never guess whether raw prompts/reference URLs are public.
        task = {
            **tasks[0],
            "prompt": "",
            "prompt_hidden": True,
            "prompt_actions_allowed": False,
        }
        return {"ok": True, "task": task}


class VkNativeTasksAdapter:
    """Explicit incomplete domain adapter; never advertises 1:1 readiness."""
    ready_operations = frozenset({"tasks"})

    def __init__(self, service: VkNativeTaskService | None = None) -> None:
        self.service = service or VkNativeTaskService()

    async def handle(self, request: web.Request, *, actor: PlatformActor) -> web.Response:
        _vk_actor_id(actor)
        if request.method != "POST":
            return web.json_response({"ok": False, "error": "Method not allowed"}, status=405)
        if request.content_length is not None and request.content_length > 32768:
            return web.json_response({"ok": False, "error": "Request too large"}, status=413)
        try:
            body: Any = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "Invalid payload"}, status=400)
        # The auth token is only verified in the gateway; no user-supplied
        # owner IDs or roles are honored here.
        common_fields = {"init_data", "start_param_fallback"}
        try:
            if request.path.endswith("/api/task-history"):
                if set(body) - common_fields - {"cursor"}:
                    raise ValueError("Invalid history request")
                data = await self.service.history(actor, body.get("cursor"))
            elif request.path.endswith("/api/task-detail"):
                if set(body) - common_fields - {"task_id"}:
                    raise ValueError("Invalid detail request")
                data = await self.service.detail(actor, body.get("task_id"))
                if data is None:
                    return web.json_response({"ok": False, "error": "Task not found"}, status=404)
            else:
                # No fake bootstrap, catalogue or payment operations.
                return web.json_response({
                    "ok": False, "error": "VK adapter operation not implemented",
                }, status=501)
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "Invalid task request"}, status=400)
        except NativeVkTaskNotFound:
            return web.json_response({"ok": False, "error": "VK account not found"}, status=404)
        except PermissionError:
            return web.json_response({"ok": False, "error": "Access denied"}, status=403)
        return web.json_response(data, headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        })
