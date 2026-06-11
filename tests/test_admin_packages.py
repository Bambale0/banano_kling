import json
import os
import tempfile
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.database import init_db
from bot.database import set_bot_setting
from bot.handlers.admin_packages import (
    format_packages_text,
    get_admin_packages_keyboard,
)
from bot.services.admin_config_service import AdminPackageConfigService


@pytest_asyncio.fixture
async def temp_db():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    with patch("bot.database.DATABASE_PATH", db_path):
        await init_db()
        yield db_path
    os.unlink(db_path)


@pytest.fixture
def default_packages():
    return [
        {
            "id": "mini",
            "name": "Мини",
            "credits": 15,
            "price_rub": 150,
            "bonus_credits": 0,
        },
        {
            "id": "pro",
            "name": "Про",
            "credits": 100,
            "price_rub": 900,
            "bonus_credits": 15,
            "subscription_days": 30,
            "image_limit": 180,
            "video_limit": 4,
            "includes_pro": True,
            "popular": True,
        },
    ]


@pytest.fixture
def service(default_packages):
    svc = AdminPackageConfigService(setting_key="test_admin_payment_packages")
    with patch(
        "bot.services.admin_config_service.preset_manager.get_packages",
        return_value=default_packages,
    ):
        yield svc


@pytest.mark.asyncio
async def test_service_updates_packages_in_bot_settings(temp_db, service):
    result = await service.set_price("mini", 199)
    assert result.ok
    result = await service.set_bonus("mini", 3)
    assert result.ok
    result = await service.set_credits("mini", 22)
    assert result.ok
    result = await service.set_hidden("mini", True)
    assert result.ok
    result = await service.set_discount("mini", 20)
    assert result.ok

    package = await service.get_package("mini")
    assert package["price_rub"] == 199
    assert package["credits"] == 22
    assert package["bonus_credits"] == 3
    assert package["hidden"] is True
    assert package["discount_enabled"] is True
    assert package["discount_percent"] == 20
    assert package["original_price_rub"] == 199

    async with aiosqlite.connect(temp_db) as db:
        cursor = await db.execute(
            "SELECT value FROM bot_settings WHERE key = ?",
            ("test_admin_payment_packages",),
        )
        row = await cursor.fetchone()

    assert row is not None
    stored = json.loads(row[0])
    assert stored["packages"][0]["price_rub"] == 199


@pytest.mark.asyncio
async def test_service_updates_subscription_limits(temp_db, service):
    assert (await service.set_subscription_days("pro", 14)).ok
    assert (await service.set_image_limit("pro", 77)).ok
    assert (await service.set_video_limit("pro", 3)).ok
    assert (await service.set_bool_field("pro", "includes_pro", False)).ok
    assert (await service.set_bool_field("pro", "priority", True)).ok

    package = await service.get_package("pro")

    assert package["subscription_days"] == 14
    assert package["image_limit"] == 77
    assert package["photo_limit_text"] == "до 77 фото"
    assert package["video_limit"] == 3
    assert package["video_limit_text"] == "3 видео"
    assert package["includes_pro"] is False
    assert package["priority"] is True


@pytest.mark.asyncio
async def test_service_sets_single_popular_package(temp_db, service):
    result = await service.set_popular("mini")
    assert result.ok

    packages = await service.list_packages()
    popular_ids = [package["id"] for package in packages if package["popular"]]
    assert popular_ids == ["mini"]


