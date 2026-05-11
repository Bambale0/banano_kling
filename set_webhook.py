#!/usr/bin/env python3
"""
Скрипт для установки/удаления/проверки вебхука Telegram бота
"""

import asyncio
import os
import sys

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


async def get_webhook_info(bot: Bot):
    """Получить информацию о текущем вебхуке"""
    info = await bot.get_webhook_info()
    print("\n" + "=" * 60)
    print("📋 ИНФОРМАЦИЯ О ВЕБХУКЕ")
    print("=" * 60)
    print(f"🔗 URL: {info.url or '❌ Не установлен'}")
    print(f"📁 IP адрес: {info.ip_address or 'N/A'}")
    print(f"⏱ Последняя ошибка: {info.last_error_date or 'Нет'}")
    print(f"❌ Сообщение об ошибке: {info.last_error_message or 'Нет'}")
    print(f"📊 Макс. подключений: {info.max_connections}")
    print(f"📋 Ожидает обновлений: {info.pending_update_count}")
    print("=" * 60 + "\n")
    return info


async def set_webhook(
    bot: Bot, webhook_url: str, secret_token: str = None, ip_address: str = None
):
    """Установить вебхук"""
    print(f"\n🚀 Установка вебхука: {webhook_url}")

    try:
        kwargs = {"url": webhook_url, "drop_pending_updates": True}
        if secret_token:
            kwargs["secret_token"] = secret_token
        if ip_address:
            kwargs["ip_address"] = ip_address
        await bot.set_webhook(**kwargs)
        print("✅ Вебхук успешно установлен!\n")
        return True
    except Exception as e:
        print(f"❌ Ошибка установки вебхука: {e}\n")
        return False


async def delete_webhook(bot: Bot):
    """Удалить вебхук"""
    print("\n🗑 Удаление вебхука...")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Вебхук успешно удален!\n")
        return True
    except Exception as e:
        print(f"❌ Ошибка удаления вебхука: {e}\n")
        return False


async def main():
    """Главная функция"""
    # Получаем токен из переменных окружения
    bot_token = os.getenv("BOT_TOKEN")
    webhook_host = os.getenv("WEBHOOK_HOST")
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook")
    webhook_ip = os.getenv("WEBHOOK_IP")

    if not bot_token:
        print("❌ Ошибка: BOT_TOKEN не найден в .env")
        return

    # Создаем бота
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    print("\n" + "=" * 60)
    print("🤖 Telegram Bot Webhook Manager")
    print("=" * 60)

    # Показываем текущую конфигурацию
    print(f"\n📊 Конфигурация:")
    print(f"   • BOT_TOKEN: {'*' * 10}{bot_token[-5:]}")
    print(f"   • WEBHOOK_HOST: {webhook_host or '❌ Не задан'}")
    print(f"   • WEBHOOK_PATH: {webhook_path}")
    print(f"   • WEBHOOK_IP: {webhook_ip or 'не задан'}")

    # Показываем текущий статус
    await get_webhook_info(bot)

    # Меню действий
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
    else:
        print("📋 Доступные команды:")
        print("   1. python set_webhook.py info     - Показать информацию")
        print("   2. python set_webhook.py set      - Установить вебхук")
        print("   3. python set_webhook.py delete   - Удалить вебхук")
        print("   4. python set_webhook.py poll     - Переключить на polling")
        print()
        action = (
            input("Выберите действие (1/2/3/4 или info/set/delete/poll): ")
            .strip()
            .lower()
        )

    if action in ["2", "set"]:
        if not webhook_host:
            print("❌ Ошибка: WEBHOOK_HOST не задан в .env")
            print("   Пример: WEBHOOK_HOST=https://your-domain.com")
            return

        webhook_url = f"{webhook_host.rstrip('/')}{webhook_path}"
        secret_token = os.getenv("WEBHOOK_SECRET_TOKEN")

        await set_webhook(bot, webhook_url, secret_token, webhook_ip)
        await get_webhook_info(bot)

    elif action in ["3", "delete"]:
        await delete_webhook(bot)
        await get_webhook_info(bot)

    elif action in ["4", "poll"]:
        await delete_webhook(bot)
        print("✅ Вебхук удален. Бот теперь работает в режиме polling.")

    elif action in ["1", "info"]:
        # Информация уже показана
        pass

    else:
        print("❌ Неизвестная команда")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
