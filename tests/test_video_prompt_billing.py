from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.video_prompt_billing import (
    VideoPromptCharge,
    VideoPromptInsufficientBalance,
    refund_video_prompt_charge,
    reserve_video_prompt_charge,
    video_prompt_cost_credits,
)

ROOT = Path(__file__).resolve().parents[1]


def _video_prompt_handler_source() -> str:
    source = (ROOT / "bot/handlers/image_analyzer.py").read_text(encoding="utf-8")
    start = source.index("async def analyze_video_prompt")
    end = source.index(
        "@router.message(ImageAnalyzerStates.waiting_for_video_prompt)",
        start,
    )
    return source[start:end]


def test_video_prompt_handler_reserves_charge_before_provider_call() -> None:
    handler = _video_prompt_handler_source()
    reserve = "await reserve_video_prompt_charge(message.from_user.id)"
    provider = "await video_prompt_service.analyze_video("

    assert reserve in handler
    assert provider in handler
    assert handler.index(reserve) < handler.index(provider)
    assert "except VideoPromptInsufficientBalance as e:" in handler
    assert "await refund_video_prompt_charge(charge)" in handler


def test_video_prompt_cost_uses_configured_service_price(mocker) -> None:
    mocker.patch(
        "bot.services.video_prompt_billing.preset_manager.get_video_prompt_cost",
        return_value=3.0,
    )

    assert video_prompt_cost_credits() == 3.0


@pytest.mark.asyncio
async def test_video_prompt_charge_deducts_configured_cost(mocker) -> None:
    mocker.patch("bot.services.video_prompt_billing.config.is_admin", return_value=False)
    mocker.patch(
        "bot.services.video_prompt_billing.preset_manager.get_video_prompt_cost",
        return_value=3.0,
    )
    get_user = mocker.patch(
        "bot.services.video_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(
            side_effect=[mocker.Mock(credits=10.0), mocker.Mock(credits=7.0)]
        ),
    )
    deduct = mocker.patch(
        "bot.services.video_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(return_value=True),
    )

    charge = await reserve_video_prompt_charge(123)

    assert charge.charged is True
    assert charge.cost_credits == 3.0
    assert charge.balance_after == 7.0
    deduct.assert_awaited_once_with(123, 3.0)
    assert get_user.await_count == 2


@pytest.mark.asyncio
async def test_video_prompt_charge_rejects_insufficient_balance(mocker) -> None:
    mocker.patch("bot.services.video_prompt_billing.config.is_admin", return_value=False)
    mocker.patch(
        "bot.services.video_prompt_billing.preset_manager.get_video_prompt_cost",
        return_value=3.0,
    )
    mocker.patch(
        "bot.services.video_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=2.9)),
    )
    deduct = mocker.patch(
        "bot.services.video_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(),
    )

    with pytest.raises(VideoPromptInsufficientBalance) as error:
        await reserve_video_prompt_charge(123)

    assert error.value.cost_credits == 3.0
    assert error.value.balance == 2.9
    deduct.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_prompt_refund_returns_exact_reserved_amount(mocker) -> None:
    add = mocker.patch(
        "bot.services.video_prompt_billing.add_credits",
        new=mocker.AsyncMock(return_value=True),
    )
    mocker.patch(
        "bot.services.video_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=10.0)),
    )
    charge = VideoPromptCharge(
        telegram_id=123,
        cost_credits=3.0,
        charged=True,
        balance_after=7.0,
    )

    balance = await refund_video_prompt_charge(charge)

    assert balance == 10.0
    add.assert_awaited_once_with(123, 3.0)


@pytest.mark.asyncio
async def test_video_prompt_admin_is_not_charged(mocker) -> None:
    mocker.patch("bot.services.video_prompt_billing.config.is_admin", return_value=True)
    mocker.patch(
        "bot.services.video_prompt_billing.preset_manager.get_video_prompt_cost",
        return_value=3.0,
    )
    mocker.patch(
        "bot.services.video_prompt_billing.get_or_create_user",
        new=mocker.AsyncMock(return_value=mocker.Mock(credits=10.0)),
    )
    deduct = mocker.patch(
        "bot.services.video_prompt_billing.deduct_credits",
        new=mocker.AsyncMock(),
    )

    charge = await reserve_video_prompt_charge(123)

    assert charge.charged is False
    assert charge.cost_credits == 3.0
    assert charge.balance_after == 10.0
    deduct.assert_not_awaited()
