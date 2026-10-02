from __future__ import annotations

from dataclasses import dataclass

from bot.config import config
from bot.database import add_credits, deduct_credits, get_or_create_user
from bot.services.preset_manager import preset_manager


@dataclass(frozen=True)
class VideoPromptCharge:
    telegram_id: int
    cost_credits: float
    charged: bool
    balance_after: float


class VideoPromptInsufficientBalance(ValueError):
    def __init__(self, *, balance: float, cost_credits: float):
        self.balance = round(float(balance), 4)
        self.cost_credits = round(float(cost_credits), 4)
        super().__init__(
            f"Недостаточно бананов. Стоимость: {self.cost_credits:g} 🍌, "
            f"баланс: {self.balance:g} 🍌."
        )


def video_prompt_cost_credits() -> float:
    return float(preset_manager.get_video_prompt_cost())


async def reserve_video_prompt_charge(telegram_id: int) -> VideoPromptCharge:
    cost_credits = video_prompt_cost_credits()
    user = await get_or_create_user(telegram_id)

    if config.is_admin(telegram_id):
        return VideoPromptCharge(
            telegram_id=telegram_id,
            cost_credits=cost_credits,
            charged=False,
            balance_after=round(float(user.credits), 4),
        )

    if float(user.credits) + 1e-9 < cost_credits:
        raise VideoPromptInsufficientBalance(
            balance=float(user.credits),
            cost_credits=cost_credits,
        )

    deducted = await deduct_credits(telegram_id, cost_credits)
    if not deducted:
        current = await get_or_create_user(telegram_id)
        raise VideoPromptInsufficientBalance(
            balance=float(current.credits),
            cost_credits=cost_credits,
        )

    current = await get_or_create_user(telegram_id)
    return VideoPromptCharge(
        telegram_id=telegram_id,
        cost_credits=cost_credits,
        charged=True,
        balance_after=round(float(current.credits), 4),
    )


async def refund_video_prompt_charge(
    charge: VideoPromptCharge | None,
) -> float | None:
    if charge is None:
        return None
    if charge.charged:
        await add_credits(charge.telegram_id, charge.cost_credits)
    current = await get_or_create_user(charge.telegram_id)
    return round(float(current.credits), 4)
