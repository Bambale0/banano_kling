from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from bot.database import Credits, get_user_credits
from bot.services.photo_prompt_billing import (
    PhotoPromptCharge,
    PhotoPromptInsufficientBalance,
    photo_prompt_cost_credits,
    photo_prompt_price_rub,
    refund_photo_prompt_charge,
    reserve_photo_prompt_charge,
)
from bot.services.preset_manager import preset_manager

ROOT = Path(__file__).resolve().parents[1]


def test_photo_prompt_is_one_ruble_and_one_tenth_credit() -> None:
    assert preset_manager.get_credit_rub_value() == 10
    assert photo_prompt_price_rub() == 1
    assert photo_prompt_cost_credits() == 0.1


def test_credit_balance_keeps_fractional_part() -> None:
    assert str(Credits(14.9)) == "14.9"
    assert inspect.signature(get_user_credits).return_annotation is Credits


@pytest.mark.asyncio
async def test_photo_prompt_charge_deducts_only_point_one_credit(mocker) -> None:
    mocker.patch("bot.services.photo_prompt_billing.config.is_admin", return_value=False)
    get_user = mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(
            side_effect=[mocker.Mock(credits=2.0), mocker.Mock(credits=1.9)]
        ),
    )
    deduct = mocker.patch(
        "bot.services.photo_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(return_value=True),
    )

    charge = await reserve_photo_prompt_charge(123)

    assert charge.charged is True
    assert charge.cost_credits == 0.1
    assert charge.price_rub == 1
    assert charge.balance_after == 1.9
    deduct.assert_awaited_once_with(123, 0.1)
    assert get_user.await_count == 2


@pytest.mark.asyncio
async def test_photo_prompt_charge_rejects_insufficient_fractional_balance(mocker) -> None:
    mocker.patch("bot.services.photo_prompt_billing.config.is_admin", return_value=False)
    mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=0.09)),
    )
    deduct = mocker.patch(
        "bot.services.photo_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(),
    )

    with pytest.raises(PhotoPromptInsufficientBalance) as error:
        await reserve_photo_prompt_charge(123)

    assert error.value.cost_credits == 0.1
    assert error.value.price_rub == 1
    deduct.assert_not_awaited()


@pytest.mark.asyncio
async def test_photo_prompt_refund_returns_exact_reserved_amount(mocker) -> None:
    add = mocker.patch(
        "bot.services.photo_prompt_billing.add_credits",
        new=mocker.AsyncMock(return_value=True),
    )
    mocker.patch(
        "bot.services.photo_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=2.0)),
    )
    charge = PhotoPromptCharge(
        telegram_id=123,
        cost_credits=0.1,
        price_rub=1,
        charged=True,
        balance_after=1.9,
    )

    balance = await refund_photo_prompt_charge(charge)

    assert balance == 2.0
    add.assert_awaited_once_with(123, 0.1)


def test_photo_prompt_contract_charges_both_surfaces_and_updates_ui() -> None:
    miniapp = (ROOT / "bot/miniapp.py").read_text(encoding="utf-8")
    handler = (ROOT / "bot/handlers/image_analyzer.py").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/miniapp-v0/components/workspace-sheet.tsx").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "schema_postgres.sql").read_text(encoding="utf-8")

    assert "await reserve_photo_prompt_charge(telegram_id)" in miniapp
    assert "await refund_photo_prompt_charge(charge)" in miniapp
    assert "await reserve_photo_prompt_charge(message.from_user.id)" in handler
    assert "await refund_photo_prompt_charge(charge)" in handler
    assert "setCredits(data.credits)" in workspace
    assert "Собрать точный промпт · 1 ₽" in workspace
    assert "credits NUMERIC(12, 4) DEFAULT 0" in schema
