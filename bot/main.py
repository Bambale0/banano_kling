import asyncio
import logging
import sys
import os
import json

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Загружаем переменные из .env файла
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiohttp import web
from bot.config import config
from bot.database import init_db
from bot.handlers import (
    admin_router,
    batch_generation_router,
    common_router,
    generation_router,
    payments_router,
)
from bot.handlers.payments import handle_tbank_webhook
from bot.services.preset_manager import preset_manager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Действия при старте бота"""
    logger.info("Bot starting...")

    # Инициализируем базу данных
    await init_db()
    logger.info("Database initialized")

    # Устанавливаем вебхук для Telegram (если используем webhook mode)
    if config.WEBHOOK_HOST:
        await bot.set_webhook(config.webhook_url)
        logger.info(f"Webhook set to {config.webhook_url}")

    # Загружаем пресеты
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Bot shutting down...")
    await bot.delete_webhook()


def setup_dispatcher() -> Dispatcher:
    """Настройка диспетчера с роутерами"""
    dp = Dispatcher()

    # ⭐ КРИТИЧЕСКИ ВАЖНО: Порядок роутеров в aiogram 3.x
    # Первый зарегистрированный роутер имеет НАИВЫСШИЙ приоритет!
    # Сообщение передаётся ВСЕМ роутерам одновременно, но обрабатывается
    # тем, у кого более специфичный фильтр (например, StateFilter)
    #
    # Правильный порядок:
    # 1. generation_router (FSM состояния - самые специфичные)
    # 2. admin_router (админ команды)
    # 3. payments_router (платежи)
    # 4. batch_generation_router (пакетная генерация)
    # 5. common_router (общие команды /start /help - самые общие)
    
    dp.include_router(generation_router)  # FSM состояния - ПЕРВЫЙ!
    dp.include_router(admin_router)       # Админ-команды
    dp.include_router(payments_router)    # Платежи
    dp.include_router(batch_generation_router)  # Пакетная генерация
    dp.include_router(common_router)      # Общие команды - ПОСЛЕДНИЙ!

    return dp


async def handle_telegram_webhook(request: web.Request, bot: Bot, dp: Dispatcher) -> web.Response:
    """Обработчик вебхука от Telegram"""
    try:
        # Получаем данные из запроса
        update_data = await request.json()
        
        # Создаём объект Update
        update = Update(**update_data)
        
        # Обрабатываем обновление через диспетчер
        await dp.feed_webhook_update(bot, update)
        
        return web.Response(text="OK", status=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return web.Response(text="Internal Server Error", status=500)


async def handle_kling_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kling API"""
    try:
        data = await request.json()
        logger.info(f"Kling webhook: {data}")

        # Обработка завершения генерации видео
        task_id = data.get("task_id")
        status = data.get("status")

        if status == "COMPLETED":
            # Получаем URL видео
            video_url = data.get("result", {}).get("video_url")

            # Находим задачу в БД
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)
            if task:
                # Отправляем видео пользователю
                bot_instance = Bot(token=config.BOT_TOKEN)

                try:
                    await bot_instance.send_video(
                        chat_id=task.user_id,
                        video=video_url,
                        caption=f"✅ <b>Ваше видео готово!</b>\n\n"
                        f"🎯 Пресет: {task.preset_id}",
                        parse_mode="HTML",
                    )

                    await complete_video_task(task_id, video_url)
                    logger.info(f"Video sent to user {task.user_id}")
                except Exception as e:
                    logger.error(f"Failed to send video: {e}")
                finally:
                    await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        return web.Response(status=500)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""
    app = web.Application()

    # Вебхук Telegram
    async def telegram_webhook_handler(request: web.Request) -> web.Response:
        return await handle_telegram_webhook(request, bot, dp)

    app.router.add_post(config.WEBHOOK_PATH, telegram_webhook_handler)

    # Вебхук Т-Банка
    app.router.add_post("/tbank/webhook", handle_tbank_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Health check endpoint
    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/health", health_check)

    return app


async def main():
    """Главная функция"""
    # Создаём директорию для логов если её нет
    os.makedirs("logs", exist_ok=True)

    # Проверяем наличие токена
    if not config.BOT_TOKEN:
        logger.error(
            "BOT_TOKEN is not set! Please set the BOT_TOKEN environment variable."
        )
        sys.exit(1)

    # Создаём бота
    bot = Bot(
        token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Настраиваем диспатчер
    dp = setup_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.WEBHOOK_HOST:
        # Webhook mode (для production)
        logger.info("Starting in webhook mode...")
        app = setup_web_server(dp, bot)
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", config.WEBHOOK_PORT)
        await site.start()

        logger.info(f"Server started on port {config.WEBHOOK_PORT}")

        # Держим бота запущенным
        await asyncio.Event().wait()
    else:
        # Polling mode (для разработки)
        logger.info("Starting in polling mode...")
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
