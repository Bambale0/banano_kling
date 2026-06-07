"""Unit and integration tests for bot/database.py"""

import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.database import (MASTER_PARTNER_TELEGRAM_ID, GenerationTask,
                          Transaction, User, add_credits, add_generation_task,
                          add_free_generations, check_can_afford,
                          activate_user_subscription,
                          complete_video_task, consume_free_generation,
                          consume_subscription_usage,
                          create_promo_code, create_transaction, deduct_credits,
                          get_admin_stats, get_feed_tasks,
                          get_master_partner_user, get_or_create_user,
                          get_active_subscription,
                          get_public_feed_task, get_task_by_id,
                          get_transaction_by_order, increment_feed_share,
                          like_feed_task, remove_task_from_feed,
                          share_task_to_feed,
                          get_user_credits, get_user_stats, init_db,
                          mark_promo_code_used, normalize_promo_code,
                          refund_generation_billing,
                          refund_subscription_usage,
                          validate_promo_code,
                          update_transaction_status)


@pytest_asyncio.fixture(scope="function")
async def temp_db():
    """Temporary database fixture"""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    original_db_path = "bot.database.DATABASE_PATH"

    with patch(original_db_path, db_path):
        await init_db()
        yield db_path
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_init_db(temp_db):
    """Test database initialization creates all tables"""
    async with aiosqlite.connect(temp_db) as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = await cursor.fetchall()
        table_names = [table[0] for table in tables]
        expected_tables = [
            "users",
            "transactions",
            "generation_tasks",
            "generation_history",
            "user_settings",
            "referrals",
            "partner_withdrawals",
            "batch_jobs",
        ]
        for table in expected_tables:
            assert table in table_names


@pytest.mark.asyncio
async def test_get_or_create_user(temp_db):
    """Test get_or_create_user creates and retrieves user"""
    user = await get_or_create_user(
        123456,
        username="old_user",
        first_name="Ivan",
        last_name="Petrov",
    )
    assert user.telegram_id == 123456
    assert user.credits == 10  # bonus
    assert user.referral_code is not None
    assert user.username == "old_user"
    assert user.first_name == "Ivan"

    # Get again
    user2 = await get_or_create_user(123456, username="new_user")
    assert user2.id == user.id
    assert user2.credits == 10
    assert user2.username == "new_user"
    assert user2.first_name == "Ivan"


@pytest.mark.asyncio
async def test_get_user_credits(temp_db):
    """Test get_user_credits"""
    await get_or_create_user(123456)
    credits = await get_user_credits(123456)
    assert credits == 10


@pytest.mark.asyncio
async def test_add_credits(temp_db):
    """Test add_credits"""
    await get_or_create_user(123456)
    assert await add_credits(123456, 5)
    credits = await get_user_credits(123456)
    assert credits == 15


@pytest.mark.asyncio
async def test_deduct_credits(temp_db):
    """Test deduct_credits"""
    await get_or_create_user(123456)
    assert await deduct_credits(123456, 5)
    credits = await get_user_credits(123456)
    assert credits == 5

    # Insufficient
    assert not await deduct_credits(123456, 10)


@pytest.mark.asyncio
async def test_check_can_afford(temp_db):
    """Test check_can_afford"""
    await get_or_create_user(123456)
    assert await check_can_afford(123456, 5)
    assert not await check_can_afford(123456, 15)


@pytest.mark.asyncio
async def test_subscription_usage_limit_and_refund(temp_db):
    await activate_user_subscription(
        123456,
        package_id="boom",
        package_name="Boom",
        days=30,
        image_limit=1,
        video_limit=0,
    )

    subscription = await get_active_subscription(123456)
    assert subscription is not None
    assert subscription["package_id"] == "boom"
    assert subscription["images_used"] == 0

    ok, reason, usage = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:1",
    )
    assert ok
    assert reason == "ok"

    ok, reason, duplicate = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:1",
    )
    assert ok
    assert reason == "already_consumed"
    assert duplicate["subscription_id"] == usage["subscription_id"]

    ok, reason, _ = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:2",
    )
    assert not ok
    assert reason == "limit_exhausted"

    assert await refund_subscription_usage(usage["id"])

    ok, reason, _ = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:2",
    )
    assert ok
    assert reason == "ok"


@pytest.mark.asyncio
async def test_subscription_limit_exhaustion_can_fall_back_to_credits(temp_db):
    await get_or_create_user(123456)
    await activate_user_subscription(
        123456,
        package_id="boom",
        package_name="Boom",
        days=30,
        image_limit=1,
        video_limit=0,
    )

    ok, reason, _ = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:1",
    )
    assert ok
    assert reason == "ok"

    ok, reason, _ = await consume_subscription_usage(
        123456,
        usage_type="image",
        model="banana_2",
        external_id="image:2",
    )
    assert not ok
    assert reason == "limit_exhausted"

    assert await deduct_credits(
        123456,
        2,
        reason="generation_charge",
        external_id="image:2",
    )
    assert await get_user_credits(123456) == 8


