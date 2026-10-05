"""Production composition. No provider call or balance mutation happens on import."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiohttp import web

from .api import API
from .contract import PipelineError, integer
from .delivery import Delivery, DeliveryFailure, TerminalNotifications
from .feed import FeedPublisher, copy_public_output
from .media import MediaStore
from .pipeline import Pipeline
from .provider import Higgsfield
from .recipes import RecipeStore
from .repository import Repository

logger = logging.getLogger(__name__)
RUNTIME_KEY = web.AppKey('genjutsu_pipeline', Pipeline)


def studio_url(base: str, *, run_id: str | None = None, recipe_id: str | None = None) -> str:
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query['genjutsu'] = '1'
    if run_id:
        query['genjutsu_run'] = run_id
    if recipe_id:
        query['genjutsu_recipe'] = recipe_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def send_terminal_notification(bot, base: str, owner: int, text: str, run_id: str, timeout: int) -> str:
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
    )
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text='Открыть работу', web_app=WebAppInfo(url=studio_url(base, run_id=run_id)))]] )
    try:
        message = await bot.send_message(owner, text, parse_mode=None, reply_markup=keyboard,
                                         request_timeout=timeout)
    except TelegramRetryAfter as exc:
        raise DeliveryFailure('rate_limited', retry_after=int(exc.retry_after)) from exc
    except TelegramForbiddenError as exc:
        raise DeliveryFailure('chat_unavailable') from exc
    except TelegramBadRequest as exc:
        code = 'chat_unavailable' if any(v in str(exc).lower() for v in ('chat not found', 'user is deactivated')) else 'message_rejected'
        raise DeliveryFailure(code) from exc
    return str(message.message_id)


async def authenticate(request: web.Request, body: dict) -> tuple[int, bool]:
    from bot.config import config
    from bot.database import is_user_banned
    from bot.miniapp import _get_user_context

    init_data = body.get('init_data')
    if not isinstance(init_data, str) or not init_data:
        raise PipelineError('unauthorized', status=401)
    try:
        owner, _ = await _get_user_context(request.app, init_data, body.get('start_param_fallback'))
    except ValueError as exc:
        raise PipelineError('unauthorized', status=401) from exc
    if await is_user_banned(owner):
        raise PipelineError('user_banned', status=403)
    return owner, config.is_admin(owner)


def setup_genjutsu(app: web.Application, *, base: str = '/mini-app/api') -> None:
    from bot import db as db_backend
    from bot.config import config

    @asynccontextmanager
    async def connect():
        async with db_backend.connect() as db:
            db.row_factory = db_backend.Row
            yield db

    repository = Repository(connect)
    provider = Higgsfield(
        config.HIGGSFIELD_API_KEY.strip(),
        base_url=config.HIGGSFIELD_API_BASE_URL.strip(),
    )
    media = MediaStore(
        Path(config.GENJUTSU_MEDIA_ROOT),
        (config.GENJUTSU_PUBLIC_BASE_URL or config.WEBHOOK_HOST or '').strip(),
        config.GENJUTSU_MEDIA_SIGNING_KEY,
    )
    recipes = RecipeStore(repository)
    repository.start_validator = recipes.validate_start
    pipeline = Pipeline(repository, provider, media, plan_resolver=recipes.resolve_project)
    app[RUNTIME_KEY] = pipeline

    async def import_owned(owner: int, body: dict) -> dict:
        from bot.database import get_saved_reference_by_id
        from bot.miniapp import _fetch_task_detail
        from bot.services.media_input_utils import resolve_local_upload_path

        reference_id, task_id = body.get('saved_reference_id'), body.get('task_id')
        if (reference_id is None) == (task_id is None):
            raise PipelineError('one_import_source_required')
        if reference_id is not None:
            reference = await get_saved_reference_by_id(owner, integer(reference_id, 1, 2**53 - 1, 'invalid_reference'))
            if not reference:
                raise PipelineError('asset_unavailable', status=404)
            source_url, kind = reference.file_url, reference.kind
        else:
            if not isinstance(task_id, str) or not 1 <= len(task_id) <= 200:
                raise PipelineError('invalid_task_id')
            detail = await _fetch_task_detail(owner, task_id)
            if not detail or detail['status'] != 'completed' or detail['type'] != 'video':
                raise PipelineError('result_unavailable', status=404)
            source_url, kind = detail.get('result_url'), 'video'
        path = resolve_local_upload_path(source_url or '')
        if not path:
            raise PipelineError('asset_file_unavailable', status=404)
        candidate = Path(path).resolve()
        if not candidate.is_relative_to(Path('static/uploads').resolve()) or not candidate.is_file():
            raise PipelineError('asset_file_unavailable', status=404)
        async def chunks():
            with candidate.open('rb') as stream:
                while chunk := await asyncio.to_thread(stream.read, 262144):
                    yield chunk
        return await pipeline.store_upload(owner, kind, chunks())

    async def send(owner, asset, run_id, timeout):
        from aiogram.exceptions import (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramRetryAfter,
        )
        from aiogram.types import (
            FSInputFile,
            InlineKeyboardButton,
            InlineKeyboardMarkup,
            WebAppInfo,
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text='Открыть работу', web_app=WebAppInfo(url=studio_url(config.mini_app_url, run_id=run_id)))]] )
        try:
            if asset['size_bytes'] > 48 * 1024 * 1024:
                # The durable studio always resolves a fresh private media link.
                message = await app['bot'].send_message(owner,
                    'Genjutsu: видео готово. Откройте работу, чтобы посмотреть и скачать исходный файл.',
                    reply_markup=keyboard, request_timeout=timeout)
            else:
                message = await app['bot'].send_video(owner, FSInputFile(media.path(asset['storage_key'])),
                    caption='Genjutsu: видео готово.', reply_markup=keyboard,
                    supports_streaming=True, request_timeout=timeout)
        except TelegramRetryAfter as exc:
            raise DeliveryFailure('rate_limited', retry_after=int(exc.retry_after)) from exc
        except TelegramForbiddenError as exc:
            raise DeliveryFailure('chat_unavailable') from exc
        except TelegramBadRequest as exc:
            code = 'chat_unavailable' if any(v in str(exc).lower() for v in ('chat not found', 'user is deactivated')) else 'media_rejected'
            raise DeliveryFailure(code) from exc
        return str(message.message_id)

    async def publish_output(asset, step_id):
        from bot.services.feed_persist import FEED_STORAGE_DIR

        return await copy_public_output(media, asset, step_id, directory=FEED_STORAGE_DIR,
                                        base_url=config.static_base_url)

    feed = FeedPublisher(repository, recipes, publish_output)
    API(pipeline, authenticate, importer=import_owned, recipes=recipes, feed=feed).register(app, base=base)
    delivery = Delivery(pipeline, send)

    async def send_notice(owner, text, run_id, timeout):
        return await send_terminal_notification(app['bot'], config.mini_app_url, owner, text, run_id, timeout)

    notifications = TerminalNotifications(repository, send_notice)

    async def lifecycle(application):
        await repository.migrate()
        await recipes.migrate()
        stop = asyncio.Event()
        tasks = [asyncio.create_task(pipeline.worker(stop), name='genjutsu-generation'),
                 asyncio.create_task(delivery.worker(stop), name='genjutsu-delivery'),
                 asyncio.create_task(notifications.worker(stop), name='genjutsu-notifications')]
        logger.info('genjutsu_runtime_started', extra={
            'provider_configured': provider.configured, 'media_configured': media.configured})
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app.cleanup_ctx.append(lifecycle)
