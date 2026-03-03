#!/usr/bin/env python3
"""
Скрипт для проверки баланса пользователя по Telegram ID
"""

import asyncio
import sys
import os

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.database import get_or_create_user, get_user_stats

async def check_balance(telegram_id: int):
    """Проверяет баланс пользователя по Telegram ID"""
    try:
        # Получаем пользователя (создаётся если не существует)
        user = await get_or_create_user(telegram_id)
        
        # Получаем статистику пользователя
        stats = await get_user_stats(telegram_id)
        
        print(f"📊 Информация о пользователе {telegram_id}:")
        print(f"   Telegram ID: {user.telegram_id}")
        print(f"   Баланс: {stats['credits']} бананов")
        print(f"   Всего генераций: {stats['generations']}")
        print(f"   Потрачено бананов: {stats['total_spent']}")
        print(f"   Дата регистрации: {stats['member_since']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при проверке баланса: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python check_balance.py <telegram_id>")
        print("Пример: python check_balance.py 708343476")
        sys.exit(1)
    
    try:
        telegram_id = int(sys.argv[1])
    except ValueError:
        print("❌ Неверный формат Telegram ID. Ожидается число.")
        sys.exit(1)
    
    print(f"🔍 Проверка баланса для пользователя {telegram_id}...")
    asyncio.run(check_balance(telegram_id))