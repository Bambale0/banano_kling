#!/usr/bin/env python3
"""
Ручное добавление реферала: прикрепляет пользователя к référel-коду.
Запуск:
  python add_referral.py <telegram_id> <referral_code>
  python add_referral.py 6983566051 VADK5DTE
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.database import process_referral


async def main():
    if len(sys.argv) != 3:
        print("Использование: python add_referral.py <telegram_id> <referral_code>")
        sys.exit(1)

    telegram_id = int(sys.argv[1])
    referral_code = str(sys.argv[2]).strip().upper()

    result = await process_referral(telegram_id, referral_code)
    if result:
        print(
            f"✅ Готово: пользователь {telegram_id} прикреплён к рефералу {referral_code}."
        )
    else:
        print(
            "❌ Не удалось добавить реферал. "
            "Проверьте, что код существует, пользователь ещё не зарегистрирован "
            "и не имеет другого пригласителя, а также не оплачивал ранее."
        )


if __name__ == "__main__":
    asyncio.run(main())