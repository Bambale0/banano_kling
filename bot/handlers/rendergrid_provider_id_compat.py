"""Preserve provider trace IDs across synchronous RenderGrid image completions.

RenderGrid exposes its native identifier as ``creation_id``. The legacy image
handler expects a provider-agnostic ``provider_task_id`` on synchronous results,
while the Mini App start notifier historically expects ``task_id`` to carry the
provider id and ``local_task_id`` to carry the local ``img_*`` id.

This compatibility layer normalizes those two boundaries without changing
provider routing, billing, persistence, or result delivery.
"""

from __future__ import annotations

import importlib
from functools import wraps
from typing import Any

from bot.services.rendergrid_nano_banana_provider import RenderGridNanoBananaProvider

_INSTALLED = False


def _install_rendergrid_result_normalizer() -> None:
    if getattr(RenderGridNanoBananaProvider, "_provider_id_compat_installed", False):
        return

    original_generate_image = RenderGridNanoBananaProvider.generate_image

    @wraps(original_generate_image)
    async def generate_image_with_provider_id(self, *args: Any, **kwargs: Any):
        result = await original_generate_image(self, *args, **kwargs)
        if not isinstance(result, dict):
            return result

        creation_id = str(result.get("creation_id") or "").strip()
        if not creation_id or result.get("provider_task_id"):
            return result

        normalized = dict(result)
        normalized["provider_task_id"] = creation_id
        return normalized

    RenderGridNanoBananaProvider.generate_image = generate_image_with_provider_id
    RenderGridNanoBananaProvider._provider_id_compat_installed = True


def _install_started_notifier_normalizer() -> None:
    miniapp_module = importlib.import_module("bot.miniapp")
    if getattr(miniapp_module, "_provider_id_notifier_compat_installed", False):
        return

    original_notifier = miniapp_module._notify_miniapp_image_task_queued

    @wraps(original_notifier)
    async def notify_with_provider_id(
        app: Any,
        telegram_id: int,
        launch_result: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        normalized = dict(launch_result or {})
        provider_task_id = str(normalized.get("provider_task_id") or "").strip()
        task_id = str(normalized.get("task_id") or "").strip()

        # Queued legacy launches already expose provider id as task_id and local
        # id separately. Synchronous done launches expose the inverse shape:
        # task_id is local and provider_task_id is the provider-native trace id.
        if provider_task_id:
            normalized["task_id"] = provider_task_id
            if task_id and not normalized.get("local_task_id"):
                normalized["local_task_id"] = task_id

        return await original_notifier(
            app,
            telegram_id,
            normalized,
            **kwargs,
        )

    miniapp_module._notify_miniapp_image_task_queued = notify_with_provider_id
    miniapp_module._provider_id_notifier_compat_installed = True


def install_rendergrid_provider_id_compat() -> None:
    """Install provider-result and user-facing trace-id normalization once."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _install_rendergrid_result_normalizer()
    _install_started_notifier_normalizer()
