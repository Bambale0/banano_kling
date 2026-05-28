import asyncio
import html
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

from aiogram import BaseMiddleware, Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Update
from aiohttp import web

from bot.config import config
from bot.database import init_db, is_maintenance_mode, is_user_banned
from bot.handlers import (
    admin_router,
    batch_generation_router,
    common_router,
    feed_router,
    generation_router,
    image_analyzer_router,
    payments_router,
    start_router,
)
from bot.handlers.payments import handle_cryptobot_webhook, handle_tbank_webhook
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


TERMINAL_SUCCESS_STATUSES = {"success", "completed", "succeeded", "finished"}
TERMINAL_FAILURE_STATUSES = {
    "fail",
    "failed",
    "failure",
    "error",
    "cancelled",
    "canceled",
    "rejected",
    "timeout",
    "timed_out",
    "task_status_failed",
}
NON_TERMINAL_STATUSES = {
    "",
    "pending",
    "processing",
    "running",
    "queued",
    "created",
    "submitted",
    "in_progress",
    "task_status_processing",
}


def _status_kind(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in TERMINAL_SUCCESS_STATUSES:
        return "success"
    if normalized in TERMINAL_FAILURE_STATUSES:
        return "failure"
    return "pending"


def _verify_ai_webhook_request(request: web.Request, provider: str) -> bool:
    """Verify callbacks from providers that cannot sign payloads themselves."""
    secret = config.AI_WEBHOOK_SECRET
    if not secret:
        logger.warning(
            "AI_WEBHOOK_SECRET is not set; accepting unsigned %s webhook", provider
        )
        return True

    query = getattr(request, "query", {})
    candidates = [
        query.get("secret") if hasattr(query, "get") else None,
        request.headers.get("x-webhook-secret"),
        request.headers.get("x-ai-webhook-secret"),
    ]
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        candidates.append(auth.split(" ", 1)[1].strip())

    import hmac

    return any(
        candidate and hmac.compare_digest(str(candidate), secret)
        for candidate in candidates
    )


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user or config.is_admin(user.id):
            return await handler(event, data)

        if await is_user_banned(user.id):
            if isinstance(event, types.Message):
                await event.answer("🚫 Доступ к боту ограничен.")
            elif isinstance(event, types.CallbackQuery):
                await event.answer("Доступ ограничен", show_alert=True)
            return None

        if await is_maintenance_mode():
            text = "⚙️ Бот временно на обслуживании. Скоро вернёмся."
            if isinstance(event, types.Message):
                await event.answer(text)
            elif isinstance(event, types.CallbackQuery):
                await event.answer(text, show_alert=True)
            return None

        return await handler(event, data)


def _build_friendly_generation_error(
    fail_code: str | int | None,
    fail_msg: str | None,
    *,
    service_name: str | None = None,
    credits_returned: bool = False,
) -> str:
    code = html.escape(str(fail_code or "unknown"))
    details = (fail_msg or "").lower()
    service = f" ({html.escape(service_name)})" if service_name else ""

    if any(
        marker in details
        for marker in (
            "content safety",
            "safety restrictions",
            "prohibited use policy",
            "sensitive content",
            "policy",
        )
    ):
        friendly_text = (
            "Запрос отклонён фильтром безопасности. Иногда он ошибается даже на обычных фото. "
            "Попробуйте другое фото или более нейтральный промпт."
        )
    elif any(marker in details for marker in ("timeout", "timed out")):
        friendly_text = (
            "Сервис не успел подготовить результат. Попробуйте повторить запрос чуть позже."
        )
    elif any(marker in details for marker in ("rate limit", "too many requests")):
        friendly_text = (
            "Сервис временно перегружен. Попробуйте повторить запрос через пару минут."
        )
    else:
        friendly_text = (
            "Не получилось создать результат. Попробуйте упростить промпт или повторить позже."
        )

    refund_text = (
        "\n\n🍌 Бананы возвращены на счёт."
        if credits_returned
        else "\n\nПопробуйте ещё раз чуть позже."
    )
    return (
        f"❌ <b>Генерация не удалась{service}</b>\n\n"
        f"Код: <code>{code}</code>\n"
        f"{friendly_text}"
        f"{refund_text}"
    )


def _short_result_text(value: str | None, limit: int = 220) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return html.escape(text)
    return html.escape(text[:limit].rstrip()) + "..."


def _build_generation_result_caption(
    *,
    media_label: str,
    model_display: str,
    task_id: str,
    task,
    result_url: str | None = None,
) -> str:
    lines = [
        f"✅ <b>{media_label} ({html.escape(str(model_display))}) готово!</b>",
        f"ID: <code>{html.escape(str(task_id))}</code>",
    ]
    details = []
    if getattr(task, "duration", None):
        details.append(f"⏱ <code>{task.duration}с</code>")
    if getattr(task, "aspect_ratio", None):
        details.append(f"📐 <code>{html.escape(str(task.aspect_ratio))}</code>")
    if getattr(task, "cost", None):
        details.append(f"💰 <code>{task.cost}🍌</code>")
    if details:
        lines.append(" · ".join(details))

    if getattr(task, "prompt", None):
        lines.append(f"🎯 <b>Промпт:</b> <code>{_short_result_text(task.prompt)}</code>")
    elif getattr(task, "preset_id", None) and task.preset_id not in {"no_preset", "no_preset_video"}:
        lines.append(f"🎯 <b>Пресет:</b> {html.escape(str(task.preset_id))}")

    if result_url:
        lines.append(f"🔗 <a href='{html.escape(result_url, quote=True)}'>Скачать</a>")

    return "\n\n".join(lines)


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
    dp.message.middleware(AccessControlMiddleware())
    dp.callback_query.middleware(AccessControlMiddleware())

    # Регистрируем глобальный обработчик ошибок
    dp.errors.register(errors_handler)

    # ⭐ КРИТИЧЕСКИ ВАЖНО: Порядок роутеров в aiogram 3.x
    # Первый зарегистрированный роутер имеет НАИВЫСШИЙ приоритет!
    # Сообщение передаётся ВСЕМ роутерам одновременно, но обрабатывается
    # тем, у кого более специфичный фильтр (например, StateFilter)
    #
    # Правильный порядок:
    # 0. start_router (/start must reset any active FSM state)
    # 1. generation_router (FSM состояния - самые специфичные)
    # 2. admin_router (админ команды)
    # 3. payments_router (платежи)
    # 4. batch_generation_router (пакетная генерация)
    # 5. common_router (общие команды /help - самые общие)

    dp.include_router(start_router)  # /start работает из любого состояния
    dp.include_router(generation_router)  # FSM состояния - ПЕРВЫЙ!
    dp.include_router(image_analyzer_router)  # Анализ фото в промпт
    dp.include_router(feed_router)  # Bot-side лента публичных фото
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

        # Idempotency: Telegram can retry the same update.
        update_id = update_data.get("update_id")
        if update_id is not None:
            from bot.services.reliability import runtime_reliability

            if not await runtime_reliability.mark_telegram_update(int(update_id)):
                logger.info("Skipping duplicate Telegram update_id=%s", update_id)
                return web.Response(text="OK", status=200)

        # Создаём объект Update
        update = Update(**update_data)

        # Обрабатываем обновление через диспетчер. Ставим timeout ниже 60с,
        # чтобы aiogram корректно переводил слишком долгую обработку в background
        # без лишних повторов от Telegram.
        await dp.feed_webhook_update(bot, update, _timeout=25)

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


async def _download_remote_file(url: str, suffix: str = "") -> tuple[str | None, str | None]:
    import tempfile

    import aiohttp

    tmp_file = None
    try:
        async with aiohttp.ClientSession() as sess:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; Telegram Bot SDK/1.0)",
                "Accept": "*/*",
            }
            async with sess.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    return None, f"download failed: status {resp.status}"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp_file = tmp.name
                with open(tmp_file, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 64):
                        if chunk:
                            f.write(chunk)
        return tmp_file, None
    except Exception as e:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        return None, str(e)


