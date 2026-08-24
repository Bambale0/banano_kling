"""Regression tests for payer-facing payment success notices."""

from pathlib import Path


PAYMENTS_SOURCE = Path("bot/handlers/payments.py")


def test_partner_commission_is_not_rendered_as_payer_bonus():
    """Partner RUB commission belongs to referrers, not the buyer receipt."""
    source = PAYMENTS_SOURCE.read_text(encoding="utf-8")

    assert "Партнёрский бонус" not in source
    assert "Partner commission is an internal/referrer-facing accrual" in source
    assert 'if referral_bonus.get("mode") == "partner":' in source
    assert 'return ""' in source


def test_banana_referral_bonus_still_renders_for_payer():
    source = PAYMENTS_SOURCE.read_text(encoding="utf-8")

    assert "Реферальный бонус" in source
    assert "бананов" in source
