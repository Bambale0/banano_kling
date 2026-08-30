"""Disable referral antifraud enforcement for the Tanya production runtime.

The legacy referral flow still contains blocklist, hourly/daily throttles and a
burst auto-ban. Product policy currently requires those checks to be disabled.
Keep this as an explicit compatibility layer so the old implementation can stay
intact while production behavior is unambiguous and reversible.
"""

from __future__ import annotations

from bot import database

# Effectively unreachable for a real referral table while still preserving the
# legacy comparison code paths without editing the large database module.
_DISABLED_LIMIT = (2**63) - 1


def disable_referral_antifraud() -> None:
    """Turn off referral blocklists, rate limits and burst auto-bans."""

    database.REFERRAL_ANTIFRAUD_MAX_PER_HOUR = _DISABLED_LIMIT
    database.REFERRAL_ANTIFRAUD_MAX_PER_DAY = _DISABLED_LIMIT
    database.REFERRAL_ANTIFRAUD_BURST_WINDOW_SECONDS = 0
    database.REFERRAL_ANTIFRAUD_BURST_MAX = 0

    # Mutate the existing sets in place so any module that imported a reference
    # to them before this hook runs observes the disabled state too.
    database.REFERRAL_ANTIFRAUD_BLOCK_CODES.clear()
    database.REFERRAL_ANTIFRAUD_BLOCK_REFERRER_IDS.clear()
