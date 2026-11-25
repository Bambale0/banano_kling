"""Platform-specific payment availability at the authenticated API boundary."""

from __future__ import annotations

from aiohttp import web

_VK_LAVA_PAYMENT_PROVIDERS = frozenset({
    "lava",
    "lava_card",
    "lava_sbp",
    "lava_foreign",
    "lava_foreign_card",
    "lava_foreign_paypal",
})


def vk_payment_provider_denied(ctx: dict, provider: str) -> web.Response | None:
    """Retain VK provider scoping; Telegram and web use configured providers."""
    if ctx.get("platform") == "vk" and provider not in _VK_LAVA_PAYMENT_PROVIDERS:
        return web.json_response(
            {"ok": False, "error": "В приложении ВК доступна только оплата через Lava."},
            status=403,
        )
    return None
