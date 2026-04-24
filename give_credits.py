#!/usr/bin/env python3
"""
Скрипт для начисления кредитов пользователю по Telegram ID
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.database import add_credits, get_or_create_user


async def give_credits(telegram_id: int, amount: int):
    """Начисляет кредиты пользователю по Telegram ID"""
    try:
        user = await get_or_create_user(telegram_id)
        old_balance = user.credits

        success = await add_credits(telegram_id, amount)

        user = await get_or_create_user(telegram_id)
        new_balance = user.credits

        print(f"✅ Пользователь: {telegram_id}")
        print(f"   Баланс до: {old_balance}")
        print(f"   Начислено: {amount}")
        print(f"   Баланс после: {new_balance}")
        print(f"   Успешно: {success}")

        return True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python give_credits.py <telegram_id> <amount>")
        print("Пример: python give_credits.py 8166443943 100")
        sys.exit(1)

    telegram_id = int(sys.argv[1])
    amount = int(sys.argv[2])

    asyncio.run(give_credits(telegram_id, amount))
