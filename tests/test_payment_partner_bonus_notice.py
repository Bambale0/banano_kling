"""Regression tests for payer-facing payment success notices."""

from __future__ import annotations

from bot.handlers.payments import _build_bonus_text


def test_partner_commission_is_not_rendered_as_payer_bonus() -> None:
    """Partner RUB commission belongs to referrers, not the buyer receipt."""
    text = _build_bonus_text({"mode": "partner", "value": 300.0})

    assert text == ""


def test_banana_referral_bonus_still_renders_for_payer() -> None:
    text = _build_bonus_text({"mode": "banana", "value": 5})

    assert "Реферальный бонус" in text
    assert "5" in text
    assert "бананов" in text
