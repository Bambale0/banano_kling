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
    catalog_router,
    common_router,
    generation_router,
    image_analyzer_router,
    payments_router,
)
from bot.handlers.payments import (
    handle_robokassa_result,
    handle_robokassa_success,
    handle_yookassa_webhook,
)
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
            except Exception as e:
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

    # Middleware для проверки подписки
    from bot.middleware.subscription import SubscriptionCheckMiddleware

    dp.message.middleware(SubscriptionCheckMiddleware())
    dp.callback_query.middleware(SubscriptionCheckMiddleware())

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
    dp.include_router(common_router)  # Общие команды
    dp.include_router(catalog_router)  # Каталог товаров

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
    """Обработчик уведомлений от Kling/PiAPI/Replicate/Kie.ai"""
    try:
        # Verify Replicate webhook signature if configured
        from bot.config import config as _config

        def _verify_replicate_signature(
            secret: str, body: bytes, headers: dict
        ) -> bool:
            """Verify HMAC SHA256 signature using common header names."""
            if not secret:
                return True
            import hashlib
            import hmac

            body_bytes = (
                body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            )

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

                sig_str = sig if isinstance(sig, str) else str(sig)
                parts = [p.strip() for p in sig_str.split(",") if p.strip()]
                sig_candidate = parts[-1]

                if sig_candidate.startswith("sha256="):
                    sig_val = sig_candidate.split("=", 1)[1]
                elif sig_candidate.startswith("v1="):
                    sig_val = sig_candidate.split("=", 1)[1]
                else:
                    sig_val = sig_candidate

                try:
                    computed_hex = hmac.new(
                        secret_bytes, body_bytes, hashlib.sha256
                    ).hexdigest()
                    if hmac.compare_digest(computed_hex, sig_val):
                        return True
                except Exception as e:
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

        # Kling specific format: {'code': 200, 'data': {'result_video_url': '...'}, 'msg': '...', 'taskId': '...'}
        if "code" in data and data.get("code") == 200 and "taskId" in data:
            task_id = data["taskId"]
            video_url = data["data"].get("result_video_url")
            if task_id and video_url:
                logger.info(
                    f"Kling success webhook: task {task_id}, video {video_url[:50]}..."
                )
                from bot.database import (
                    complete_video_task,
                    get_task_by_id,
                    get_telegram_id_by_user_id,
                )
                from bot.keyboards import get_video_result_keyboard

                task = await get_task_by_id(task_id)
                if task:
                    telegram_id = await get_telegram_id_by_user_id(task.user_id)
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            caption = f"✅ <b>Видео (Kling) готово!</b>\\n\\nID: <code>{task_id}</code>"
                            if task.duration:
                                caption += f"\\n⏱ <code>{task.duration}с</code>"
                            if task.aspect_ratio:
                                caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
                            if task.cost:
                                caption += f"\\n💰 <code>{task.cost}💎</code>"
                            if task.preset_id == "no_preset" and task.prompt:
                                caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
                            else:
                                caption += f"\\n\\n🎯 Пресет: {task.preset_id}"

                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_url,
                                caption=caption,
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=get_video_result_keyboard(video_url),
                            )
                            await complete_video_task(task_id, video_url)
                            logger.info(f"Kling video sent to {telegram_id}")
                        except Exception as e:
                            logger.error(
                                f"Failed to notify Kling user {telegram_id}: {e}"
                            )
                        finally:
                            await bot_instance.session.close()
                return web.Response(status=200)

        # Detect Kie.ai format (code:200/501, data.taskId, data.resultJson or failMsg)
        if "code" in data and "data" in data:
            kie_data = data["data"]
            task_id = kie_data.get("taskId")
            status = kie_data.get("state", "").lower()
            result_json_str = kie_data.get("resultJson", "{}")
            fail_code = kie_data.get("failCode")
            fail_msg = kie_data.get("failMsg", "")
            try:
                result_json = json.loads(result_json_str)
                video_url = result_json.get("resultUrls", [None])[0]
            except (json.JSONDecodeError, KeyError):
                video_url = None

            if task_id:
                logger.info(
                    f"Kie.ai webhook: task {task_id}, status {status}, "
                    + f"video {video_url[:50] if video_url else None}..., "
                    + f"fail: {fail_code}/{fail_msg[:50]}..."
                )
                from bot.database import (
                    add_credits,
                    complete_video_task,
                    get_task_by_id,
                    get_telegram_id_by_user_id,
                )

                task = await get_task_by_id(task_id)
                if task:
                    telegram_id = await get_telegram_id_by_user_id(task.user_id)
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            if status in {"success", "completed"} and video_url:
                                # Success case
                                caption = f"✅ <b>{'Видео' if task.type == 'video' else 'Изображение'} ({task.model or 'Kie.ai'}) готово!</b>\\n\\nID: <code>{task_id}</code>"
                                if task.duration:
                                    caption += f"\\n⏱ <code>{task.duration}с</code>"
                                if task.aspect_ratio:
                                    caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
                                if task.cost:
                                    caption += f"\\n💰 <code>{task.cost}💎</code>"
                                if task.preset_id == "no_preset" and task.prompt:
                                    caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
                                else:
                                    caption += f"\\n\\n🎯 Пресет: {task.preset_id}"
                                import os

                                # Отправляем видео - всегда скачиваем для Kie.ai
                                import tempfile

                                import aiohttp
                                from aiogram.types import FSInputFile

                                from bot.keyboards import get_video_result_keyboard

                                tmp_file = None
                                try:
                                    async with aiohttp.ClientSession() as sess:
                                        headers = {
                                            "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot SDK/1.0)",
                                            "Accept": "*/*",
                                        }
                                        async with sess.get(
                                            video_url,
                                            headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=120),
                                        ) as resp:
                                            if resp.status != 200:
                                                raise RuntimeError(
                                                    f"Download failed: status {resp.status}"
                                                )
                                            tmp = tempfile.NamedTemporaryFile(
                                                delete=False, suffix=".mp4"
                                            )
                                            tmp_file = tmp.name
                                            with open(tmp_file, "wb") as f:
                                                async for (
                                                    chunk
                                                ) in resp.content.iter_chunked(
                                                    1024 * 64
                                                ):
                                                    if chunk:
                                                        f.write(chunk)
                                    video_file = FSInputFile(tmp_file)
                                    await bot_instance.send_video(
                                        chat_id=telegram_id,
                                        video=video_file,
                                        caption=caption,
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                        reply_markup=get_video_result_keyboard(
                                            video_url
                                        ),
                                    )
                                    logger.info(
                                        f"Kie.ai video downloaded and sent to {telegram_id}"
                                    )
                                except Exception as dl_e:
                                    logger.error(
                                        f"Kie.ai video download failed: {dl_e}"
                                    )
                                    # Fallback to URL
                                    await bot_instance.send_video(
                                        chat_id=telegram_id,
                                        video=video_url,
                                        caption=caption,
                                        parse_mode="HTML",
                                        supports_streaming=True,
                                        reply_markup=get_video_result_keyboard(
                                            video_url
                                        ),
                                    )
                                    logger.info(
                                        f"Kie.ai video sent via URL to {telegram_id}"
                                    )
                                finally:
                                    if tmp_file and os.path.exists(tmp_file):
                                        try:
                                            os.remove(tmp_file)
                                        except Exception as e:
                                            pass
                                await complete_video_task(task_id, video_url)
                                logger.info(f"Kie.ai result sent to {telegram_id}")
                            else:
                                # Fail case
                                policy_violation = "Prohibited Use policy" in fail_msg
                                error_msg = (
                                    "Ваш запрос был отклонён из-за нарушения политики Google (чувствительный контент)."
                                    if policy_violation
                                    else f"Ошибка API: {fail_msg[:100]}"
                                )
                                await add_credits(telegram_id, task.cost or 0)
                                await bot_instance.send_message(
                                    chat_id=telegram_id,
                                    text=f"❌ <b>Генерация не удалась</b>\n\n"
                                    + f"ID: <code>{task_id}</code>\n\n"
                                    + f"{error_msg}\n\n"
                                    + f"💎 Кредиты возвращены.",
                                    parse_mode="HTML",
                                )
                                await complete_video_task(task_id, None)
                                logger.info(
                                    f"Kie.ai fail notified to {telegram_id}, credits returned"
                                )
                        except Exception as e:
                            logger.error(f"Failed to notify user {telegram_id}: {e}")
                        finally:
                            await bot_instance.session.close()
                return web.Response(status=200)

        # Fallback to PiAPI/Replicate parsing
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
                f"Kling webhook missing task id. Top-level keys: {list(data.keys())}, "
                + f"payload: {webhook_data}"
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

            if not task:
                logger.warning(f"{service_name} task {task_id} not found in database")
                return web.Response(status=200)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, "
                + f"preset: {task.preset_id}"
            )

            model_display = task.model or task.preset_id or "Kling"
            caption = f"✅ <b>Видео ({model_display}) готово!</b>\\n\\nID: <code>{task_id}</code>"
            if task.duration:
                caption += f"\\n⏱ <code>{task.duration}с</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{task.cost}💎</code>"
            if task.preset_id == "no_preset" and task.prompt:
                caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {task.preset_id}"

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
                logger.error(f"Failed to send video via URL: {e}")
                # If sending by URL failed (Telegram can't fetch remote file),
                # try to download the file locally and upload it to Telegram.
                try:
                    # Only attempt download for http(s) URLs
                    if isinstance(video_url, str) and video_url.lower().startswith(
                        "http"
                    ):
                        import os
                        import tempfile

                        import aiohttp as _aiohttp

                        logger.info(
                            "Attempting to download video and upload to Telegram as file"
                        )
                        tmp_file = None
                        try:
                            async with _aiohttp.ClientSession() as sess:
                                async with sess.get(video_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Failed to download video, status={resp.status}"
                                        )
                                    # Create temporary file
                                    tmp = tempfile.NamedTemporaryFile(delete=False)
                                    tmp_file = tmp.name
                                    # Stream write
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)

                            # Send downloaded file
                            from aiogram.types import FSInputFile

                            from bot.keyboards import get_video_result_keyboard

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=caption,
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=get_video_result_keyboard(video_url),
                            )

                            await complete_video_task(task_id, video_url)
                            logger.info(
                                f"Video downloaded and sent to user {telegram_id}"
                            )
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except Exception as e:
                                    logger.exception(
                                        "Failed to remove temporary video file"
                                    )
                    else:
                        # Fallback — отправляем как ссылка
                        from bot.keyboards import get_video_result_keyboard

                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=f"🎬 Ваше видео готово!\n\n{video_url}",
                            reply_markup=get_video_result_keyboard(video_url),
                            parse_mode="HTML",
                        )
                except Exception as fallback_error:
                    logger.error(
                        f"Failed to send fallback message or upload video: {fallback_error}"
                    )
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
                                    "💎 Кредиты возвращены на счёт."
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

            model_display = task.model or task.preset_id or "Seedream"
            caption = f"✅ <b>Изображение ({model_display}) готово!</b>\\n\\nID: <code>{task_id}</code>"
            if task.aspect_ratio:
                caption += f"\\n📐 <code>{task.aspect_ratio}</code>"
            if task.cost:
                caption += f"\\n💰 <code>{task.cost}💎</code>"
            if task.preset_id == "no_preset" and task.prompt:
                caption += f"\\n\\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
            else:
                caption += f"\\n\\n🎯 Пресет: {task.preset_id}"

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