@pytest.mark.asyncio
async def test_service_creates_and_keeps_custom_package(temp_db, service):
    result = await service.create_package(
        {
            "id": "video_pack",
            "name": "Видео пакет",
            "kind": "subscription",
            "period": "месяц",
            "price_rub": 1900,
            "credits": 0,
            "bonus_credits": 0,
            "subscription_days": 30,
            "image_limit": 0,
            "video_limit": 12,
            "includes_pro": False,
        }
    )

    assert result.ok
    packages = await service.list_packages()
    by_id = {package["id"]: package for package in packages}

    assert set(by_id) == {"mini", "pro", "video_pack"}
    assert by_id["video_pack"]["name"] == "Видео пакет"
    assert by_id["video_pack"]["kind"] == "subscription"
    assert by_id["video_pack"]["period"] == "месяц"
    assert by_id["video_pack"]["credits"] == 0
    assert by_id["video_pack"]["video_limit"] == 12


@pytest.mark.asyncio
async def test_service_updates_package_text_fields(temp_db, service):
    assert (await service.set_text_field("mini", "name", "Старт")).ok
    assert (await service.set_text_field("mini", "kind", "credits")).ok
    assert (await service.set_text_field("mini", "period", "разово")).ok

    package = await service.get_package("mini")

    assert package["name"] == "Старт"
    assert package["kind"] == "credits"
    assert package["period"] == "разово"


@pytest.mark.asyncio
async def test_service_ignores_stale_package_overrides_without_matching_ids(
    temp_db, service
):
    await set_bot_setting(
        "test_admin_payment_packages",
        json.dumps(
            {
                "packages": [
                    {
                        "id": "legacy",
                        "name": "Legacy",
                        "credits": 999,
                        "price_rub": 1,
                    }
                ]
            }
        ),
    )

    packages = await service.list_packages()

    assert [package["id"] for package in packages] == ["mini", "pro"]


@pytest.mark.asyncio
async def test_service_merges_matching_overrides_with_default_packages(
    temp_db, service
):
    await set_bot_setting(
        "test_admin_payment_packages",
        json.dumps(
            {
                "packages": [
                    {
                        "id": "mini",
                        "name": "Мини old",
                        "credits": 17,
                        "price_rub": 199,
                    }
                ]
            }
        ),
    )

    packages = await service.list_packages()

    assert [package["id"] for package in packages] == ["mini", "pro"]
    assert packages[0]["price_rub"] == 199
    assert packages[0]["credits"] == 17
    assert packages[1]["id"] == "pro"


@pytest.mark.asyncio
async def test_service_rejects_invalid_values(temp_db, service):
    assert not (await service.set_price("mini", 0)).ok
    assert not (await service.set_bonus("mini", -1)).ok
    assert not (await service.set_credits("mini", -1)).ok
    assert not (await service.set_subscription_days("pro", -1)).ok
    assert not (await service.set_image_limit("pro", -1)).ok
    assert not (await service.set_video_limit("pro", -1)).ok
    assert not (await service.set_bool_field("pro", "unknown", True)).ok
    assert not (await service.set_discount("mini", 96)).ok
    assert not (await service.set_hidden("missing", True)).ok


def test_admin_packages_keyboard_contains_package_actions(default_packages):
    kb = get_admin_packages_keyboard(default_packages)
    callback_data = [
        button.callback_data
        for row in kb.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert "admin_pkg_price:mini" in callback_data
    assert "admin_pkg_credits:mini" in callback_data
    assert "admin_pkg_bonus:mini" in callback_data
    assert "admin_pkg_popular:mini" in callback_data
    assert "admin_pkg_hidden:mini" in callback_data
    assert "admin_pkg_discount:mini" in callback_data
    assert "admin_pkg_days:pro" in callback_data
    assert "admin_pkg_images:pro" in callback_data
    assert "admin_pkg_videos:pro" in callback_data
    assert "admin_pkg_pro:pro" in callback_data
    assert "admin_pkg_priority:pro" in callback_data


def test_format_packages_text_shows_statuses(default_packages):
    packages = [
        {
            **default_packages[0],
            "hidden": True,
            "discount_enabled": True,
            "discount_percent": 15,
        }
    ]

    text = format_packages_text(packages)

    assert "Пакеты" in text
    assert "скрыт" in text
    assert "скидка 15%" in text
