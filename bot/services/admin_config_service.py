from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from bot.database import get_bot_setting, set_bot_setting
from bot.services.preset_manager import preset_manager


PACKAGE_SETTINGS_KEY = "admin_payment_packages"


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

    async def set_bonus(
        self, package_id: str, bonus_credits: int
    ) -> PackageUpdateResult:
        if bonus_credits < 0:
            return PackageUpdateResult(False, error="bonus_must_be_non_negative")
        return await self._update_package(package_id, {"bonus_credits": bonus_credits})

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

        return [
            self._normalize_package(package)
            for package in packages
            if isinstance(package, dict)
        ]

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

    @staticmethod
    def _normalize_package(package: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(package)
        normalized["id"] = str(normalized.get("id", "")).strip()
        normalized["name"] = str(normalized.get("name") or normalized["id"])
        normalized["credits"] = int(normalized.get("credits", 0))
        normalized["price_rub"] = int(normalized.get("price_rub", 0))
        normalized["bonus_credits"] = int(normalized.get("bonus_credits", 0))
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
