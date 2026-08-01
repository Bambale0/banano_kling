import asyncio
import ast
from pathlib import Path

import pytest

from bot import database
from bot import db as db_backend
from bot.services.generation_refund_service import refund_generation_credits_once


async def _refund_count(refund_key: str) -> int:
    async with db_backend.connect(database.DATABASE_PATH) as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM generation_credit_refunds WHERE refund_key = ?",
            (refund_key,),
        )
        row = await cursor.fetchone()
        return int(row[0] or 0)


@pytest.mark.asyncio
async def test_refund_key_credits_balance_only_once():
    telegram_id = 72001
    before = float((await database.get_or_create_user(telegram_id)).credits)

    first = await refund_generation_credits_once(
        telegram_id,
        2.5,
        refund_key="generation:test:once",
        reason="provider_launch_failed",
    )
    second = await refund_generation_credits_once(
        telegram_id,
        2.5,
        refund_key="generation:test:once",
        reason="duplicate_failure_handler",
    )

    after = float((await database.get_or_create_user(telegram_id)).credits)
    assert first is True
    assert second is False
    assert after - before == pytest.approx(2.5)
    assert await _refund_count("generation:test:once") == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_refunds_have_one_winner():
    telegram_id = 72002
    before = float((await database.get_or_create_user(telegram_id)).credits)

    results = await asyncio.gather(
        *(
            refund_generation_credits_once(
                telegram_id,
                3,
                refund_key="generation:test:concurrent",
                reason=f"worker_{index}",
            )
            for index in range(10)
        )
    )

    after = float((await database.get_or_create_user(telegram_id)).credits)
    assert sum(result is True for result in results) == 1
    assert after - before == pytest.approx(3)
    assert await _refund_count("generation:test:concurrent") == 1


@pytest.mark.asyncio
async def test_invalid_refund_does_not_change_balance():
    telegram_id = 72003
    before = float((await database.get_or_create_user(telegram_id)).credits)

    assert not await refund_generation_credits_once(
        telegram_id,
        0,
        refund_key="generation:test:zero",
    )
    assert not await refund_generation_credits_once(
        telegram_id,
        5,
        refund_key="",
    )

    after = float((await database.get_or_create_user(telegram_id)).credits)
    assert after == pytest.approx(before)


def test_miniapp_generation_flow_has_no_direct_credit_grants():
    path = Path("bot/miniapp.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "add_credits"
    ]

    assert not direct_calls, (
        "Mini App generation refunds must use refund_generation_credits_once; "
        f"direct add_credits calls remain at lines {direct_calls}"
    )


def test_motion_exception_refund_requires_confirmed_debit():
    source = Path("bot/miniapp.py").read_text(encoding="utf-8")

    assert "motion_debit_succeeded = False" in source
    assert "if motion_debit_succeeded:" in source
    assert "if 'telegram_id' in locals() and 'cost' in locals():" not in source