async def handle_kie_ai_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kie.ai (Nano Banana 2) API"""
    try:
        logger.info(f"Kie.ai webhook headers: {dict(request.headers)}")

        raw_body = await request.read()
        if not raw_body:
            logger.warning("Kie.ai webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            logger.info(f"Kie.ai webhook raw body: {repr(body_text)}")
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kie.ai webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(f"Kie.ai webhook parsed data: {data}")

        from bot.database import (
            add_credits,
            complete_video_task,
            get_task_by_id,
            get_telegram_id_by_user_id,
        )
        from bot.keyboards import get_video_result_keyboard

        # Flexible extraction for task_id, status, image_url
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
        task_id = (
            webhook_data.get("taskId")
            or webhook_data.get("task_id")
            or webhook_data.get("id")
        )
        status = webhook_data.get("state") or webhook_data.get("status")
        normalized_status = str(status).lower() if status else ""

        model = webhook_data.get("model", "")
        model_lower = model.lower()
        if "seedream" in model_lower:
            service_name = "Seedream"
            if "4.5-edit" in model_lower:
                service_name += " 4.5 Edit"
            elif "lite" in model_lower:
                service_name += " Lite"
        elif "nano-banana" in model_lower or "nano_banana" in model_lower:
            service_name = "Nano Banana"
            if "pro" in model_lower:
                service_name += " Pro"
            else:
                service_name += " 2"
        else:
            service_name = "Kie.ai"

        logger.info(
            f"Processing {service_name} task {task_id} with status {status} (normalized: {normalized_status})"
        )

        if not task_id:
            logger.error(f"Kie.ai webhook missing task id. Payload: {webhook_data}")
            return web.Response(status=200)

        # Find task in DB early for both success and failure
        task = await get_task_by_id(task_id)
        telegram_id = None
        if task:
            telegram_id = await get_telegram_id_by_user_id(task.user_id)

        if normalized_status in {"success", "completed", "succeeded", "finished"}:
            # Parse resultJson for Kie.ai specific format
            result_json_str = webhook_data.get("resultJson", "{}")
            result_url = None
            try:
                result_json = json.loads(result_json_str)
                result_urls = result_json.get("resultUrls", [])
                result_url = result_urls[0] if result_urls else None
            except (json.JSONDecodeError, KeyError, IndexError):
                logger.warning(f"Failed to parse Kie.ai resultJson: {result_json_str}")

            if result_url:
                logger.info(
                    f"Extracted {service_name} result URL: {result_url[:50]}..."
                )
            else:
                logger.error(
                    f"No result URL found in {service_name} result: {webhook_data.get('resultJson', 'N/A')}"
                )
                if telegram_id:
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=f"❌ <b>Ошибка генерации ({service_name})</b>\n\nID: <code>{task_id}</code>\n\nНет результата от API.",
                            parse_mode="HTML",
                        )
                    finally:
                        await bot_instance.session.close()
                return web.Response(status=200)

            if not task:
                logger.warning(f"{service_name} task {task_id} not found in database")
                return web.Response(status=200)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found {service_name} task for user {task.user_id}, telegram_id: {telegram_id}, preset: {task.preset_id}"
            )

            source_links = ""
            try:
                param_str = webhook_data.get("param", "{}")
                param_json = json.loads(param_str)
                input_str = param_json.get("input", "{}")
                input_json = json.loads(input_str)
                sources = []
                for key in [
                    "image_urls",
                    "image_input",
                    "input_urls",
                    "first_frame_url",
                    "image_url",
                ]:
                    val = input_json.get(key)
                    if val:
                        if isinstance(val, list):
                            sources.extend([str(u) for u in val[:3]])
                        else:
                            sources.append(str(val))
                if sources:
                    source_links = f"\n🖼 <b>Исходники:</b>\n" + "\n".join(
                        [
                            f"• <a href='{u}'>{u.split('/')[-1] if '/' in u else u}</a>"
                            for u in sources[:3]
                        ]
                    )
            except:
                pass

            is_video = False
            if result_url:
                url_lower = result_url.lower()
                video_exts = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".flv"]
                if any(url_lower.endswith(ext) for ext in video_exts):
                    is_video = True
                elif "video" in model_lower:
                    is_video = True

            # Build ultra-compact caption with minimal line breaks
            info_lines = []
            if task.cost:
                info_lines.append(f"💰{task.cost}💎")
            if task.duration:
                info_lines.append(f"⏱{task.duration}с")
            if task.aspect_ratio:
                info_lines.append(f"📐{task.aspect_ratio}")
            info_str = " | ".join(info_lines) if info_lines else ""

            prompt_or_preset = (
                f"<code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"
                if task.preset_id == "no_preset" and task.prompt
                else task.preset_id
            )
            label = "Промпт" if task.preset_id == "no_preset" else "Пресет"

            full_caption = f"""✅ <b>{'Видео' if is_video else 'Изображение'} ({service_name})</b> | ID: <code>{task_id}</code>{' | ' + info_str if info_str else ''}
