import os
import tempfile
from unittest.mock import patch

import pytest
import pytest_asyncio

from bot.database import (
    consume_subscription_usage,
    create_transaction,
    disable_recurring_subscription,
    get_active_subscription,
    get_or_create_user,
    get_recurring_subscription,
    get_user_credits,
    init_db,
    list_due_recurring_subscriptions,
    upsert_recurring_subscription,
)
from bot.handlers.payments import (
    _complete_transaction,
    _payment_created_text,
    _recurring_choice_text,
    _topup_menu_text,
)
from bot.services.recurring_service import renew_due_recurring_subscriptions
from bot.services.admin_config_service import admin_package_config_service
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
        50,
        1490.0,
    )

    assert await _complete_transaction(order_id)

    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "boom"
    assert subscription["image_limit"] == 100
    assert subscription["video_limit"] == 0


@pytest.mark.asyncio
async def test_subscription_payment_uses_admin_package_overrides(temp_db):
    assert (await admin_package_config_service.set_image_limit("boom", 77)).ok
    assert (await admin_package_config_service.set_video_limit("boom", 2)).ok

    user = await get_or_create_user(123456)
    order_id = "123456_1000_boom"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-override",
        "tbank",
        50,
        1490.0,
    )

    assert await _complete_transaction(order_id)

    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "boom"
    assert subscription["image_limit"] == 77
    assert subscription["video_limit"] == 2


@pytest.mark.asyncio
async def test_video_only_subscription_package_activates_and_consumes_video(temp_db):
    assert (
        await admin_package_config_service.create_package(
            {
                "id": "video12",
                "name": "Видео 12",
                "kind": "subscription",
                "price_rub": 1900,
                "credits": 0,
                "bonus_credits": 0,
                "subscription_days": 30,
                "image_limit": 0,
                "video_limit": 12,
            }
        )
    ).ok
    user = await get_or_create_user(123456)
    order_id = "123456_1000_video12"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-video-only",
        "tbank",
        0,
        1900.0,
    )

    assert await _complete_transaction(order_id)

    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "video12"
    assert subscription["image_limit"] == 0
    assert subscription["video_limit"] == 12

    ok, reason, usage = await consume_subscription_usage(
        123456,
        usage_type="video",
        model="v3_std",
        external_id="video-task-1",
    )

    assert ok, reason
    assert usage["used"] == 1
    assert usage["limit"] == 12


@pytest.mark.asyncio
async def test_try_package_payment_adds_balance_and_subscription(temp_db):
    user = await get_or_create_user(123456)
    order_id = "123456_1000_try24"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-try",
        "tbank",
        5,
        149.0,
    )

    assert await _complete_transaction(order_id)

    assert await get_user_credits(123456) == 15
    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "try24"
    assert subscription["image_limit"] == 10
    assert subscription["video_limit"] == 0


@pytest.mark.asyncio
async def test_credit_package_payment_only_adds_balance(temp_db):
    user = await get_or_create_user(123456)
    order_id = "123456_1000_coin50"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-credits",
        "tbank",
        50,
        499.0,
    )

    assert await _complete_transaction(order_id)

    assert await get_user_credits(123456) == 60
    assert await get_active_subscription(123456) is None


@pytest.mark.asyncio
async def test_subscription_payment_confirms_recurring_rebill_id(temp_db):
    user = await get_or_create_user(123456)
    order_id = "123456_1000_boom"
    assert await create_transaction(
        order_id,
        user.id,
        "payment-recurring",
        "tbank",
        50,
        1490.0,
    )
    await upsert_recurring_subscription(
        123456,
        provider="tbank",
        package_id="boom",
        package_name="Boom",
        amount_rub=1490,
        credits=50,
        customer_key="123456",
        status="pending",
    )

    assert await _complete_transaction(
        order_id,
        payment_data={"RebillId": "rebill-123"},
    )

    recurring = await get_recurring_subscription(123456)
    subscription = await get_active_subscription(123456)
    assert recurring is not None
    assert recurring["status"] == "active"
    assert recurring["rebill_id"] == "rebill-123"
    assert recurring["next_charge_at"] == subscription["expires_at"]


