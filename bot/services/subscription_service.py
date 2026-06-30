from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.database import (
    activate_user_subscription,
    consume_subscription_usage,
    get_active_subscription,
    refund_subscription_usage,
)


PRO_IMAGE_MODELS = {
    "banana_pro",
    "nano-banana-pro",
    "gemini_3_pro",
    "gemini-3-pro",
    "gemini-3-pro-image-preview",
    "wan_27_image_pro",
}


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    source: str
    reason: str = ""
    usage_id: int | None = None
    label: str = ""


class SubscriptionService:
    def package_entitlement(self, package: dict[str, Any]) -> dict[str, Any] | None:
        entitlement = package.get("entitlement")
        if isinstance(entitlement, dict):
            return entitlement
        is_subscription = package.get("kind") == "subscription" or bool(
            package.get("subscription_days")
        )
        if not is_subscription:
            return None
        return {
            "days": int(package.get("subscription_days") or 30),
            "image_limit": int(package.get("image_limit") or 0),
            "video_limit": int(package.get("video_limit") or 0),
            "includes_pro": bool(package.get("includes_pro")),
            "priority": bool(package.get("priority")),
        }

    def is_subscription_package(self, package: dict[str, Any]) -> bool:
        return self.package_entitlement(package) is not None

    async def activate_from_package(
        self, telegram_id: int, package: dict[str, Any]
    ) -> dict[str, Any] | None:
        entitlement = self.package_entitlement(package)
        if not entitlement:
            return None
        return await activate_user_subscription(
            telegram_id,
            package_id=str(package["id"]),
            package_name=str(package["name"]),
            days=int(entitlement["days"]),
            image_limit=int(entitlement["image_limit"]),
            video_limit=int(entitlement.get("video_limit") or 0),
            includes_pro=bool(entitlement.get("includes_pro")),
            priority=bool(entitlement.get("priority")),
        )

    async def current(self, telegram_id: int) -> dict[str, Any] | None:
        return await get_active_subscription(telegram_id)

    async def consume(
        self,
        telegram_id: int,
        *,
        usage_type: str,
        model: str,
        external_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> AccessDecision:
        model_key = (model or "").lower()
        requires_pro = usage_type == "image" and model_key in PRO_IMAGE_MODELS
        ok, reason, usage = await consume_subscription_usage(
            telegram_id,
            usage_type=usage_type,
            model=model,
            external_id=external_id,
            requires_pro=requires_pro,
            metadata=metadata,
        )
        if not ok:
            return AccessDecision(False, "subscription", reason)
        used = usage.get("used")
        limit = usage.get("limit")
        package_name = usage.get("package_name", "подписка")
        return AccessDecision(
            True,
            "subscription",
            usage_id=int(usage["id"]),
            label=f"{package_name}: {used}/{limit}",
        )

    async def refund(self, usage_id: int | None) -> bool:
        if not usage_id:
            return False
        return await refund_subscription_usage(usage_id)


subscription_service = SubscriptionService()
