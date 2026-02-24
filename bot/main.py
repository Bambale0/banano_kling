import asyncio
import logging
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    start_router,
    settings_router,
    image_generation_router,
    image_editing_router,
    video_generation_router,
)
from bot.handlers.payments import handle_tbank_webhook
from bot.services.preset_manager import preset_manager

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
    logger.info("Bot starting...")
    await init_db()
    logger.info("Database initialized")
    if config.WEBHOOK_HOST:
        await bot.set_webhook(config.webhook_url)
        logger.info(f"Webhook set to {config.webhook_url}")
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")


async def on_shutdown(bot: Bot):
    logger.info("Bot shutting down...")
    await bot.delete_webhook()


def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # ⭐ Новые упрощённые обработчики (для нового UX) - должны быть первыми
    dp.include_router(image_generation_router)
    dp.include_router(image_editing_router)
    dp.include_router(video_generation_router)
    dp.include_router(settings_router)
    dp.include_router(start_router)
    
    # ⭐ Старые обработчики (с пресетами)
    dp.include_router(generation_router)
    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(batch_generation_router)
    dp.include_router(common_router)

    return dp


async def handle_telegram_webhook(request: web.Request, bot: Bot, dp: Dispatcher) -> web.Response:
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_webhook_update(bot, update)
        return web.Response(text="OK", status=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return web.Response(text="Internal Server Error", status=500)


async def handle_kling_webhook(request: web.Request) -> web.Response:
    try:
        logger.info(f"Kling webhook headers: {dict(request.headers)}")
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

        task_id = data.get("task_id")
        status = data.get("status")

        if status == "COMPLETED":
            generated = data.get("generated", [])
            
            if not generated:
                logger.error(f"No generated videos in completed task: {data}")
                return web.Response(status=200)
            
            video_url = generated[0].strip() if isinstance(generated[0], str) else None
            
            if not video_url:
                logger.error(f"Invalid video URL in generated array: {generated}")
                return web.Response(status=200)
            
            logger.info(f"Extracted video URL: {video_url[:50]}...")

            from bot.database import complete_video_task, get_task_by_id

            task = await get_task_by_id(task_id)
            
            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return web.Response(status=200)
            
            logger.info(f"Found task for user {task.user_id}, preset: {task.preset_id}")
            
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                await bot_instance.send_video(
                    chat_id=task.user_id,
                    video=video_url,
                    caption=f"✅ <b>Ваше видео готово!</b>\n\n🎯 Пресет: {task.preset_id}",
                    parse_mode="HTML",
                    supports_streaming=True,
                )

                await complete_video_task(task_id, video_url)
                logger.info(f"Video sent to user {task.user_id}")
            except Exception as e:
                logger.error(f"Failed to send video: {e}")
                try:
                    await bot_instance.send_message(
                        chat_id=task.user_id,
                        text=f"🎬 Ваше видео готово!\n\n{video_url}"
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        return web.Response(status=500)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    app = web.Application()

    async def telegram_webhook_handler(request: web.Request) -> web.Response:
        return await handle_telegram_webhook(request, bot, dp)

    app.router.add_post(config.WEBHOOK_PATH, telegram_webhook_handler)
    app.router.add_post("/tbank/webhook", handle_tbank_webhook)
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="OK")

    app.router.add_get("/health", health_check)

    return app


async def main():
    os.makedirs("logs", exist_ok=True)

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set! Please set the BOT_TOKEN environment variable.")
        sys.exit(1)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = setup_dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.WEBHOOK_HOST:
        logger.info("Starting in webhook mode...")
        app = setup_web_server(dp, bot)
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", config.WEBHOOK_PORT)
        await site.start()

        logger.info(f"Server started on port {config.WEBHOOK_PORT}")
        await asyncio.Event().wait()
    else:
        logger.info("Starting in polling mode...")
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
