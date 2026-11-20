"""Platform-specific payment availability at the authenticated API boundary."""

from __future__ import annotations

import logging
import re

from aiohttp import web

logger = logging.getLogger(__name__)

_VK_LAVA_PAYMENT_PROVIDERS = frozenset({
    "lava",
    "lava_card",
    "lava_sbp",
    "lava_foreign",
    "lava_foreign_card",
    "lava_foreign_paypal",
})


def vk_payment_provider_denied(ctx: dict, provider: str) -> web.Response | None:
    """Use authenticated context only; never trust client platform/intent fields.

    browser_ query IDs are minted and HMAC-signed by browser_auth after widget
    verification. _get_user_context validates their signature and expiry.
    webstudio_ query IDs also require a LIVE verified website-session bridge;
    trust only the server-owned proof set AFTER verify_studio_bridge succeeds.
    Keep the historical function name for compatibility with VK integrations.
    """
    if ctx.get("platform") == "vk" and provider not in _VK_LAVA_PAYMENT_PROVIDERS:
        return web.json_response(
            {"ok": False, "error": "В приложении ВК доступна только оплата через Lava."},
            status=403,
        )
    query_id = str((ctx.get("payload") or {}).get("query_id") or "")
    website_checkout_verified = (
        query_id.startswith("browser_")
        or (
            ctx.get("webstudio_session_verified") is True
            and re.fullmatch(r"webstudio_[A-Za-z0-9_-]{16,40}", query_id) is not None
        )
    )
    if (ctx.get("platform") != "vk" and provider not in {"telegram_stars", "stars", "xtr"}
            and not website_checkout_verified):
        from bot.web_payments import web_payment_url

        logger.info("Payment surface denied: surface=telegram provider=%s", provider)
        return web.json_response(
            {"ok": False, "code": "WEB_PAYMENT_REQUIRED",
             "error": "Этот способ оплаты доступен на сайте. В Telegram доступны только Stars.",
             "web_url": web_payment_url()}, status=403,
            headers={"Cache-Control": "no-store"},
        )
    return None
