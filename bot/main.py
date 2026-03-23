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
    image_analyzer_router,
    payments_router,
)
from bot.handlers.payments import handle_tbank_webhook, handle_yookassa_webhook
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
        # aiogram.Bot does not expose an event loop attribute in some versions.
        # Use asyncio.create_task to schedule background tasks on the running loop.
        asyncio.create_task(_static_cleanup_loop())
        logger.info(
            "Scheduled static/uploads cleanup task (every 6 hours) via asyncio.create_task"
        )
    except Exception:
        logger.exception("Failed to schedule static cleanup task")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Bot shutting down...")
    await bot.delete_webhook()
    await bot.session.close()


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
    dp.include_router(image_analyzer_router)  # Анализ фото в промпт
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
    """Обработчик уведомлений от Kling API (PiAPI)"""
    try:
        # Verify Replicate webhook signature if configured
        from bot.config import config as _config

        def _verify_replicate_signature(
            secret: str, body: bytes, headers: dict
        ) -> bool:
            """Verify HMAC SHA256 signature using common header names.

            Replicate may send signatures in a header such as:
            - 'x-replicate-signature'
            - 'x-signature'
            - 'replicate-signature'

            The header format may be 'sha256=HEX' or plain HEX. We try a few
            common variants. If secret is empty — verification is skipped.
            """
            if not secret:
                return True
            import hashlib
            import hmac

            body_bytes = (
                body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            )

            # Candidate headers to check. Some providers (Replicate/Runway)
            # may use different header names such as 'webhook-signature'.
            candidates = [
                headers.get("x-replicate-signature"),
                headers.get("x-signature"),
                headers.get("replicate-signature"),
                headers.get("signature"),
                headers.get("webhook-signature"),
            ]

            secret_bytes = secret.encode("utf-8")

            for sig in candidates:
                if not sig:
                    continue

                # Header may contain prefixes or comma-separated values like 'v1,<sig>'
                # or 'sha256=<hex>'. Normalize to the actual token part.
                sig_str = sig if isinstance(sig, str) else str(sig)
                # If comma-separated, take the last non-empty part
                parts = [p.strip() for p in sig_str.split(",") if p.strip()]
                sig_candidate = parts[-1]

                # Remove common scheme prefixes
                if sig_candidate.startswith("sha256="):
                    sig_val = sig_candidate.split("=", 1)[1]
                elif sig_candidate.startswith("v1="):
                    sig_val = sig_candidate.split("=", 1)[1]
                else:
                    sig_val = sig_candidate

                # Try hex comparison (common 'sha256=HEX' or plain HEX)
                try:
                    computed_hex = hmac.new(secret_bytes, body_bytes, hashlib.sha256).hexdigest()
                    if hmac.compare_digest(computed_hex, sig_val):
                        return True
                except Exception:
                    pass

                # Try base64 comparison (some gateways use base64-encoded signature)
                try:
                    import base64

                    computed_b64 = base64.b64encode(
                        hmac.new(secret_bytes, body_bytes, hashlib.sha256).digest()
                    ).decode()
                    # Compare with padding and without padding
                    if hmac.compare_digest(computed_b64, sig_val):
                        return True
                    if hmac.compare_digest(computed_b64.rstrip("="), sig_val.rstrip("=")):
                        return True
                except Exception:
                    pass
            return False

        # Read raw body for verification
        raw_body = await request.read()
        if not _verify_replicate_signature(
            _config.REPLICATE_WEBHOOK_SECRET, raw_body, dict(request.headers)
        ):
            logger.warning(
                "Rejected Kling webhook: replicate signature verification failed"
            )
            return web.Response(status=200)

        # Rewind body for normal processing: aiohttp request.text() uses internal stream
        # We'll load the JSON from raw_body below instead of calling request.text() twice.
        # Логируем все заголовки для отладки
        logger.info(f"Kling webhook headers: {dict(request.headers)}")

        # Проверяем, есть ли данные в теле запроса
        if not raw_body:
            logger.warning("Kling webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info(f"Kling webhook raw body: {repr(body_text)}")
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kling webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Kling webhook parsed data: {data}")

        # PiAPI / Replicate webhooks may arrive in slightly different shapes.
        # Use a recursive extractor so we can handle flat payloads, nested `data`
        # objects, or other vendor variants without losing the task id.
        def _extract_first(obj, keys):
            if isinstance(obj, dict):
                for key in keys:
                    value = obj.get(key)
                    if value not in (None, ""):
                        return value
                for value in obj.values():
                    found = _extract_first(value, keys)
                    if found not in (None, ""):
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = _extract_first(item, keys)
                    if found not in (None, ""):
                        return found
            return None

        webhook_data = data.get("data") if isinstance(data.get("data"), dict) else data
        task_id = _extract_first(
            webhook_data, ("task_id", "id", "prediction_id", "predictionId")
        )
        status = _extract_first(
            webhook_data, ("status", "state", "result", "prediction_status")
        )

        if not task_id:
            logger.error(
                f"Kling webhook missing task id. Top-level keys: {list(data.keys())}, payload: {webhook_data}"
            )
            return web.Response(status=200)

        logger.info(f"Processing Kling task {task_id} with status {status}")

        normalized_status = str(status).lower() if status else ""

        if normalized_status in {"completed", "succeeded", "success", "finished"}:
            # Replicate can return either a direct URL/string or a nested object.
            output = (
                webhook_data.get("output", {}) if isinstance(webhook_data, dict) else {}
            )
            video_url = (
                (output.get("video_url") if isinstance(output, dict) else None)
                or (output.get("video") if isinstance(output, dict) else None)
                or (output if isinstance(output, str) else None)
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                    if isinstance(output, dict)
                    else None
                )
            )

            if not video_url:
                logger.error(f"No video URL in completed task: {webhook_data}")
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

            # Determine caption based on preset
            if task.preset_id == "no_preset" and task.prompt:
                caption = f"✅ <b>Ваше видео готово!</b>\n\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption = f"✅ <b>Ваше видео готово!</b>\n\n🎯 Пресет: {task.preset_id}"

            # Отправляем видео пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                from bot.keyboards import get_video_result_keyboard

                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=caption,
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
                        parse_mode="HTML",
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send fallback message: {fallback_error}")
            finally:
                await bot_instance.session.close()
        else:
            logger.error(f"Kling task {task_id} failed with status: {status}")
            # Check for sensitive content error
            # webhook_data['error'] or webhook_data['logs'] may be dicts (or other types)
            # so convert them to strings safely before concatenation to avoid TypeError
            def _to_str(value):
                if value is None:
                    return ""
                if isinstance(value, (str, int, float)):
                    return str(value)
                try:
                    return json.dumps(value, ensure_ascii=False)
                except Exception:
                    return str(value)

            # Safely stringify possible dict/complex types in webhook error/logs
            error_msg = (
                _to_str(webhook_data.get("error"))
                + " "
                + _to_str(webhook_data.get("logs"))
            ).lower()
            if "sensitive" in error_msg or "e005" in error_msg:
                from bot.database import (
                    add_credits,
                    get_task_by_id,
                    get_telegram_id_by_user_id,
                )

                task = await get_task_by_id(task_id)
                if task:
                    telegram_id = await get_telegram_id_by_user_id(task.user_id)
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            # Try to get preset cost from preset manager (presets.json)
                            preset = preset_manager.get_preset(task.preset_id)
                            preset_cost = preset.cost if preset else 0
                            await add_credits(telegram_id, preset_cost)
                            await bot_instance.send_message(
                                chat_id=telegram_id,
                                text=(
                                    "❌ <b>Ваш промпт был помечен как чувствительный контент</b>\n\n"
                                    "Пожалуйста, попробуйте другой промпт без чувствительного контента.\n\n"
                                    "🍌 Кредиты возвращены на счёт."
                                ),
                                parse_mode="HTML",
                            )
                            logger.info(
                                f"Sent sensitive content notification to {telegram_id}, returned {preset_cost} credits"
                            )
                        except Exception as notify_error:
                            logger.error(
                                f"Failed to notify user about sensitive content: {notify_error}"
                            )
                        finally:
                            await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kling webhook error: {e}")
        # Return 200 even on unexpected errors to avoid webhook relayers
        # repeatedly retrying the same payload. The error is logged above
        # for investigation.
        return web.Response(status=200)


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

            # Determine caption based on preset
            if task.preset_id == "no_preset" and task.prompt:
                caption = f"✅ <b>Ваше изображение готово!</b>\n\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption = (
                    f"✅ <b>Ваше изображение готово!</b>\n\n🎯 Пресет: {task.preset_id}"
                )

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=image_url,
                    caption=caption,
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

            # Determine caption based on preset
            if task.preset_id == "no_preset" and task.prompt:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>\n\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption = f"✅ <b>Ваше изображение (FLUX.2 Pro) готово!</b>\n\n🎯 Пресет: {task.preset_id}"

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=image_url,
                    caption=caption,
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


