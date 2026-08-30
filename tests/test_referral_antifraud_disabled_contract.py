from __future__ import annotations

from pathlib import Path

from bot import database
from bot.services.referral_antifraud_disabled import disable_referral_antifraud


def test_disable_referral_antifraud_removes_all_enforcement() -> None:
    original = (
        database.REFERRAL_ANTIFRAUD_MAX_PER_HOUR,
        database.REFERRAL_ANTIFRAUD_MAX_PER_DAY,
        database.REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
        database.REFERRAL_ANTIFRAUD_BURST_MAX,
        set(database.REFERRAL_ANTIFRAUD_BLOCK_CODES),
        set(database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS),
    )

    try:
        database.REFERRAL_ANTIFRAUD_MAX_PER_HOUR = 1
        database.REFERRAL_ANTIFRAUD_MAX_PER_DAY = 2
        database.REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS = 10
        database.REFERRAL_ANTIFRAUD_BURST_MAX = 3
        database.REFERRAL_ANTIFRAUD_BLOCK_CODES.clear()
        database.REFERRAL_ANTIFRAUD_BLOCK_CODES.add("BLOCKED")
        database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS.clear()
        database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS.add(123)

        disable_referral_antifraud()

        assert database.REFERRAL_ANTIFRAUD_MAX_PER_HOUR > 1_000_000_000
        assert database.REFERRAL_ANTIFRAUD_MAX_PER_DAY > 1_000_000_000
        assert database.REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS == 0
        assert database.REFERRAL_ANTIFRAUD_BURST_MAX == 0
        assert database.REFERRAL_ANTIFRAUD_BLOCK_CODES == set()
        assert database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS == set()
    finally:
        (
            database.REFERRAL_ANTIFRAUD_MAX_PER_HOUR,
            database.REFERRAL_ANTIFRAUD_MAX_PER_DAY,
            database.REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS,
            database.REFERRAL_ANTIFRAUD_BURST_MAX,
            block_codes,
            block_referrers,
        ) = original
        database.REFERRAL_ANTIFRAUD_BLOCK_CODES.clear()
        database.REFERRAL_ANTIFRAUD_BLOCK_CODES.update(block_codes)
        database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS.clear()
        database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS.update(block_referrers)


def test_disabled_antifraud_is_installed_before_user_handlers() -> None:
    source = Path("bot/handlers/__init__.py").read_text(encoding="utf-8")

    assert "disable_referral_antifraud" in source
    assert source.index("disable_referral_antifraud()") < source.index(
        "from . import admin as admin_module"
    )
    assert source.index("disable_referral_antifraud()") < source.index(
        "from . import common as common_module"
    )