@pytest.mark.asyncio
async def test_refund_generation_billing_returns_subscription_usage(temp_db):
    user = await get_or_create_user(123456)
    await activate_user_subscription(
        123456,
        package_id="pro",
        package_name="Pro",
        days=30,
        image_limit=5,
        video_limit=1,
        includes_pro=True,
    )
    ok, reason, usage = await consume_subscription_usage(
        123456,
        usage_type="video",
        model="v3_pro",
        external_id="video:1",
    )
    assert ok
    assert reason == "ok"

    assert await add_generation_task(
        user.id,
        123456,
        "provider-task-1",
        "video",
        "no_preset_video",
        model="v3_pro",
        cost=0,
        billing_source="subscription",
        subscription_usage_id=usage["id"],
    )
    assert await refund_generation_billing("provider-task-1")

    ok, reason, _ = await consume_subscription_usage(
        123456,
        usage_type="video",
        model="v3_pro",
        external_id="video:2",
    )
    assert ok
    assert reason == "ok"


@pytest.mark.asyncio
async def test_create_transaction(temp_db):
    """Test create_transaction"""
    user = await get_or_create_user(123456)
    assert await create_transaction("order1", user.id, "pay1", "tbank", 10, 100.0)
    trans = await get_transaction_by_order("order1")
    assert trans is not None
    assert trans.credits == 10
    assert trans.status == "pending"


def test_normalize_promo_code_accepts_cyrillic_lookalikes():
    """Russian-keyboard lookalikes should not break promo activation."""
    assert normalize_promo_code("КRIS06") == "KRIS06"
    assert normalize_promo_code("КРИС06") == "KRIS06"
    assert normalize_promo_code("ВЕСНА2026") == "VESNA2026"
    assert normalize_promo_code("СТАРТ_КРИС") == "START_KRIS"
    assert normalize_promo_code("  vesna-2026 ") == "VESNA-2026"


@pytest.mark.asyncio
async def test_validate_promo_code_accepts_cyrillic_lookalike_input(temp_db):
    ok, code = await create_promo_code("KRIS06", 20, 5, None, 999999)
    assert ok
    assert code == "KRIS06"

    success, reason, promo = await validate_promo_code(123456, "КРИС06")

    assert success
    assert reason == "ok"
    assert promo["code"] == "KRIS06"
    assert promo["discount_percent"] == 20
    assert promo["promo_type"] == "discount"


@pytest.mark.asyncio
async def test_create_banana_promo_code_grants_credit_type(temp_db):
    ok, code = await create_promo_code(
        "PARTNER50",
        0,
        10,
        None,
        999999,
        promo_type="bananas",
        reward_credits=50,
    )
    assert ok
    assert code == "PARTNER50"

    success, reason, promo = await validate_promo_code(123456, "PARTNER50")

    assert success
    assert reason == "ok"
    assert promo["promo_type"] == "bananas"
    assert promo["reward_credits"] == 50
    assert promo["used_count"] == 0


@pytest.mark.asyncio
async def test_banana_promo_is_reusable_until_total_limit(temp_db):
    ok, code = await create_promo_code(
        "FREEBANANAS",
        0,
        5,
        None,
        999999,
        promo_type="bananas",
        reward_credits=25,
    )
    assert ok
    assert code == "FREEBANANAS"

    assert await mark_promo_code_used(
        123456,
        "FREEBANANAS",
        order_id="bonus:FREEBANANAS:123456:1",
    ) == (True, "ok")
    assert await mark_promo_code_used(
        123456,
        "FREEBANANAS",
        order_id="bonus:FREEBANANAS:123456:2",
    ) == (True, "ok")
    assert await mark_promo_code_used(
        123456,
        "FREEBANANAS",
        order_id="bonus:FREEBANANAS:123456:2",
    ) == (False, "already_used")


@pytest.mark.asyncio
async def test_create_generation_promo_code_grants_free_generation_type(temp_db):
    ok, code = await create_promo_code(
        "FREEGEN",
        0,
        10,
        None,
        999999,
        promo_type="generation",
        reward_credits=2,
    )
    assert ok
    assert code == "FREEGEN"

    success, reason, promo = await validate_promo_code(123456, "FREEGEN")

    assert success
    assert reason == "ok"
    assert promo["promo_type"] == "generation"
    assert promo["reward_credits"] == 2


@pytest.mark.asyncio
async def test_free_generation_balance_can_be_consumed(temp_db):
    user = await get_or_create_user(123456)
    assert user.free_generations == 0

    assert await add_free_generations(123456, 2)
    user = await get_or_create_user(123456)
    assert user.free_generations == 2

    assert await consume_free_generation(123456)
    user = await get_or_create_user(123456)
    assert user.free_generations == 1


