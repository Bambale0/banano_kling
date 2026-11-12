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


def _strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item) for item in value
    )


def _model_identity(item: object, reference_field: str) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str) and bool(item["id"])
        and isinstance(item.get("label"), str) and bool(item["label"])
        and _strings(item.get("ratios"))
        and type(item.get(reference_field)) is int
        and 0 <= item[reference_field] <= 4
    )


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
        if (
            not isinstance(state, dict)
            or type(state.get("registered")) is not bool
            or type(state.get("is_blocked")) is not bool
            or not isinstance(state.get("tasks"), list)
        ):
            raise RuntimeError("Invalid native VK state")
        if not state["registered"] or state["is_blocked"]:
            raise PermissionError("VK account is unavailable")
        models = await self._models(owner)
        if (
            not isinstance(models, dict) or models.get("ok") is not True
            or not isinstance(models.get("photo_models"), list)
            or not isinstance(models.get("video_models"), list)
        ):
            raise RuntimeError("Invalid native VK catalogue")
        commerce = await self._commerce(owner)
        if (
            not isinstance(commerce, dict) or commerce.get("ok") is not True
            or type(commerce.get("registered")) is not bool
            or not isinstance(commerce.get("payment_packages"), list)
        ):
            raise RuntimeError("Invalid native VK commerce")
        if commerce["registered"] is not True:
            raise PermissionError("VK account is not registered")
        # The two reads are not a transaction: payment/debit may happen between
        # them. Display the later native commerce snapshot, never require two
        # independently read balances to match. Submission rechecks funds.
        balance = _money(commerce.get("balance"))

        image_models = []
        for item in models.get("photo_models", []):
            if (
                not _model_identity(item, "max_references")
                or not isinstance(item.get("quality_costs"), dict)
                or not _strings(item.get("resolutions"))
                or set(item["quality_costs"]) != set(item["resolutions"])
                or "cost" not in item
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
                not _model_identity(item, "max_image_references")
                or not isinstance(item.get("durations"), list)
                or not item["durations"]
                or any(type(value) is not int or not 1 <= value <= 60 for value in item["durations"])
                or not _strings(item.get("scenarios"))
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
        packages = []
        for item in commerce["payment_packages"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str) or not item["id"]
                or type(item.get("credits")) is not int or item["credits"] <= 0
                or type(item.get("price_rub")) is not int or item["price_rub"] <= 0
                or (item.get("lava_offer_id") is not None and not isinstance(item["lava_offer_id"], str))
            ):
                raise RuntimeError("Invalid native VK payment package")
            packages.append({
                "id": item["id"], "name": f"{item['credits']} бананов",
                "credits": item["credits"], "price_rub": item["price_rub"],
                **({"lava_offer_id": item["lava_offer_id"]} if item.get("lava_offer_id") else {}),
            })
        return {
            "ok": True, "first_name": "VK", "credits": balance,
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
