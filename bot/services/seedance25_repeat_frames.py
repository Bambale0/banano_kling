"""Time-limited operator setting for Seedance 2.5 Mini App feed repeats."""

import logging
from time import time

from bot import database

logger = logging.getLogger(__name__)
SETTING_KEY = "seedance25_repeat_optional_frames_until"


async def optional_repeat_frames_until() -> int:
    try:
        until = int(await database.get_bot_setting(SETTING_KEY, "0") or "0")
    except (TypeError, ValueError):
        return 0
    except Exception as exc:  # noqa: BLE001 -- a settings outage keeps validation enabled
        logger.warning("Seedance optional repeat frames setting unavailable: error_type=%s", type(exc).__name__)
        return 0
    return until if until > time() else 0