@pytest.mark.asyncio
async def test_same_user_can_use_promo_until_total_limit(temp_db):
    ok, code = await create_promo_code("PARTNERKRIS", 20, 2, None, 999999)
    assert ok
    assert code == "PARTNERKRIS"

    success, reason, promo = await validate_promo_code(123456, "PARTNERKRIS")
    assert success
    assert reason == "ok"
    assert promo["used_count"] == 0
    assert await mark_promo_code_used(123456, "PARTNERKRIS", order_id="order-1") == (
        True,
        "ok",
    )
    success, reason, promo = await validate_promo_code(123456, "PARTNERKRIS")
    assert success
    assert reason == "ok"
    assert promo["used_count"] == 1
    assert await mark_promo_code_used(123456, "PARTNERKRIS", order_id="order-2") == (
        True,
        "ok",
    )

    success, reason, promo = await validate_promo_code(123456, "PARTNERKRIS")
    assert not success
    assert reason == "used_up"
    assert promo == {}


@pytest.mark.asyncio
async def test_promo_redemption_is_idempotent_by_order_id(temp_db):
    ok, code = await create_promo_code("START20", 20, 5, None, 999999)
    assert ok
    assert code == "START20"

    assert await mark_promo_code_used(123456, "START20", order_id="same-order") == (
        True,
        "ok",
    )
    assert await mark_promo_code_used(123456, "START20", order_id="same-order") == (
        False,
        "already_used",
    )


@pytest.mark.asyncio
async def test_update_transaction_status(temp_db):
    """Test update_transaction_status"""
    user = await get_or_create_user(123456)
    await create_transaction("order1", user.id, "pay1", "tbank", 10, 100.0)
    assert await update_transaction_status("order1", "completed")
    trans = await get_transaction_by_order("order1")
    assert trans.status == "completed"


@pytest.mark.asyncio
async def test_add_generation_task(temp_db):
    """Test add_generation_task"""
    user = await get_or_create_user(123456)
    assert await add_generation_task(
        user.id, 123456, "task1", "video", "preset1", cost=5
    )
    task = await get_task_by_id("task1")
    assert task is not None
    assert task.status == "pending"


@pytest.mark.asyncio
async def test_complete_video_task(temp_db):
    """Test complete_video_task"""
    user = await get_or_create_user(123456)
    await add_generation_task(user.id, 123456, "task1", "video", "preset1")
    assert await complete_video_task("task1", "http://result.url")
    task = await get_task_by_id("task1")
    assert task.status == "completed"
    assert task.result_url == "http://result.url"


@pytest.mark.asyncio
async def test_feed_publish_filters_and_metrics(temp_db):
    user = await get_or_create_user(123456)
    await add_generation_task(
        user.id,
        123456,
        "img_task",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="hidden prompt",
    )
    assert await share_task_to_feed("img_task", 123456) == (False, "not_ready")

    await complete_video_task("img_task", "http://result.url")
    assert await share_task_to_feed("img_task", 123456) == (True, "ok")

    public_task = await get_public_feed_task("img_task")
    assert public_task is not None
    assert public_task.prompt == "hidden prompt"
    assert await like_feed_task("img_task") == 1
    assert await increment_feed_share("img_task") == 1

    feed_tasks = await get_feed_tasks()
    assert [task.task_id for task in feed_tasks] == ["img_task"]

    assert await remove_task_from_feed("img_task", 123456)
    assert await get_public_feed_task("img_task") is None


@pytest.mark.asyncio
async def test_feed_publish_blocks_foreign_source(temp_db):
    author = await get_or_create_user(111)
    remixer = await get_or_create_user(222)
    await add_generation_task(author.id, 111, "source", "image", "banana_pro")
    await complete_video_task("source", "http://source.url")
    assert await share_task_to_feed("source", 111) == (True, "ok")

    await add_generation_task(
        remixer.id,
        222,
        "derivative",
        "image",
        "banana_pro",
        source_feed_task_id="source",
    )
    await complete_video_task("derivative", "http://derivative.url")

    assert await share_task_to_feed("derivative", 222) == (False, "foreign_source")


@pytest.mark.asyncio
async def test_get_user_stats(temp_db):
    """Test get_user_stats"""
    user = await get_or_create_user(123456)
    stats = await get_user_stats(123456)
    assert stats["credits"] == 10
    assert stats["generations"] == 0


@pytest.mark.asyncio
async def test_get_admin_stats(temp_db):
    """Test get_admin_stats"""
    stats = await get_admin_stats()
    assert stats["total_users"] >= 0
    assert stats["total_generations"] >= 0


@pytest.mark.asyncio
async def test_master_partner(temp_db):
    """Test master partner"""
    master = await get_master_partner_user()
    assert master.telegram_id == MASTER_PARTNER_TELEGRAM_ID
