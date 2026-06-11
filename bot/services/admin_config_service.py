from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from bot.database import get_bot_setting, set_bot_setting
from bot.services.preset_manager import preset_manager


PACKAGE_SETTINGS_KEY = "admin_payment_packages"
PACKAGE_OVERRIDE_FIELDS = {
    "name",
    "kind",
    "period",
    "price_rub",
    "credits",
    "bonus_credits",
    "subscription_days",
    "image_limit",
    "photo_limit_text",
    "video_limit",
    "video_limit_text",
    "includes_pro",
    "priority",
    "popular",
    "hidden",
    "discount_enabled",
    "discount_percent",
    "original_price_rub",
}


@dataclass(frozen=True)
class PackageUpdateResult:
    ok: bool
    package: dict[str, Any] | None = None
    error: str = ""


class AdminPackageConfigService:
    """Stores admin-edited payment package settings without touching price.json."""

    def __init__(self, setting_key: str = PACKAGE_SETTINGS_KEY):
        self.setting_key = setting_key

    async def list_packages(self, include_hidden: bool = True) -> list[dict[str, Any]]:
        packages = await self._load_packages()
        if include_hidden:
            return packages
        return [package for package in packages if not package.get("hidden")]

    async def get_package(self, package_id: str) -> dict[str, Any] | None:
        for package in await self._load_packages():
            if package.get("id") == package_id:
                return package
        return None

    async def set_price(self, package_id: str, price_rub: int) -> PackageUpdateResult:
        if price_rub <= 0:
            return PackageUpdateResult(False, error="price_must_be_positive")
        return await self._update_package(package_id, {"price_rub": price_rub})

    async def create_package(self, package: dict[str, Any]) -> PackageUpdateResult:
        normalized = self._normalize_package(package)
        if not normalized["id"]:
            return PackageUpdateResult(False, error="id_required")
        if not normalized["name"]:
            return PackageUpdateResult(False, error="name_required")
        if normalized["price_rub"] <= 0:
            return PackageUpdateResult(False, error="price_must_be_positive")
        packages = await self._load_packages()
        if any(item.get("id") == normalized["id"] for item in packages):
            return PackageUpdateResult(False, error="package_exists")
        packages.append(normalized)
        await self._save_packages(packages)
        return PackageUpdateResult(True, package=copy.deepcopy(normalized))

    async def set_text_field(
        self, package_id: str, field: str, value: str
    ) -> PackageUpdateResult:
        if field not in {"name", "kind", "period", "photo_limit_text", "video_limit_text"}:
            return PackageUpdateResult(False, error="unsupported_text_field")
        value = str(value or "").strip()
        if field == "name" and not value:
            return PackageUpdateResult(False, error="name_required")
        if field == "kind" and value not in {"credits", "subscription"}:
            return PackageUpdateResult(False, error="bad_kind")
        return await self._update_package(package_id, {field: value})

    async def set_bonus(
        self, package_id: str, bonus_credits: int
    ) -> PackageUpdateResult:
        if bonus_credits < 0:
            return PackageUpdateResult(False, error="bonus_must_be_non_negative")
        return await self._update_package(package_id, {"bonus_credits": bonus_credits})

    async def set_credits(self, package_id: str, credits: int) -> PackageUpdateResult:
        if credits < 0:
            return PackageUpdateResult(False, error="credits_must_be_non_negative")
        return await self._update_package(package_id, {"credits": credits})

    async def set_subscription_days(
        self, package_id: str, days: int
    ) -> PackageUpdateResult:
        if days < 0:
            return PackageUpdateResult(False, error="days_must_be_non_negative")
        return await self._update_package(package_id, {"subscription_days": days})

    async def set_image_limit(
        self, package_id: str, image_limit: int
    ) -> PackageUpdateResult:
        if image_limit < 0:
            return PackageUpdateResult(False, error="image_limit_must_be_non_negative")
        updates: dict[str, Any] = {"image_limit": image_limit}
        if image_limit > 0:
            updates["photo_limit_text"] = f"до {image_limit} фото"
        return await self._update_package(package_id, updates)

    async def set_video_limit(
        self, package_id: str, video_limit: int
    ) -> PackageUpdateResult:
        if video_limit < 0:
            return PackageUpdateResult(False, error="video_limit_must_be_non_negative")
        updates: dict[str, Any] = {"video_limit": video_limit}
        if video_limit > 0:
            updates["video_limit_text"] = f"{video_limit} видео"
        return await self._update_package(package_id, updates)

    async def set_bool_field(
        self, package_id: str, field: str, enabled: bool
    ) -> PackageUpdateResult:
        if field not in {"includes_pro", "priority"}:
            return PackageUpdateResult(False, error="unsupported_bool_field")
        return await self._update_package(package_id, {field: bool(enabled)})

    async def set_popular(self, package_id: str) -> PackageUpdateResult:
        packages = await self._load_packages()
        target: dict[str, Any] | None = None
        for package in packages:
            package["popular"] = package.get("id") == package_id
            if package["popular"]:
                target = package

        if target is None:
            return PackageUpdateResult(False, error="package_not_found")

        await self._save_packages(packages)
        return PackageUpdateResult(True, package=copy.deepcopy(target))

    async def set_hidden(self, package_id: str, hidden: bool) -> PackageUpdateResult:
        return await self._update_package(package_id, {"hidden": hidden})

    async def set_discount(
        self, package_id: str, discount_percent: int
    ) -> PackageUpdateResult:
        if not 0 <= discount_percent <= 95:
            return PackageUpdateResult(False, error="discount_must_be_0_95")

        package = await self.get_package(package_id)
        if package is None:
            return PackageUpdateResult(False, error="package_not_found")

        updates: dict[str, Any] = {
            "discount_enabled": discount_percent > 0,
            "discount_percent": discount_percent,
        }
        if discount_percent > 0:
            updates["original_price_rub"] = package.get(
                "original_price_rub", package.get("price_rub")
            )
        else:
            updates.pop("original_price_rub", None)

        return await self._update_package(package_id, updates)

    async def reset_to_price_json(self) -> list[dict[str, Any]]:
        packages = self._default_packages()
        await self._save_packages(packages)
        return packages

    async def _update_package(
        self, package_id: str, updates: dict[str, Any]
    ) -> PackageUpdateResult:
        packages = await self._load_packages()
        for package in packages:
            if package.get("id") != package_id:
                continue

            if "discount_percent" in updates and updates["discount_percent"] == 0:
                package.pop("original_price_rub", None)
            package.update(updates)
            await self._save_packages(packages)
            return PackageUpdateResult(True, package=copy.deepcopy(package))

        return PackageUpdateResult(False, error="package_not_found")

    async def _load_packages(self) -> list[dict[str, Any]]:
        raw = await get_bot_setting(self.setting_key, "")
        if not raw:
            return self._default_packages()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._default_packages()

        packages = data.get("packages") if isinstance(data, dict) else data
        if not isinstance(packages, list):
            return self._default_packages()

        packages = [
            self._normalize_package(package)
            for package in packages
            if isinstance(package, dict)
        ]
        return self._merge_with_defaults(packages)

    async def _save_packages(self, packages: list[dict[str, Any]]) -> None:
        payload = {
            "packages": [self._normalize_package(package) for package in packages]
        }
        await set_bot_setting(
            self.setting_key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )

    def _default_packages(self) -> list[dict[str, Any]]:
        return [
            self._normalize_package(copy.deepcopy(package))
            for package in preset_manager.get_packages()
        ]

    def _merge_with_defaults(
        self, stored_packages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        default_packages = self._default_packages()
        default_by_id = {package["id"]: package for package in default_packages}
        stored_by_id = {package["id"]: package for package in stored_packages}

        matching_ids = set(default_by_id).intersection(stored_by_id)
        if len(matching_ids) < max(1, len(default_by_id) // 2):
            return default_packages

        merged: list[dict[str, Any]] = []
        for default_package in default_packages:
            package_id = default_package["id"]
            merged_package = copy.deepcopy(default_package)
            if package_id in stored_by_id:
                for field in PACKAGE_OVERRIDE_FIELDS:
                    if field in stored_by_id[package_id]:
                        merged_package[field] = stored_by_id[package_id][field]
            merged.append(self._normalize_package(merged_package))
        for package in stored_packages:
            package_id = package.get("id")
            if package_id and package_id not in default_by_id:
                merged.append(self._normalize_package(copy.deepcopy(package)))
        return merged

    @staticmethod
    def _normalize_package(package: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(package)
        normalized["id"] = str(normalized.get("id", "")).strip()
        normalized["kind"] = str(normalized.get("kind") or "credits")
        normalized["name"] = str(normalized.get("name") or normalized["id"])
        normalized["credits"] = int(normalized.get("credits", 0))
        normalized["price_rub"] = int(normalized.get("price_rub", 0))
        normalized["bonus_credits"] = int(normalized.get("bonus_credits", 0))
        normalized["subscription_days"] = int(normalized.get("subscription_days", 0) or 0)
        normalized["image_limit"] = int(normalized.get("image_limit", 0) or 0)
        if normalized["image_limit"] > 0:
            normalized["photo_limit_text"] = f"до {normalized['image_limit']} фото"
        else:
            normalized.pop("photo_limit_text", None)
        normalized["video_limit"] = int(normalized.get("video_limit", 0) or 0)
        normalized["includes_pro"] = bool(normalized.get("includes_pro", False))
        normalized["priority"] = bool(normalized.get("priority", False))
        if normalized["video_limit"] <= 0:
            normalized.pop("video_limit_text", None)
        elif not normalized.get("video_limit_text"):
            normalized["video_limit_text"] = f"{normalized['video_limit']} видео"
        normalized["popular"] = bool(normalized.get("popular", False))
        normalized["hidden"] = bool(normalized.get("hidden", False))
        normalized["discount_enabled"] = bool(normalized.get("discount_enabled", False))
        normalized["discount_percent"] = int(normalized.get("discount_percent", 0))
        if normalized["discount_percent"] <= 0:
            normalized["discount_enabled"] = False
            normalized.pop("original_price_rub", None)
        elif "original_price_rub" in normalized:
            normalized["original_price_rub"] = int(normalized["original_price_rub"])
        return normalized


admin_package_config_service = AdminPackageConfigService()