async def handle_wanx_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от PiAPI WanX API"""
    try:
        logger.info(f"WanX webhook headers: {dict(request.headers)}")

        body = await request.text()
        logger.info(f"WanX webhook raw body: {repr(body)[:500]}")

        if not body:
            logger.warning("WanX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"WanX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"WanX webhook parsed data: {data}")

        webhook_data = data.get("data") or data.get("payload") or data
        task_id = webhook_data.get("task_id")
        status = webhook_data.get("status")

        if not task_id:
            logger.warning(f"No task_id in WanX webhook: {data}")
            return web.Response(status=200)

        normalized_status = str(status).lower() if status else ""
        logger.info(f"WanX task {task_id} status: {status}")

        if normalized_status in (
            "completed",
            "succeeded",
            "success",
            "task_status_succeed",
        ):
            output = webhook_data.get("output", {})
            video_url = (
                output.get("video_url")
                or output.get("video")
                or (
                    output.get("works")
                    and output["works"][0]
                    .get("video", {})
                    .get("resource_without_watermark")
                )
            )

            if not video_url:
                logger.error(f"No video URL in WanX completed task: {webhook_data}")
                return web.Response(status=200)

            from bot.database import (
                complete_video_task,
                get_task_by_id,
                get_telegram_id_by_user_id,
            )

            task = await get_task_by_id(task_id)
            if not task:
                logger.warning(f"WanX task {task_id} not found in database")
                return web.Response(status=200)

            telegram_id = await get_telegram_id_by_user_id(task.user_id)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            caption = (
                f"✅ <b>Ваше видео WanX готово!</b>\n\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if task.prompt and len(task.prompt) > 100 else ''}</code>"
                if task.preset_id == "no_preset" and task.prompt
                else f"✅ <b>Ваше видео WanX готово!</b>\n\n🎯 Пресет: {task.preset_id}"
            )

            bot_instance = Bot(token=config.BOT_TOKEN)
            try:
                from bot.keyboards import get_video_result_keyboard

                await bot_instance.send_video(
                    chat_id=telegram_id,
                    video=video_url,
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=get_video_result_keyboard(video_url),
                )
                await complete_video_task(task_id, video_url)
                logger.info(f"WanX video sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send WanX video: {e}")
                try:
                    from bot.keyboards import get_video_result_keyboard

                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🎬 Ваше видео WanX готово!\n\n{video_url}",
                        reply_markup=get_video_result_keyboard(video_url),
                        parse_mode="HTML",
                    )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send WanX fallback message: {fallback_error}"
                    )
            finally:
                await bot_instance.session.close()

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"WanX webhook error: {e}")
        return web.Response(status=500)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""
    app = web.Application()
    app["bot"] = bot

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

    # Вебхук YooKassa
    app.router.add_post("/yookassa/webhook", handle_yookassa_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Replicate (Runway)
    # We reuse the same handler which can parse multiple vendor payloads,
    # but keep a dedicated route so providers can be configured separately.
    app.router.add_post("/webhook/replicate", handle_kling_webhook)

    # Вебхук Seedream (Novita AI)
    app.router.add_post("/webhook/seedream", handle_seedream_webhook)

    # Вебхук Novita FLUX.2 Pro
    app.router.add_post("/webhook/novita", handle_novita_webhook)

    # Вебхук WanX (PiAPI)
    app.router.add_post("/webhook/wanx", handle_wanx_webhook)

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