@pytest.mark.asyncio
async def test_disable_recurring_subscription(temp_db):
    await upsert_recurring_subscription(
        123456,
        provider="tbank",
        package_id="boom",
        package_name="Boom",
        amount_rub=1490,
        credits=50,
        customer_key="123456",
        rebill_id="rebill-123",
        status="active",
    )

    assert await disable_recurring_subscription(123456)
    recurring = await get_recurring_subscription(123456)
    assert recurring["status"] == "disabled"


@pytest.mark.asyncio
async def test_due_recurring_subscription_charges_and_renews(temp_db):
    await upsert_recurring_subscription(
        123456,
        provider="tbank",
        package_id="boom",
        package_name="Boom",
        amount_rub=1490,
        credits=50,
        customer_key="123456",
        rebill_id="rebill-123",
        status="active",
        next_charge_at="2000-01-01T00:00:00",
    )
    assert len(await list_due_recurring_subscriptions()) == 1

    with patch("bot.services.recurring_service.tbank_service.init_payment") as init_mock:
        with patch(
            "bot.services.recurring_service.tbank_service.charge_recurrent"
        ) as charge_mock:
            init_mock.return_value = {
                "Success": True,
                "PaymentId": "renew-payment",
            }
            charge_mock.return_value = {
                "Success": True,
                "Status": "CONFIRMED",
                "PaymentId": "renew-payment",
            }

            assert await renew_due_recurring_subscriptions() == 1

    init_mock.assert_called_once()
    charge_mock.assert_called_once()
    assert charge_mock.call_args.kwargs["payment_id"] == "renew-payment"
    assert charge_mock.call_args.kwargs["rebill_id"] == "rebill-123"

    recurring = await get_recurring_subscription(123456)
    subscription = await get_active_subscription(123456)
    assert await get_user_credits(123456) == 60
    assert subscription is not None
    assert subscription["package_id"] == "boom"
    assert recurring["last_order_id"].startswith("r123456_")
    assert recurring["next_charge_at"] == subscription["expires_at"]


def test_subscription_payment_text_explains_hybrid_balance():
    package = preset_manager.get_package("try24")

    text = _payment_created_text(package, 5, amount_rub=149)

    assert "Бонусный баланс: <code>5</code> BoomCoin" in text
    assert "Срок: <code>24 часа</code>" in text
    assert "Фото: <code>до 10 фото</code>" in text
    assert "Подписка активируется после оплаты" in text


def test_recurring_choice_text_requires_explicit_consent():
    package = preset_manager.get_package("boom")

    text = _recurring_choice_text(package)

    assert "Оплатить" not in text
    assert "автопродление" in text
    assert "Сумма списания" in text
    assert "Периодичность" in text
    assert "поддержку" in text
    assert "Отключить можно" in text


def test_credit_payment_text_does_not_mention_subscription_access():
    package = preset_manager.get_package("coin120")

    text = _payment_created_text(package, 120, amount_rub=990)

    assert "Оплата пакета «120 BoomCoin»" in text
    assert "BoomCoin: <code>120</code> (+20 бонус)" in text
    assert "BoomCoin начислятся автоматически" in text
    assert "Подписка активируется" not in text
    assert "баланс и доступ" not in text


def test_topup_menu_text_describes_credits_and_subscription_features():
    text = _topup_menu_text()

    assert "BoomCoin" in text
    assert "Разовый баланс без срока действия" in text
    assert "После лимита бот продолжит работать за BoomCoin" in text
    assert "Подписки" in text
    assert "Boom" in text
    assert "до 100 фото" in text
    assert "Pro" in text
    assert "Banana Pro" in text
    assert "Studio" in text
    assert "приоритет" in text
