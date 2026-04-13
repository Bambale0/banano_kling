"""Unit and integration tests for bot/database.py"""

import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from bot.database import (
    MASTER_PARTNER_TELEGRAM_ID,
    GenerationTask,
    Transaction,
    User,
    add_credits,
    add_generation_task,
    check_can_afford,
    complete_video_task,
    create_transaction,
    deduct_credits,
    get_admin_stats,
    get_master_partner_user,
    get_or_create_user,
    get_task_by_id,
    get_transaction_by_order,
    get_user_credits,
    get_user_stats,
    init_db,
    update_transaction_status,
)


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
async def test_check_can_afford(temp_db):
    """Test check_can_afford"""
    await get_or_create_user(123456)
    assert await check_can_afford(123456, 5)
    assert not await check_can_afford(123456, 15)


@pytest.mark.asyncio
async def test_create_transaction(temp_db):
    """Test create_transaction"""
    user = await get_or_create_user(123456)
    assert await create_transaction("order1", user.id, "pay1", "tbank", 10, 100.0)
    trans = await get_transaction_by_order("order1")
    assert trans is not None
    assert trans.credits == 10
    assert trans.status == "pending"


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
