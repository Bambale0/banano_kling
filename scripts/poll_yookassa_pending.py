#!/usr/bin/env python3
"""Simple CLI to poll pending YooKassa transactions and reconcile them.

Usage: python3 scripts/poll_yookassa_pending.py
"""

import asyncio
import logging

from bot.services.yookassa_service import yookassa_service

logging.basicConfig(level=logging.INFO)


async def main():
    results = await yookassa_service.poll_pending_transactions()
    print("Reconcile results:")
    for r in results:
        print(r)


if __name__ == "__main__":
    asyncio.run(main())
