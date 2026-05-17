"""Unit and integration tests for bot/database.py"""

import asyncio
import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.database import (MASTER_PARTNER_TELEGRAM_ID, GenerationTask,
                          Transaction, User, add_credits, add_generation_task,
                          admin_adjust_user_credits,
                          check_can_afford, complete_video_task,
                          create_transaction, deduct_credits,
                          get_admin_finance_overview, get_admin_stats,
                          get_admin_user_profile, get_admin_users_page,
                          get_master_partner_user, get_or_create_user,
                          get_primary_reference_asset,
                          get_task_by_id, get_transaction_by_order,
                          get_user_reference_assets,
                          get_user_credits, get_user_stats, init_db,
                          save_user_reference_asset,
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
    user = await get_or_create_user(123456)
    assert user.telegram_id == 123456
    assert user.credits == 10  # bonus
    assert user.referral_code is not None

    # Get again
    user2 = await get_or_create_user(123456)
    assert user2.id == user.id
    assert user2.credits == 10


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
async def test_deduct_credits_concurrent_claims_once(temp_db):
    """Concurrent deductions should not both pass the same balance check."""
    await get_or_create_user(123457)

    results = await asyncio.gather(
        deduct_credits(123457, 8),
        deduct_credits(123457, 8),
    )

    assert sorted(results) == [False, True]
    assert await get_user_credits(123457) == 2


@pytest.mark.asyncio
async def test_check_can_afford(temp_db):
    """Test check_can_afford"""
    await get_or_create_user(123456)
    assert await check_can_afford(123456, 5)
    assert not await check_can_afford(123456, 15)


@pytest.mark.asyncio
async def test_create_transaction(temp_db):
    """Test create_transaction"""
    user = await get_or_create_user(123456)
    assert await create_transaction("order1", user.id, "pay1", "yookassa", 10, 100.0)
    trans = await get_transaction_by_order("order1")
    assert trans is not None
    assert trans.credits == 10
    assert trans.status == "pending"


@pytest.mark.asyncio
async def test_update_transaction_status(temp_db):
    """Test update_transaction_status"""
    user = await get_or_create_user(123456)
    await create_transaction("order1", user.id, "pay1", "yookassa", 10, 100.0)
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
async def test_admin_user_profile_does_not_duplicate_join_sums(temp_db):
    user = await get_or_create_user(777001)
    assert await create_transaction("order-a", user.id, "pay-a", "test", 10, 100.0, "completed")
    assert await create_transaction("order-b", user.id, "pay-b", "test", 20, 200.0, "completed")
    assert await add_generation_task(user.id, user.telegram_id, "task-a", "image", "manual", cost=3)
    assert await add_generation_task(user.id, user.telegram_id, "task-b", "video", "manual", cost=7)

    profile = await get_admin_user_profile(user.telegram_id)
    page = await get_admin_users_page(limit=10, offset=0)
    page_user = next(item for item in page["users"] if item["telegram_id"] == user.telegram_id)

    assert profile["payments_rub"] == 300
    assert profile["generation_spent"] == 10
    assert profile["generation_tasks"] == 2
    assert page_user["payments_rub"] == 300
    assert page_user["generation_tasks"] == 2


@pytest.mark.asyncio
async def test_admin_adjust_user_credits_and_finance_overview(temp_db):
    user = await get_or_create_user(777002)
    assert await admin_adjust_user_credits(user.telegram_id, 15)
    assert await get_user_credits(user.telegram_id) == 25
    assert await admin_adjust_user_credits(user.telegram_id, -100)
    assert await get_user_credits(user.telegram_id) == 0

    assert await create_transaction("order-c", user.id, "pay-c", "test", 15, 150.0, "completed")
    overview = await get_admin_finance_overview()
    assert overview["completed_rub"] == 150
    assert overview["sold_credits"] == 15


@pytest.mark.asyncio
async def test_user_reference_assets_primary_uniqueness(temp_db):
    user = await get_or_create_user(888001)

    first_id = await save_user_reference_asset(
        user.telegram_id, "main", "https://example.com/main-1.jpg", is_primary=True
    )
    second_id = await save_user_reference_asset(
        user.telegram_id, "main", "https://example.com/main-2.jpg", is_primary=True
    )
    clothing_id = await save_user_reference_asset(
        user.telegram_id, "clothing", "https://example.com/dress.jpg"
    )

    assert first_id
    assert second_id
    assert clothing_id
    primary = await get_primary_reference_asset(user.telegram_id)
    main_assets = await get_user_reference_assets(user.telegram_id, "main")
    clothing_assets = await get_user_reference_assets(user.telegram_id, "clothing")

    assert primary["image_url"] == "https://example.com/main-2.jpg"
    assert sum(1 for asset in main_assets if asset["is_primary"]) == 1
    assert clothing_assets[0]["image_url"] == "https://example.com/dress.jpg"


@pytest.mark.asyncio
async def test_master_partner(temp_db):
    """Test master partner"""
    master = await get_master_partner_user()
    assert master.telegram_id == MASTER_PARTNER_TELEGRAM_ID