async def _send_video_with_fallback(
    bot_instance: Bot,
    chat_id: int,
    video_url: str,
    caption: str,
    reply_markup=None,
) -> bool:
    from aiogram.types import FSInputFile

    try:
        await bot_instance.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=caption,
            parse_mode="HTML",
            supports_streaming=True,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.warning(
            "Video URL send failed (%s), trying file upload",
            e,
        )

    tmp_file, download_error = await _download_remote_file(video_url, suffix=".mp4")
    if not tmp_file:
        logger.error("Video download fallback failed: %s", download_error)
        return False

    try:
        await bot_instance.send_video(
            chat_id=chat_id,
            video=FSInputFile(tmp_file),
            caption=caption,
            parse_mode="HTML",
            supports_streaming=True,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.error("Video upload fallback failed: %s", e)
        return False
    finally:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                logger.exception("Failed to remove temporary video file")


async def handle_kling_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от Kling/PiAPI/Kie.ai"""
    try:
        raw_body = await request.read()
        if not _verify_ai_webhook_request(request, "kling"):
            logger.warning("Rejected Kling webhook: invalid AI webhook secret")
            return web.Response(status=403)

        # Проверяем, есть ли данные в теле запроса
        if not raw_body:
            logger.warning("Kling webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kling webhook received invalid JSON: {e}")
            return web.Response(status=200)

        logger.info(
            "Kling webhook received: keys=%s task_id=%s status=%s",
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            data.get("taskId") or data.get("task_id") or data.get("id") if isinstance(data, dict) else None,
            data.get("status") or data.get("state") if isinstance(data, dict) else None,
        )

        # Kling specific format: {'code': 200, 'data': {'result_video_url': '...'}, 'msg': '...', 'taskId': '...'}
        if "code" in data and data.get("code") == 200 and "taskId" in data:
            task_id = data["taskId"]
            video_url = data["data"].get("result_video_url")
            if task_id and video_url:
                from bot.database import (
                    complete_video_task,
                    get_task_by_id,
                    get_telegram_id_by_user_id,
                )
                from bot.keyboards import get_video_result_keyboard

                task = await get_task_by_id(task_id)
                model_display = task.model if task and task.model else "Kling"
                if model_display == "aleph":
                    model_display = "Aleph Video"
                elif model_display == "glow":
                    model_display = "Kling Glow"
                logger.info(
                    f"{model_display} success webhook: task {task_id}, video {video_url[:50]}..."
                )
                if task:
                    telegram_id = await get_telegram_id_by_user_id(task.user_id)
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            caption = _build_generation_result_caption(
                                media_label="Видео",
                                model_display=model_display,
                                task_id=task_id,
                                task=task,
                            )

                            sent = await _send_video_with_fallback(
                                bot_instance=bot_instance,
                                chat_id=telegram_id,
                                video_url=video_url,
                                caption=caption,
                                reply_markup=get_video_result_keyboard(video_url),
                            )
                            if sent:
                                await complete_video_task(task_id, video_url)
                                logger.info(f"{model_display} video sent to {telegram_id}")
                            else:
                                logger.error(
                                    "%s video delivery failed for %s after all fallbacks",
                                    model_display,
                                    telegram_id,
                                )
                        except Exception as e:
                            logger.error(
                                f"Failed to notify {model_display} user {telegram_id}: {e}"
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
                from bot.database import (
                    add_credits,
                    complete_video_task,
                    get_task_by_id,
                    get_telegram_id_by_user_id,
                )

                task = await get_task_by_id(task_id)
                model_display = task.model if task and task.model else "AI"
                if model_display == "aleph":
                    model_display = "Aleph Video"
                elif model_display == "glow":
                    model_display = "Kling Glow"
                logger.info(
                    f"{model_display} webhook: task {task_id}, status {status}, "
                    + f"video {video_url[:50] if video_url else None}..., "
                    + f"fail: {fail_code}/{fail_msg[:50]}..."
                )
                if task:
                    telegram_id = await get_telegram_id_by_user_id(task.user_id)
                    if telegram_id:
                        bot_instance = Bot(token=config.BOT_TOKEN)
                        try:
                            if _status_kind(status) == "success" and video_url:
                                # Success case
                                model_display = task.model if task.model else "AI"
                                if model_display == "aleph":
                                    model_display = "Aleph Video"
                                elif model_display == "glow":
                                    model_display = "Kling Glow"
                                caption = _build_generation_result_caption(
                                    media_label="Видео" if task.type == "video" else "Изображение",
                                    model_display=model_display,
                                    task_id=task_id,
                                    task=task,
                                )
                                from bot.keyboards import get_video_result_keyboard

                                sent = await _send_video_with_fallback(
                                    bot_instance=bot_instance,
                                    chat_id=telegram_id,
                                    video_url=video_url,
                                    caption=caption,
                                    reply_markup=get_video_result_keyboard(video_url),
                                )
                                if sent:
                                    await complete_video_task(task_id, video_url)
                                    logger.info(f"Kie.ai result sent to {telegram_id}")
                                else:
                                    raise RuntimeError(
                                        "Kie.ai delivery failed after URL/upload fallbacks"
                                    )
                            elif _status_kind(status) == "failure":
                                # Fail case
                                await add_credits(telegram_id, task.cost or 0)
                                await bot_instance.send_message(
                                    chat_id=telegram_id,
                                    text=_build_friendly_generation_error(
                                        fail_code,
                                        fail_msg,
                                        service_name=model_display,
                                        credits_returned=bool(task.cost),
                                    ),
                                    parse_mode="HTML",
                                )
                                await complete_video_task(task_id, None)
                                logger.info(
                                    f"Kie.ai fail notified to {telegram_id}, credits returned"
                                )
                            else:
                                logger.info(
                                    "Ignoring non-terminal Kie.ai status for task %s: %s",
                                    task_id,
                                    status,
                                )
                        except Exception as e:
                            logger.error(f"Failed to notify user {telegram_id}: {e}")
                        finally:
                            await bot_instance.session.close()
                return web.Response(status=200)

        # Fallback to PiAPI/Kie-compatible parsing
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

        webhook_data = data
        task_id = _extract_first(
            webhook_data, ("taskId", "task_id", "id", "prediction_id", "predictionId")
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

        status_kind = _status_kind(normalized_status)
        if status_kind == "success":
            # Providers can return either a direct URL/string or a nested object.
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
                logger.info(
                    "%s webhook task %s is not tracked locally; ignoring external/manual task",
                    service_name,
                    task_id,
                )
                return web.Response(status=200)
            if not telegram_id:
                logger.error(f"Cannot find telegram_id for user_id {task.user_id}")
                return web.Response(status=200)

            logger.info(
                f"Found task for user {task.user_id}, telegram_id: {telegram_id}, "
                + f"preset: {task.preset_id}"
            )

            model_display = task.model or task.preset_id or "Kling"
            caption = _build_generation_result_caption(
                media_label="Видео",
                model_display=model_display,
                task_id=task_id,
                task=task,
            )

            # Отправляем видео пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            try:
                from bot.keyboards import get_video_result_keyboard

                sent = await _send_video_with_fallback(
                    bot_instance=bot_instance,
                    chat_id=telegram_id,
                    video_url=video_url,
                    caption=caption,
                    reply_markup=get_video_result_keyboard(video_url),
                )

                if sent:
                    await complete_video_task(task_id, video_url)
                    logger.info(f"Video sent to user {telegram_id}")
                else:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🎬 Видео готово, но Telegram не смог принять файл автоматически.\n\nСсылка: {html.escape(video_url)}",
                        reply_markup=get_video_result_keyboard(video_url),
                        parse_mode="HTML",
                    )
                    logger.error(
                        "Failed to deliver video for %s even after upload fallback",
                        telegram_id,
                    )
            finally:
                await bot_instance.session.close()
        elif status_kind == "failure":
            logger.error(f"Kling task {task_id} failed with status: {status}")

            from bot.database import (
                add_credits,
                complete_video_task,
                get_task_by_id,
                get_telegram_id_by_user_id,
            )

            task = await get_task_by_id(task_id)
            if task and task.cost:
                telegram_id = await get_telegram_id_by_user_id(task.user_id)
                if telegram_id:
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        fail_msg = data.get(
                            "msg", str(status) if status else "Unknown error"
                        )
                        await add_credits(telegram_id, task.cost)
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=f"❌ <b>Генерация Kling не удалась</b>\\n\\n"
                            f"ID: <code>{task_id}</code>\\n\\n"
                            f"<code>{fail_msg}</code>\\n\\n"
                            f"🍌 Кредиты возвращены.",
                            parse_mode="HTML",
                        )
                        await complete_video_task(task_id, None)
                        logger.info(f"Kling failure notified to {telegram_id}")
                    except Exception as e:
                        logger.error(
                            f"Failed to notify Kling failure to {telegram_id}: {e}"
                        )
                    finally:
                        await bot_instance.session.close()

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
                                    "❌ <b>Ваш промпт был помечен как чувствительный контент</b>"
                                    "Пожалуйста, попробуйте другой промпт без чувствительного контента."
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
        else:
            logger.info(
                "Ignoring non-terminal Kling task %s status: %s",
                task_id,
                status,
            )

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
        if not _verify_ai_webhook_request(request, "seedream"):
            logger.warning("Rejected Seedream webhook: invalid AI webhook secret")
            return web.Response(status=403)

        body = await request.text()

        if not body:
            logger.warning("Seedream webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"Seedream webhook received invalid JSON: {e}")
            return web.Response(status=200)

        # Check event type - Novita AI sends ASYNC_TASK_RESULT
        event_type = data.get("event_type")
        logger.info(
            "Seedream webhook received: event_type=%s keys=%s",
            event_type,
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        )
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
            caption = _build_generation_result_caption(
                media_label="Изображение",
                model_display=model_display,
                task_id=task_id,
                task=task,
            )

            # Обновляем задачу в БД
            await complete_video_task(task_id, image_url)

            # Отправляем изображение пользователю
            bot_instance = Bot(token=config.BOT_TOKEN)

            from bot.keyboards import get_image_result_keyboard

            img_kb = get_image_result_keyboard(task_id, image_url)

            try:
                await bot_instance.send_photo(
                    chat_id=telegram_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=img_kb,
                )

                logger.info(f"Image sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send image: {e}")
                # Fallback — отправляем как ссылку
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"🖼️ Ваше изображение готово!{image_url}",
                        reply_markup=img_kb,
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


async def handle_wanx_webhook(request: web.Request) -> web.Response:
    """Обработчик уведомлений от PiAPI WanX API"""
    try:
        if not _verify_ai_webhook_request(request, "wanx"):
            logger.warning("Rejected WanX webhook: invalid AI webhook secret")
            return web.Response(status=403)

        body = await request.text()

        if not body:
            logger.warning("WanX webhook received empty body")
            return web.Response(status=200)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning(f"WanX webhook received invalid JSON: {e}")
            return web.Response(status=200)

        webhook_data = data.get("data") or data.get("payload") or data
        task_id = webhook_data.get("task_id")
        status = webhook_data.get("status")

        if not task_id:
            logger.warning(
                "No task_id in WanX webhook. keys=%s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
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

            caption = _build_generation_result_caption(
                media_label="Видео",
                model_display="WanX",
                task_id=task_id,
                task=task,
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
                        text=f"🎬 Ваше видео WanX готово!{video_url}",
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
        if not _verify_ai_webhook_request(request, "kie_ai"):
            logger.warning("Rejected Kie.ai webhook: invalid AI webhook secret")
            return web.Response(status=403)

        raw_body = await request.read()
        if not raw_body:
            logger.warning("Kie.ai webhook received empty body")
            return web.Response(status=200)

        try:
            body_text = raw_body.decode("utf-8")
            data = json.loads(body_text)
        except Exception as e:
            logger.warning(f"Kie.ai webhook received invalid JSON: {e}")
            return web.Response(status=200)

        from bot.database import (
            add_credits,
            complete_video_task,
            fail_generation_task,
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
        logger.info(
            "Kie.ai webhook received: task_id=%s status=%s code=%s",
            task_id,
            normalized_status,
            data.get("code") if isinstance(data, dict) else None,
        )

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
        elif "hailuo" in model_lower:
            service_name = "Hailuo"
            if "2-3" in model_lower:
                service_name += " 2.3"
            if "pro" in model_lower:
                service_name += " Pro"
            elif "standard" in model_lower:
                service_name += " Std"
        elif "grok-imagine" in model_lower or "grok_imagine" in model_lower:
            service_name = "Grok Imagine"
            if "text-to-image" in model_lower:
                service_name += " T2I"
            elif "image-to-image" in model_lower:
                service_name += " I2I"
        elif "ideogram/character" in model_lower:
            service_name = "Ideogram Character"
        elif "wan/2-7" in model_lower:
            service_name = "Wan 2.7"
            if "image-to-video" in model_lower:
                service_name += " I2V"
            elif "t2v" in model_lower:
                service_name += " T2V"
            elif "r2v" in model_lower:
                service_name += " R2V"
        elif "happyhorse" in model_lower:
            service_name = "HappyHorse"
            if "text-to-video" in model_lower:
                service_name += " T2V"
            elif "image-to-video" in model_lower:
                service_name += " I2V"
            elif "reference-to-video" in model_lower:
                service_name += " Ref2V"
            elif "video-edit" in model_lower:
                service_name += " Edit"
        else:
            service_name = "AI"

        logger.info(
            f"Processing {service_name} task {task_id} with status {status} (normalized: {normalized_status})"
        )

        if not task_id:
            logger.error(f"Kie.ai webhook missing task id. Payload: {webhook_data}")
            return web.Response(status=200)

        from bot.services.reliability import runtime_reliability
        event_status = normalized_status or "unknown"
        if not await runtime_reliability.mark_provider_event("kie_ai", str(task_id), event_status):
            logger.info("Skipping duplicate Kie.ai webhook task_id=%s status=%s", task_id, event_status)
            return web.Response(status=200)

        # Find task in DB early for both success and failure
        task = await get_task_by_id(task_id)
        telegram_id = None
        if task:
            telegram_id = await get_telegram_id_by_user_id(task.user_id)

        status_kind = _status_kind(normalized_status)
        if status_kind == "success":
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
                            text=f"❌ <b>Ошибка генерации ({service_name})</b>ID: <code>{task_id}</code>Нет результата от API.",
                            parse_mode="HTML",
                        )
                    finally:
                        await bot_instance.session.close()
                return web.Response(status=200)

            if not task:
                logger.info(
                    "%s webhook task %s is not tracked locally; ignoring external/manual task",
                    service_name,
                    task_id,
                )
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
                input_value = param_json.get("input", {})
                input_json = (
                    json.loads(input_value)
                    if isinstance(input_value, str)
                    else input_value
                )
                sources = []
                for key in [
                    "image_urls",
                    "image_input",
                    "input_urls",
                    "first_frame_url",
                    "image_url",
                    "reference_image",
                    "video_url",
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
                            f"• <a href='{html.escape(u, quote=True)}'>{html.escape(u.split('/')[-1] if '/' in u else u)}</a>"
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
                info_lines.append(f"💰{task.cost}🍌")
            if task.duration:
                info_lines.append(f"⏱{task.duration}с")
            if task.aspect_ratio:
                info_lines.append(f"📐{task.aspect_ratio}")
            info_str = " | ".join(info_lines) if info_lines else ""

            prompt_or_preset = (
                f"<code>{html.escape(task.prompt[:100])}{'...' if len(task.prompt) > 100 else ''}</code>"
                if task.preset_id in {"no_preset", "no_preset_video"} and task.prompt
                else html.escape(task.preset_id or "—")
            )
            label = (
                "Промпт"
                if task.preset_id in {"no_preset", "no_preset_video"}
                else "Пресет"
            )
            service_name_safe = html.escape(service_name)
            result_url_safe = html.escape(result_url or "", quote=True)

            full_caption = f"""✅ <b>{'Видео' if is_video else 'Изображение'} ({service_name_safe})</b> | ID: <code>{task_id}</code>{' | ' + info_str if info_str else ''}
\n🎯 {label}: {prompt_or_preset}{source_links}
\n🔗 <a href='{result_url_safe}'>📥 Ссылка</a>"""

            if not is_video:
                from bot.keyboards import get_image_result_keyboard

                kb_link = get_image_result_keyboard(task_id, result_url)
            else:
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
                            doc_caption = f"{full_caption}\n\n📎 Файл (более 10MB)"
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
        elif status_kind == "failure":
            # Enhanced failure logging and user notification
            fail_code = webhook_data.get("failCode", "unknown")
            fail_msg = webhook_data.get("failMsg", "No details")
            if not task:
                logger.info(
                    "%s webhook task %s failed but is not tracked locally; ignoring external/manual task. failCode=%s failMsg=%s",
                    service_name,
                    task_id,
                    fail_code,
                    fail_msg,
                )
                return web.Response(status=200)

            logger.error(
                f"{service_name} task {task_id} FAILED: failCode={fail_code}, failMsg={fail_msg}, full data: {webhook_data}"
            )

            if task and task.cost and task.cost > 0 and telegram_id:
                from bot.database import add_credits_once

                await add_credits_once(
                    telegram_id,
                    task.cost,
                    reason="generation_refund",
                    external_id=str(task_id),
                    metadata={"provider": "kie_ai", "status": normalized_status},
                )

            if telegram_id:
                bot_instance = Bot(token=config.BOT_TOKEN)
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=_build_friendly_generation_error(
                            fail_code,
                            fail_msg,
                            service_name=service_name,
                            credits_returned=bool(task and task.cost and task.cost > 0),
                        ),
                        parse_mode="HTML",
                    )
                    logger.info(f"Failure notification sent to {telegram_id}")
                except Exception as notify_e:
                    logger.error(f"Failed to notify user {telegram_id}: {notify_e}")
                finally:
                    await bot_instance.session.close()
            else:
                logger.warning(
                    f"No telegram_id for failed task {task_id} (user_id: {task.user_id})"
                )

            await fail_generation_task(task_id)
        else:
            logger.info(
                "Ignoring non-terminal %s webhook task_id=%s status=%s",
                service_name,
                task_id,
                normalized_status,
            )

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Kie.ai webhook error: {e}")
        return web.Response(status=200)


async def handle_veo_webhook(request: web.Request) -> web.Response:
    """Обрабатывает callback от Veo 3.1 API.

    Callback format:
    {
      "code": 200,
      "msg": "...",
      "data": {
        "taskId": "veo_task_...",
        "info": {
          "resultUrls": "[https://...mp4]",   <- JSON-encoded string
          "resolution": "1080p"
        },
        "fallbackFlag": false
      }
    }
    """
    try:
        if not _verify_ai_webhook_request(request, "veo"):
            logger.warning("Rejected Veo webhook: invalid AI webhook secret")
            return web.Response(status=403)

        raw_body = await request.read()

        if not raw_body:
            return web.Response(status=200)

        data = json.loads(raw_body.decode("utf-8"))

        code = data.get("code")
        veo_data = data.get("data", {})
        task_id = veo_data.get("taskId")

        if not task_id:
            logger.error(
                "Veo webhook: missing taskId. keys=%s",
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            return web.Response(status=200)

        from bot.database import (
            add_credits,
            complete_video_task,
            get_task_by_id,
            get_telegram_id_by_user_id,
        )
        from bot.keyboards import get_video_result_keyboard

        task = await get_task_by_id(task_id)
        telegram_id = None
        if task:
            telegram_id = await get_telegram_id_by_user_id(task.user_id)

        if code == 200:
            # Parse resultUrls - it's a JSON-encoded string like "[https://...mp4]"
            info = veo_data.get("info", {})
            result_urls_raw = info.get("resultUrls", "[]")
            video_url = None
            try:
                if isinstance(result_urls_raw, list):
                    video_url = result_urls_raw[0] if result_urls_raw else None
                elif isinstance(result_urls_raw, str):
                    parsed = json.loads(result_urls_raw)
                    video_url = parsed[0] if parsed else None
            except Exception as parse_e:
                logger.error(
                    f"Veo resultUrls parse error: {parse_e}, raw: {result_urls_raw}"
                )

            if not video_url:
                logger.error(f"Veo webhook: no video URL in data: {veo_data}")
                if telegram_id:
                    bot_instance = Bot(token=config.BOT_TOKEN)
                    try:
                        await bot_instance.send_message(
                            chat_id=telegram_id,
                            text=f"❌ <b>Veo 3.1: нет результата</b>\nID: <code>{task_id}</code>",
                            parse_mode="HTML",
                        )
                    finally:
                        await bot_instance.session.close()
                return web.Response(status=200)

            logger.info(f"Veo task {task_id} succeeded: {video_url[:60]}...")

            if not task or not telegram_id:
                logger.warning(f"Veo task {task_id} not found in DB or no telegram_id")
                return web.Response(status=200)

            caption = f"✅ <b>Видео (Veo 3.1) готово!</b>\n\nID: <code>{task_id}</code>"
            if task.duration:
                caption += f"\n⏱ <code>{task.duration}с</code>"
            if task.aspect_ratio:
                caption += f"\n📐 <code>{task.aspect_ratio}</code>"
            if task.cost:
                caption += f"\n💰 <code>{task.cost}🍌</code>"
            if task.prompt:
                caption += f"\n\n🎯 Промпт: <code>{task.prompt[:100]}{'...' if len(task.prompt) > 100 else ''}</code>"

            bot_instance = Bot(token=config.BOT_TOKEN)
            try:
                import os
                import tempfile

                import aiohttp as _aiohttp

                tmp_file = None
                sent = False
                try:
                    async with _aiohttp.ClientSession() as sess:
                        async with sess.get(
                            video_url, timeout=_aiohttp.ClientTimeout(total=120)
                        ) as resp:
                            if resp.status == 200:
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
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        reply_markup=get_video_result_keyboard(video_url),
                    )
                    sent = True
                except Exception as dl_e:
                    logger.warning(
                        f"Veo video download failed ({dl_e}), trying URL send"
                    )
                    try:
                        await bot_instance.send_video(
                            chat_id=telegram_id,
                            video=video_url,
                            caption=caption,
                            parse_mode="HTML",
                            supports_streaming=True,
                            reply_markup=get_video_result_keyboard(video_url),
                        )
                        sent = True
                    except Exception as url_e:
                        logger.error(f"Veo URL send failed: {url_e}")
                finally:
                    if tmp_file and os.path.exists(tmp_file):
                        try:
                            os.remove(tmp_file)
                        except Exception:
                            pass

                if sent:
                    await complete_video_task(task_id, video_url)
                else:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"{caption}\n\n🔗 <a href='{video_url}'>📥 Ссылка на видео</a>",
                        parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
                    await complete_video_task(task_id, video_url)
                logger.info(f"Veo video sent to {telegram_id}")
            except Exception as send_e:
                logger.error(f"Veo webhook send error: {send_e}")
            finally:
                await bot_instance.session.close()
        else:
            # Failure
            msg = data.get("msg", "Unknown error")
            logger.error(f"Veo task {task_id} failed: code={code}, msg={msg}")
            if task and task.cost and task.cost > 0 and telegram_id:
                await add_credits(telegram_id, task.cost)
            if telegram_id:
                bot_instance = Bot(token=config.BOT_TOKEN)
                try:
                    await bot_instance.send_message(
                        chat_id=telegram_id,
                        text=f"❌ <b>Veo 3.1: ошибка генерации</b>\nID: <code>{task_id}</code>\n{msg}\n🍌 Кредиты возвращены.",
                        parse_mode="HTML",
                    )
                finally:
                    await bot_instance.session.close()
            await complete_video_task(task_id, None)

        return web.Response(status=200)

    except Exception as e:
        logger.exception(f"Veo webhook error: {e}")
        return web.Response(status=200)


def setup_web_server(dp: Dispatcher, bot: Bot) -> web.Application:
    """Настройка aiohttp сервера для вебхуков"""
    app = web.Application()
    app["bot"] = bot

    async def app_startup(app: web.Application) -> None:
        await on_startup(bot)

    async def app_cleanup(app: web.Application) -> None:
        await on_shutdown(bot)

    app.on_startup.append(app_startup)
    app.on_cleanup.append(app_cleanup)

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

    # Вебхук Crypto Bot
    app.router.add_post("/cryptobot/webhook", handle_cryptobot_webhook)

    # Вебхук Kling
    app.router.add_post("/webhook/kling", handle_kling_webhook)

    # Вебхук Kie.ai (Nano Banana 2, Seedream, Hailuo, Grok Image)
    app.router.add_post(config.KIE_AI_WEBHOOK_PATH, handle_kie_ai_webhook)

    # Вебхук Veo 3.1
    app.router.add_post("/webhook/veo", handle_veo_webhook)

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

        site = web.TCPSite(runner, config.WEBHOOK_BIND_HOST, config.WEBHOOK_PORT)
        await site.start()

        logger.info(
            f"Server started on {config.WEBHOOK_BIND_HOST}:{config.WEBHOOK_PORT}"
        )

        # Держим бота запущенным
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
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
