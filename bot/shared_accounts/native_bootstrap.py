"""Shared Mini App bootstrap backed only by the authoritative native VK actor."""
from __future__ import annotations

import math
from collections.abc import Awaitable, Callable

from aiohttp import web

from .actor import PlatformActor
from .native_tasks import VkNativeTasksAdapter
from .task_view import serialize_native_vk_tasks
from .vk_native import (
    fetch_native_vk_commerce,
    fetch_native_vk_models,
    fetch_native_vk_state,
)

Reader = Callable[[int], Awaitable[dict]]


def _money(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise RuntimeError("Invalid native VK price")
    return float(value)


class VkNativeBootstrapService:
    def __init__(
        self,
        *,
        state_reader: Reader = fetch_native_vk_state,
        model_reader: Reader = fetch_native_vk_models,
        commerce_reader: Reader = fetch_native_vk_commerce,
    ) -> None:
        self._state = state_reader
        self._models = model_reader
        self._commerce = commerce_reader

    async def bootstrap(self, actor: PlatformActor) -> dict:
        if not isinstance(actor, PlatformActor) or actor.platform != "vk":
            raise PermissionError("Native VK bootstrap requires a verified VK actor")
        owner = actor.external_id
        if type(owner) is not int or not 0 < owner < 2**63:
            raise PermissionError("Invalid verified VK actor")
        state = await self._state(owner)
        models = await self._models(owner)
        commerce = await self._commerce(owner)
        if state.get("registered") is not True or commerce.get("registered") is not True:
            raise PermissionError("VK account is not registered")
        state_balance = _money(state.get("balance"))
        commerce_balance = _money(commerce.get("balance"))
        if abs(state_balance - commerce_balance) > 1e-6:
            raise RuntimeError("Native VK wallet snapshot mismatch")

        image_models = []
        for item in models.get("photo_models", []):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("quality_costs"), dict)
                or not isinstance(item.get("resolutions"), list)
                or set(item["quality_costs"]) != set(item["resolutions"])
            ):
                raise RuntimeError("Invalid native VK photo price catalogue")
            costs = {str(key): _money(value) for key, value in item["quality_costs"].items()}
            image_models.append({
                "id": item["id"], "label": item["label"], "description": "",
                "cost": _money(item["cost"]), "ratios": list(item["ratios"]),
                "requires_reference": False, "max_references": item["max_references"],
                "qualities": list(item["resolutions"]), "quality_costs": costs,
            })
        video_models = []
        for item in models.get("video_models", []):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("durations"), list)
                or not isinstance(item.get("costs"), dict)
                or set(item["costs"]) != {str(value) for value in item["durations"]}
            ):
                raise RuntimeError("Invalid native VK video price catalogue")
            video_models.append({
                "id": item["id"], "label": item["label"], "description": "",
                "durations": list(item["durations"]), "ratios": list(item["ratios"]),
                "supports": list(item["scenarios"]),
                "costs": {str(key): _money(value) for key, value in item["costs"].items()},
                "max_image_references": item["max_image_references"],
                "max_video_references": 0, "max_audio_references": 0,
            })
        packages = [{
            "id": item["id"], "name": f"{item['credits']} бананов",
            "credits": item["credits"], "price_rub": item["price_rub"],
            **({"lava_offer_id": item["lava_offer_id"]} if item.get("lava_offer_id") else {}),
        } for item in commerce.get("payment_packages", [])]
        return {
            "ok": True, "first_name": "VK", "credits": state_balance,
            "is_admin": False, "mini_app_url": "", "actions": [],
            "payment_packages": packages, "image_models": image_models,
            "video_models": video_models,
            "recent_tasks": serialize_native_vk_tasks(state.get("tasks", []), strict=False),
            "saved_references": [], "telegram_chat_available": False,
            "telegram_bot_start_required": False,
        }


class VkNativeAppAdapter:
    """Incremental composite; the full gateway rejects it until every domain exists."""

    ready_operations = frozenset({"bootstrap", "tasks"})

    def __init__(
        self,
        bootstrap: VkNativeBootstrapService | None = None,
        tasks: VkNativeTasksAdapter | None = None,
    ) -> None:
        self.bootstrap_service = bootstrap or VkNativeBootstrapService()
        self.tasks = tasks or VkNativeTasksAdapter()

    async def handle(self, request: web.Request, *, actor: PlatformActor) -> web.Response:
        if request.path.endswith("/api/bootstrap"):
            if request.method != "POST":
                return web.json_response({"ok": False, "error": "Method not allowed"}, status=405)
            if request.content_length is not None and request.content_length > 32768:
                return web.json_response({"ok": False, "error": "Request too large"}, status=413)
            try:
                body = await request.json()
            except (TypeError, ValueError):
                return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
            if not isinstance(body, dict) or set(body) - {"init_data", "start_param_fallback"}:
                return web.json_response({"ok": False, "error": "Invalid bootstrap request"}, status=400)
            return web.json_response(
                await self.bootstrap_service.bootstrap(actor),
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        if request.path.endswith(("/api/task-history", "/api/task-detail")):
            return await self.tasks.handle(request, actor=actor)
        return web.json_response({"ok": False, "error": "VK adapter operation not implemented"}, status=501)
