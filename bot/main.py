import asyncio
import json
import logging
import os
import sys
import time

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Загружаем переменные из .env файла
from dotenv import load_dotenv

load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
)

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
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


async def _remove_old_files(
    base_dir: str = "static/uploads", max_age_seconds: int = 6 * 3600
):
    """Удаляет файлы старше max_age_seconds в каталоге base_dir (рекурсивно)."""
    try:
        now = time.time()
        if not os.path.exists(base_dir):
            return

        for root, dirs, files in os.walk(base_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                    if now - mtime > max_age_seconds:
                        os.remove(path)
                        logger.info(f"Removed old file: {path}")
                except Exception:
                    logger.exception(f"Failed to remove file: {path}")

            # После обработки файлов: если папка пуста — удаляем её
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    logger.info(f"Removed empty dir: {root}")
            except Exception:
                # Игнорируем ошибки удаления каталогов
                pass
    except Exception:
        logger.exception("Error during static cleanup")


async def _static_cleanup_loop():
    """Фоновая задача, очищающая static/uploads каждые 6 часов."""
    while True:
        try:
            await _remove_old_files("static/uploads", max_age_seconds=6 * 3600)
        except Exception:
            logger.exception("Cleanup iteration failed")
        await asyncio.sleep(6 * 3600)


async def on_startup(bot: Bot):
    """Действия при старте бота"""
    logger.info("Bot starting...")

    # База данных уже инициализирована в main() функции
    logger.info("Database already initialized")

    # Устанавливаем вебхук для Telegram (если используем webhook mode)
    if config.WEBHOOK_HOST:
        await bot.set_webhook(config.webhook_url)
        logger.info(f"Webhook set to {config.webhook_url}")

    # Загружаем пресеты
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")
    # Запускаем задачу очистки static/uploads каждые 6 часов
    try:
        bot.loop.create_task(_static_cleanup_loop())
        logger.info("Scheduled static/uploads cleanup task (every 6 hours)")
    except Exception:
        logger.exception("Failed to schedule static cleanup task")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Bot shutting down...")
    await bot.delete_webhook()


async def errors_handler(event: types.ErrorEvent):
    """Глобальный обработчик ошибок"""
    error = event.exception

    # Обработка ошибок Telegram API
    if isinstance(error, TelegramBadRequest):
        error_msg = str(error).lower()
        if "chat not found" in error_msg:
            logger.warning(
                f"Chat not found error (user deleted chat or blocked bot): {error}"
            )
            return True
        elif "bot was blocked" in error_msg:
            logger.warning(f"Bot was blocked by user: {error}")
            return True
        elif "user is deactivated" in error_msg:
            logger.warning(f"User is deactivated: {error}")
            return True
        elif "message is not modified" in error_msg:
            # Игнорируем ошибку "message is not modified"
            return True

    # Логируем другие ошибки
    logger.exception(f"Unhandled error: {error}")
    return True


def setup_dispatcher() -> Dispatcher:
    """Настройка диспетчера с роутерами"""
    dp = Dispatcher()

    # Регистрируем глобальный обработчик ошибок
    dp.errors.register(errors_handler)

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
    dp.include_router(admin_router)  # Админ-команды
    dp.include_router(payments_router)  # Платежи
    dp.include_router(batch_generation_router)  # Пакетная генерация
    dp.include_router(common_router)  # Общие команды - ПОСЛЕДНИЙ!

    return dp


async def handle_telegram_webhook(
    request: web.Request, bot: Bot, dp: Dispatcher
) -> web.Response:
    """Обработчик вебхука от Telegram"""
    try:
        # Получаем данные из запроса
        update_data = await request.json()

        # Создаём объект Update
        update = Update(**update_data)

        # Обрабатываем обновление через диспетчер
        await dp.feed_webhook_update(bot, update)

        return web.Response(text="OK", status=200)
    except TelegramBadRequest as e:
        # Ошибки Telegram API (chat not found, user blocked bot, etc.)
        # Возвращаем 200, чтобы Telegram не повторял запрос
        error_msg = str(e).lower()
        if (
            "chat not found" in error_msg
            or "bot was blocked" in error_msg
            or "user is deactivated" in error_msg
        ):
            logger.warning(f"Chat error (safe to ignore): {e}")
            return web.Response(text="OK", status=200)
        logger.exception(f"Telegram API error: {e}")
        return web.Response(text="Bad Request", status=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        # Возвращаем 200 даже при ошибках, чтобы Telegram не спамил
        return web.Response(text="OK", status=200)


async def handle_kling_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kling API"""
    try:
        # Логируем все заголовки для отладки
        logger.info(f"Kling webhook headers: {dict(request.headers)}")

        # Проверяем, есть ли данные в теле запроса
        body = await request.text()
        logger.info(f"Kling webhook raw body: {repr(body)}")

        if not body:
            logger.warning("Kling webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Kling webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Kling webhook parsed data: {data}")

        # Обработка завершения генерации видео
        task_id = data.get("task_id")
        status = data.get("status")

        if status == "COMPLETED":
            # Получаем URL видео из массива generated
            # Webhook возвращает: {"status": "COMPLETED", "task_id": "...", "generated": ["https://..."]}
            generated = data.get("generated", [])

            if not generated:
                logger.error(f"No generated videos in completed task: {data}")
                return web.Response(status=200)

            # ✅ Правильно: берем первый URL из массива и убираем пробелы
            video_url = generated[0].strip() if isinstance(generated[0], str) else None

            if not video_url:
                logger.error(f"Invalid video URL in generated array: {generated}")
                return web.Response(status=200)

            logger.info(f"Extracted video URL: {video_url[:50]}...")

            # Находим задачу в БД
            from bot.database import (
                complete_video_task,
                get_task_by_id,
                get_telegram_id_by_user_id,
            )

            task = await get_task_by_id(task_id)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            # Получаем Telegram ID пользователя по internal user_id
            telegram_id = await get_telegram_id_by_user_id(task.user_id)

            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            # Отправляем видео пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                from bot.keyboards import get_video_result_keyboard

                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=f"✅ <b>Ваше видео готово!</b>\n\n"
                    f"🎯 Пресет: {task.preset_id}",
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=get_video_result_keyboard(video_url),
                )

                await complete_video_task(task_id, video_url)
                logger.info(f"Video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send video: {e}")
                # Fallback — отправляем как ссылку
                try:
                    from bot.keyboards import get_video_result_keyboard

                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🎬 Ваше видео готово!\n\n{video_url}",
                        reply_markup=get_video_result_keyboard(video_url),
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        return web.Response(status=500)


async def handle_seedream_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (Seedream) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info(f"Seedream webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"Seedream webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("Seedream webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Seedream webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Seedream webhook parsed data: {data}")

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Seedream webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Seedream task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            # Получаем Telegram ID пользователя
            from bot.database import get_telegram_id_by_user_id

            telegram_id = await get_telegram_id_by_user_id(task.user_id)

            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=image_url,
                    caption=f"✅ <b>Ваше изображение готово!</b>\n\n"
                    f"🎯 Пресет: {task.preset_id}",
                    parse_mode="HTML",
                )

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение готово!\n\n{image_url}",
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Seedream task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Seedream webhook error: {e}")
        return web.Response(status=500)


async def handle_novita_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Novita AI (FLUX.2 Pro) API

    Novita AI webhook format (ASYNC_TASK_RESULT event):
    {
        "event_type": "ASYNC_TASK_RESULT",
        "payload": {
            "task": {
                "task_id": "...",
                "status": "TASK_STATUS_SUCCEED",
                "task_type": "TXT_TO_IMG"
            },
            "images": [{"image_url": "https://..."}],
            "extra": {...}
        }
    }
    """
    try:
        logger.info(f"Novita FLUX webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"Novita FLUX webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("Novita FLUX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Novita FLUX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Novita FLUX webhook parsed data: {data}")

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        if event_type != "ASYNC_TASK_RESULT":
            logger.warning(f"Unexpected event_type: {event_type}, ignoring")
            return web.Response(status=200)

        # Get payload
        payload = data.get("payload", {})

        # Get task info from payload.task
        task_info = payload.get("task", {})
        task_id = task_info.get("task_id")
        status = task_info.get("status")

        if not task_id:
            logger.warning(f"No task_id in Novita FLUX webhook: {data}")
            return web.Response(status=200)

        logger.info(f"Novita FLUX task {task_id} status: {status}")

        # Novita AI status: TASK_STATUS_SUCCEED, TASK_STATUS_FAILED
        if status == "TASK_STATUS_SUCCEED":
            # Get images from payload.images array
            images = payload.get("images", [])

            if not images:
                logger.error(f"No images in completed task: {data}")
                return web.Response(status=200)

            # Novita returns images as objects with image_url field
            image_url = None
            if isinstance(images[0], dict):
                image_url = images[0].get("image_url")
            elif isinstance(images[0], str):
                image_url = images[0]

            if not image_url:
                logger.error(f"Invalid images format: {images}")
                return web.Response(status=200)

            logger.info(f"Extracted image URL: {image_url[:50]}...")

            # Находим задачу в БД по task_id
            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)

            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)

            # Получаем Telegram ID пользователя
            from bot.database import get_telegram_id_by_user_id

            telegram_id = await get_telegram_id_by_user_id(task.user_id)

            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=image_url,
                    caption=f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>\n\n"
                    f"🎯 Пресет: {task.preset_id}",
                    parse_mode="HTML",
                )

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение (FLUX.2 Pro) готово!\n\n{image_url}",
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        elif status == "TASK_STATUS_FAILED":
            reason = task_info.get("reason", "Unknown error")
            logger.error(f"Novita FLUX task {task_id} failed: {reason}")

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Novita FLUX webhook error: {e}")
        return web.Response(status=500)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""
    app = web.Application()

    # Serve static uploads directory to fix 404 errors for Novita image downloads
    app.router.add_static(
        "/uploads/", path="static/uploads", show_index=False, name="uploads"
    )

    # Вебхук Telegram
    async def telegram_webhook_handler(request: web.Request) -> web.Response:
        return await handle_telegram_webhook(request, bot, dp)

    app.router.add_post(config.WEBHOOK_PATH, telegram_webhook_handler)

    # Вебхук Т-Банка
    app.router.add_post("/tbank/webhook", handle_tbank_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Seedream (Novita AI)
    app.router.add_post("/webhook/seedream", handle_seedream_webhook)

    # Вебхук Novita FLUX.2 Pro
    app.router.add_post("/webhook/novita", handle_novita_webhook)

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

    # Инициализируем базу данных ДО создания бота
    logger.info("Initializing database before bot startup...")
    await init_db()
    logger.info("Database initialized successfully")

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