\n🎯 {label}: {prompt_or_preset}{source_links}
\n🔗 <a href='{result_url}'>📥 Ссылка</a>"""

            kb_link = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="📥 Скачать оригинал", url=result_url
                        )
                    ]
                ]
            )

            bot_instance = Bot(token=config.BOT_TOKEN)
            try:
                sent_media = False
                if is_video:
                    video_kb = get_video_result_keyboard(result_url)
                    # Try URL first
                    try:
                        await bot_instance.send_video(
                            chat_id=telegram_id,
                            video=result_url,
                            caption=full_caption,
                            parse_mode="HTML",
                            supports_streaming=True,
                            reply_markup=video_kb,
                        )
                        logger.info(
                            f"{service_name} video sent via URL to user {telegram_id}"
                        )
                        sent_media = True
                    except Exception as e:
                        logger.warning(
                            f"Video URL send failed ({e}), trying file upload"
                        )
                        tmp_file = None
                        try:
                            import os
                            import tempfile

                            import aiohttp

                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url, timeout=60) as resp:
                                    if resp.status != 200:
                                        raise RuntimeError(
                                            f"Download failed: {resp.status}"
                                        )
                                    tmp = tempfile.NamedTemporaryFile(
                                        delete=False, suffix=".mp4"
                                    )
                                    tmp_file = tmp.name
                                    with open(tmp_file, "wb") as f:
                                        async for chunk in resp.content.iter_chunked(
                                            1024 * 64
                                        ):
                                            if chunk:
                                                f.write(chunk)
                            from aiogram.types import FSInputFile

                            video_file = FSInputFile(tmp_file)
                            await bot_instance.send_video(
                                chat_id=telegram_id,
                                video=video_file,
                                caption=full_caption,
                                parse_mode="HTML",
                                supports_streaming=True,
                                reply_markup=video_kb,
                            )
                            logger.info(
                                f"{service_name} video sent as file to user {telegram_id}"
                            )
                            sent_media = True
                        except Exception as dl_e:
                            logger.error(f"Video file upload failed: {dl_e}")
                        finally:
                            if tmp_file and os.path.exists(tmp_file):
                                try:
                                    os.remove(tmp_file)
                                except:
                                    pass
                else:
                    # Image
                    image_bytes = None
                    try:
                        import aiohttp

                        async with aiohttp.ClientSession() as session:
                            async with session.get(result_url, timeout=30) as resp:
                                if resp.status == 200:
                                    image_bytes = await resp.read()
                                else:
                                    raise Exception(f"Download failed: {resp.status}")
                    except Exception as download_e:
                        logger.error(
                            f"Failed to download image {result_url}: {download_e}"
                        )

                    if image_bytes:
                        max_photo_size = 10 * 1024 * 1024
                        if len(image_bytes) <= max_photo_size:
                            photo = types.BufferedInputFile(
                                image_bytes, filename="generated.png"
                            )
                            await bot_instance.send_photo(
                                chat_id=telegram_id,
                                photo=photo,
                                caption=full_caption,
                                parse_mode="HTML",
                                reply_markup=kb_link,
                            )
                            logger.info(
                                f"{service_name} image sent as photo to user {telegram_id}"
                            )
                            sent_media = True
                        else:
                            doc_caption = f"{full_caption}\\n\\n📎 Файл (более 10MB)"
                            document = types.BufferedInputFile(
                                image_bytes, filename="generated.png"
                            )
                            await bot_instance.send_document(
                                chat_id=telegram_id,
                                document=document,
                                caption=doc_caption,
                                parse_mode="HTML",
                                reply_markup=kb_link,
                            )
                            logger.info(
                                f"{service_name} image sent as document to user {telegram_id}"
                            )
                            sent_media = True
                    else:
                        logger.warning(f"No image bytes for {service_name}")

                if sent_media:
                    await complete_video_task(task_id, result_url)
                else:
                    # Fallback text
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=full_caption,
                        reply_markup=kb_link,
                        parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
                    await complete_video_task(task_id, result_url)
                    logger.info(
                        f"{service_name} fallback text sent to user {telegram_id}"
                    )
            except Exception as send_e:
                logger.error(
                    f"Failed to send {service_name} result to {telegram_id}: {send_e}"
                )
            finally:
                await bot_instance.session.close()
        else:
            # Enhanced failure logging and user notification
            fail_code = webhook_data.get("failCode", "unknown")
            fail_msg = webhook_data.get("failMsg", "No details")
            logger.error(
                f"{service_name} task {task_id} FAILED: failCode={fail_code}, failMsg={fail_msg}, full data: {webhook_data}"
            )

            if task and task.cost and task.cost > 0:
                await add_credits(telegram_id, task.cost)

            if telegram_id:
                bot_instance = Bot(token=config.BOT_TOKEN)
                try:
                    error_msg = f"❌ <b>Ошибка генерации ({service_name})</b>\n\nID: <code>{task_id}</code>\n\nКод: <code>{fail_code}</code>\nСообщение: {fail_msg}\n\n{'💎 Кредиты возвращены!' if task and task.cost and task.cost > 0 else 'Попробуйте упростить промпт или повторить позже.'}"
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=error_msg,
                        parse_mode="HTML",
                    )
                    logger.info(f"Failure notification sent to {telegram_id}")
                except Exception as notify_e:
                    logger.error(f"Failed to notify user {telegram_id}: {notify_e}")
                finally:
                    await bot_instance.session.close()
            else:
                logger.warning(
                    f"No telegram_id for failed task {task_id} (user_id: {task.user_id if task else 'unknown'})"
                )

            await complete_video_task(task_id, None)

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kie.ai webhook error: {e}")
        return web.Response(status=200)


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

    # Вебхук YooKassa
    app.router.add_post("/yookassa/webhook", handle_yookassa_webhook)

    # Robokassa webhooks
    app.router.add_post("/robokassa/result", handle_robokassa_result)
    app.router.add_get("/robokassa/result", handle_robokassa_result)
    app.router.add_get("/robokassa/success", handle_robokassa_success)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Kie.ai (Nano Banana 2)
    app.router.add_post(config.KIE_AI_WEBHOOK_PATH, handle_kie_ai_webhook)

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
