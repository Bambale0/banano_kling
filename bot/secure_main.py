from __future__ import annotations

import asyncio

import bot.main as legacy_main
from bot.services.telegram_webhook_runtime import install_into

install_into(legacy_main)


if __name__ == "__main__":
    asyncio.run(legacy_main.main())
