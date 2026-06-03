import os
import tempfile
from unittest.mock import patch

import pytest
import pytest_asyncio

from bot.database import (
    create_transaction,
    get_active_subscription,
    get_or_create_user,
    get_user_credits,
    init_db,
)
from bot.handlers.payments import _complete_transaction, _payment_created_text
from bot.services.preset_manager import preset_manager


@pytest_asyncio.fixture(scope="function")
async def temp_db():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    with patch("bot.database.DATABASE_PATH", db_path):
        await init_db()
        yield db_path
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_completed_subscription_payment_activates_subscription(temp_db):
    user = await get_or_create_user(123456)
    order_id = "123456_1000_boom"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-1",
        "tbank",
        99,
        990.0,
    )

    assert await _complete_transaction(order_id)

    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "boom"
    assert subscription["image_limit"] == 2000
    assert subscription["video_limit"] == 0


@pytest.mark.asyncio
async def test_try_package_payment_adds_balance_and_subscription(temp_db):
    user = await get_or_create_user(123456)
    order_id = "123456_1000_try24"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-try",
        "tbank",
        10,
        99.0,
    )

    assert await _complete_transaction(order_id)

    assert await get_user_credits(123456) == 20
    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "try24"
    assert subscription["image_limit"] == 30
    assert subscription["video_limit"] == 0


def test_subscription_payment_text_explains_hybrid_balance():
    package = preset_manager.get_package("try24")

    text = _payment_created_text(package, 10, amount_rub=99)

    assert "Бонусный баланс: <code>10</code> BoomCoin" in text
    assert "Срок: <code>24 часа</code>" in text
    assert "Фото: <code>до 30 фото</code>" in text
    assert "Подписка активируется после оплаты" in text
