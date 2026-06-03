import json
import os
import tempfile
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.database import init_db
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
    result = await service.set_hidden("mini", True)
    assert result.ok
    result = await service.set_discount("mini", 20)
    assert result.ok

    package = await service.get_package("mini")
    assert package["price_rub"] == 199
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
async def test_service_sets_single_popular_package(temp_db, service):
    result = await service.set_popular("mini")
    assert result.ok

    packages = await service.list_packages()
    popular_ids = [package["id"] for package in packages if package["popular"]]
    assert popular_ids == ["mini"]


@pytest.mark.asyncio
async def test_service_rejects_invalid_values(temp_db, service):
    assert not (await service.set_price("mini", 0)).ok
    assert not (await service.set_bonus("mini", -1)).ok
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
    assert "admin_pkg_bonus:mini" in callback_data
    assert "admin_pkg_popular:mini" in callback_data
    assert "admin_pkg_hidden:mini" in callback_data
    assert "admin_pkg_discount:mini" in callback_data


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
