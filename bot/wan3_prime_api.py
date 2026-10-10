from __future__ import annotations

import logging
from functools import wraps
from typing import Any

from aiohttp import web

from bot.services.wan3_prime_lifecycle import (
    Wan3PrimeActor,
    Wan3PrimeLifecycleError,
    wan3_prime_lifecycle,
)
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import wan3_prime_storage

logger = logging.getLogger(__name__)


async def _actor_from_request(request: web.Request, body: dict[str, Any]) -> Wan3PrimeActor:
    init_data = str(
        request.headers.get("X-Telegram-Init-Data")
        or body.get("initData")
        or body.get("init_data")
        or ""
    )
    start_param = body.get("start_param_fallback") or body.get("start_param")
    if not init_data:
        raise Wan3PrimeLifecycleError("initData is required", status=401, code="auth_required")
    from bot import miniapp
    from bot.config import config
    from bot.database import is_user_banned

    try:
        telegram_id, context = await miniapp._get_user_context(request.app, init_data, start_param)
    except ValueError as exc:
        raise Wan3PrimeLifecycleError("Откройте Mini App заново из Telegram.", status=401, code="auth_invalid") from exc
    if await is_user_banned(int(telegram_id)):
        raise Wan3PrimeLifecycleError("Доступ к генерации ограничен.", status=403, code="user_banned")
    user = context.get("user")
    user_id = int(getattr(user, "id", 0) or context.get("user_id") or 0)
    if not user_id:
        db_user = await miniapp.get_or_create_user(telegram_id)
        user_id = int(db_user.id)
    return Wan3PrimeActor(
        user_id=user_id,
        telegram_id=int(telegram_id),
        is_admin=bool(config.is_admin(int(telegram_id))),
        miniapp_context=context,
    )


def _json_error(message: str, *, status: int = 400, code: str = "wan3_error") -> web.Response:
    response = web.json_response({"ok": False, "error": message, "code": code}, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _json_ok(payload: dict[str, Any], *, status: int = 200) -> web.Response:
    response = web.json_response(payload, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _lifecycle(request: web.Request):
    return request.app.get("wan3_prime_lifecycle", wan3_prime_lifecycle)


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Wan3PrimeValidationError("Malformed JSON") from exc
    if not isinstance(payload, dict):
        raise Wan3PrimeValidationError("Request body must be an object")
    return payload


def _recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = payload.get("recipe")
    if isinstance(recipe, dict):
        return dict(recipe)
    return dict(payload)


def _quote_response(quote) -> dict[str, Any]:
    from bot.services.wan3_models import wan3_model_spec
    from bot.services.wan3_prime_storage_policy import positive_setting

    model = wan3_model_spec(getattr(quote, "safe_request", {}).get("model"))
    auto = quote.requested_output_seconds is None
    retention_days = positive_setting('WAN3_RESULT_RETENTION_SECONDS', 30 * 86400) / 86400
    notice = f'Неопубликованный оригинал хранится на сервере {retention_days:g} дн. после генерации; скачайте его. Опубликованные и ещё не доставленные работы сохраняются.'
    if not auto:
        notice = 'Цена фиксируется за входное видео и выбранную длительность результата. ' + notice
    if auto:
        notice = 'Auto резервирует максимум 30 суммарных видеосекунд; неиспользованная часть возвращается после проверки результата. ' + notice
    return {
        "ok": True,
        "quote_hash": quote.quote_hash,
        "model": model.key,
        "provider_model": model.provider_model,
        "reserve_cost": quote.reserve_credits,
        "estimated_final_cost": None if auto else quote.reserve_credits,
        "billing_duration_seconds": quote.billable_seconds_reserved,
        "source_video_duration_seconds": quote.input_video_seconds,
        "tariff_missing": not quote.price_configured,
        "admin_free": quote.admin_free,
        "auto_duration": auto,
        "billing_version": 2,
        "billing_mode": "auto_reserve" if auto else "input_plus_selected_output",
        "settlement_notice": notice,
    }


async def _launch_response(actor, result):
    state = str(result.get('status') or 'unknown')
    public_state = ('done' if state == 'completed' else 'failed' if state == 'failed' else
                    'unknown' if state in {'unknown', 'submitting'} else
                    'accepted' if result.get('provider_task_id') else 'queued')
    payload = {
        'ok': True, 'status': public_state,
        'task_id': result['task_id'], 'internal_task_id': result['internal_task_id'],
        'provider_task_id': result.get('provider_task_id'),
        'model': result.get('model', 'wan_3_prime'),
        'provider_model': result.get('provider_model', 'wan/3-0-video-prime'),
        'reserve_cost': result.get('reserve_amount', 0),
        'charged_cost': result.get('charged_credits', 0),
        'refunded_cost': result.get('refunded_credits', 0),
    }
    # A debit/settlement is not the remaining user balance. Never publish it as credits.
    try:
        from bot.database import get_or_create_user
        payload['credits'] = (await get_or_create_user(actor.telegram_id)).credits
    except Exception as exc:  # noqa: BLE001 - an acknowledged provider task must not become a failed launch
        logger.warning("Wan3 accepted balance refresh deferred: task_id=%s error_type=%s", result['task_id'], type(exc).__name__)
    return payload


async def miniapp_generate_wan(request: web.Request, body: dict[str, Any] | None = None) -> web.Response:
    try:
        payload = body if body is not None else await _json_body(request)
        if not isinstance(payload, dict):
            return _json_error("Request body must be an object")
        actor = await _actor_from_request(request, payload)
        lifecycle = _lifecycle(request)
        recipe = _recipe_payload(payload)
        for flag in ('quoteOnly', 'quote_only'):
            if flag in payload and not isinstance(payload[flag], bool):
                raise Wan3PrimeValidationError('Quote-only must be a boolean')
        if payload.get("quoteOnly") is True or payload.get("quote_only") is True:
            quote = await lifecycle.quote(actor, recipe)
            return _json_ok(_quote_response(quote))
        idempotency_key = str(
            payload.get("idempotency_key")
            or payload.get("idempotencyKey")
            or request.headers.get("Idempotency-Key")
            or ""
        )
        supplied_quote = {"quote_hash": str(payload.get("quote_hash") or payload.get("quotehash") or "")}
        result = await lifecycle.launch(actor, recipe, supplied_quote, idempotency_key)
        return _json_ok(await _launch_response(actor, result))
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)
    except PermissionError as exc:
        return _json_error(str(exc), status=403, code="permission_denied")
    except web.HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - public boundary, preserve uncertain submissions and keep secrets out of responses
        logger.error("Wan3 request failed: error_type=%s", type(exc).__name__)
        return _json_error("Не удалось подтвердить операцию. Повторите проверку с тем же идентификатором.", status=500, code="internal_error")


async def _quote_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        body = {**body, "quoteOnly": True}
        return await miniapp_generate_wan(request, body)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")


async def _launch_route(request: web.Request) -> web.Response:
    return await miniapp_generate_wan(request)


async def _status_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        task_id = str(body.get("task_id") or body.get("internal_task_id") or "")
        result = await _lifecycle(request).status(actor, task_id)
        return _json_ok(result)
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _callback_route(request: web.Request) -> web.Response:
    import json

    from bot.services.wan3_prime_callback_auth import (
        nonce_callbacks_enabled,
        signed_callbacks_enabled,
    )

    if not nonce_callbacks_enabled() and (not signed_callbacks_enabled() or not request.headers.get('X-Webhook-Signature')):
        return _json_error('Callback authentication required', status=403, code='callback_auth_required')
    raw = bytearray()
    async for chunk in request.content.iter_chunked(8192):
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            return _json_error('Callback payload too large', status=413)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _json_error('Malformed callback JSON', status=400)
    _result, status = await _lifecycle(request).handle_callback(
        payload,
        internal_task_id=request.query.get('intent'),
        nonce=request.query.get('nonce'),
        headers=request.headers,
    )
    return _json_ok({'ok': status < 400}, status=status)


async def _import_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        result = await wan3_prime_storage.import_url(actor, kind=str(body.get("kind") or ""), url=str(body.get("url") or ""))
        return _json_ok(result)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _upload_init_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        result = await wan3_prime_storage.init_upload(
            actor,
            kind=str(body.get("kind") or ""),
            filename=str(body.get("filename") or ""),
            size=body.get("size"),
            content_type=str(body.get("content_type") or ""),
            upload_id=body.get("upload_id"),
        )
        return _json_ok(result)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="upload_session_conflict" if exc.status == 409 else "validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _upload_chunk_route(request: web.Request) -> web.Response:
    try:
        from bot.services.wan3_prime_storage import CHUNK_SIZE
        init_data = request.headers.get('X-Telegram-Init-Data')
        if not init_data:
            raise Wan3PrimeLifecycleError('Откройте Mini App из Telegram.', status=401, code='auth_required')
        actor = await _actor_from_request(request, {'init_data': init_data})
        reader = await request.multipart()
        fields = {}
        chunk = None
        seen = set()
        async for part in reader:
            name = part.name or ''
            if name not in {'upload_id', 'index', 'total', 'chunk', 'init_data', 'start_param_fallback'} or name in seen:
                raise Wan3PrimeValidationError('Повторяющееся или неизвестное поле загрузки.')
            seen.add(name)
            limit = CHUNK_SIZE if name == 'chunk' else 8192
            value = bytearray()
            while True:
                block = await part.read_chunk(8192)
                if not block:
                    break
                value.extend(block)
                if len(value) > limit:
                    raise Wan3PrimeValidationError('Часть файла превышает допустимый размер.', status=413)
            if name == 'chunk':
                chunk = bytes(value)
            else:
                fields[name] = value.decode('utf-8')
        if chunk is None or not {'upload_id', 'index', 'total'} <= fields.keys():
            raise Wan3PrimeValidationError('Не хватает данных для загрузки.')
        if not fields['index'].isdigit() or not fields['total'].isdigit():
            raise Wan3PrimeValidationError('Неверный номер части файла.')
        await wan3_prime_storage.save_chunk(actor, upload_id=fields['upload_id'],
            index=int(fields['index']), total=int(fields['total']), chunk=chunk)
        return _json_ok({'ok': True})
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code='validation_error')
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _upload_complete_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        result = await wan3_prime_storage.complete_upload(actor, upload_id=str(body.get("upload_id") or ""))
        return _json_ok(result)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _upload_cancel_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        result = await wan3_prime_storage.cancel_upload(actor, upload_id=body.get("upload_id"))
        return _json_ok(result)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _recipe_route(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        recipe = await _lifecycle(request).owner_recipe(actor, str(body.get("task_id") or ""))
        return _json_ok({"ok": True, "recipe": recipe, "private_media_redacted": bool(recipe.get("source_feed_gen_id") or recipe.get("trend_id"))})
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _repeat_plan_route(request: web.Request) -> web.Response:
    from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan

    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        if body.get("trend_id") is not None:
            if body.get("source_feed_gen_id") is not None:
                raise Wan3PrimeValidationError("Choose exactly one repeat source")
            from bot.services.wan3_prime_trends import get_trend_plan
            return _json_ok(public_plan(await get_trend_plan(actor, body["trend_id"])))
        return _json_ok(public_plan(await get_repeat_plan(actor, body.get("source_feed_gen_id"))))
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def repeat_plan_telegram_wan3_prime(*, telegram_id: int, source_id: int) -> dict:
    from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan

    return public_plan(await get_repeat_plan(await _telegram_actor(telegram_id), source_id))


async def trend_plan_telegram_wan3_prime(*, telegram_id: int, trend_id: int) -> dict:
    from bot.services.wan3_prime_repeat import public_plan
    from bot.services.wan3_prime_trends import get_trend_plan

    return public_plan(await get_trend_plan(await _telegram_actor(telegram_id), trend_id))


async def _trend_recipe_route(request: web.Request) -> web.Response:
    from bot.services.wan3_prime_trends import publication_recipe

    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        plan = await publication_recipe(actor, str(body.get("task_id") or ""))
        return _json_ok({"ok": True, "recipe": plan["recipe"], "slots": plan["slots"]})
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


async def _trend_publish_route(request: web.Request) -> web.Response:
    from bot.services.wan3_prime_trends import publish_trend

    try:
        body = await _json_body(request)
        actor = await _actor_from_request(request, body)
        result = await publish_trend(actor, task_id=str(body.get("task_id") or ""), title=body.get("title"),
                                     description=body.get("description", ""), replacement_keys=body.get("replacement_keys"))
        return _json_ok(result)
    except Wan3PrimeValidationError as exc:
        return _json_error(str(exc), status=exc.status, code="validation_error")
    except Wan3PrimeLifecycleError as exc:
        return _json_error(str(exc), status=exc.status, code=exc.code)


def _http_boundary(handler):
    """Consistent errors for every Wan route, not only the generation endpoint."""
    @wraps(handler)
    async def wrapped(request):
        try:
            return await handler(request)
        except Wan3PrimeValidationError as exc:
            return _json_error(str(exc), status=exc.status, code="validation_error")
        except Wan3PrimeLifecycleError as exc:
            return _json_error(str(exc), status=exc.status, code=exc.code)
        except PermissionError:
            return _json_error("Нет доступа к этой операции.", status=403, code="permission_denied")
        except (ValueError, UnicodeError):
            return _json_error("Некорректные данные запроса.", status=400, code="validation_error")
        except web.HTTPException as exc:
            return _json_error("Запрос не может быть обработан.", status=exc.status, code="http_error")
        except Exception as exc:  # noqa: BLE001 - HTTP service boundary maps unexpected errors without leaking request data
            logger.error("Wan3 HTTP boundary failure: path=%s error_type=%s", request.path, type(exc).__name__)
            return _json_error("Операция временно недоступна.", status=500, code="internal_error")
    return wrapped


def setup_wan3_prime_routes(app: web.Application, miniapp_root: str = "/mini-app") -> None:
    wan3_prime_lifecycle.miniapp_root = miniapp_root
    app["wan3_prime_lifecycle"] = app.get("wan3_prime_lifecycle", wan3_prime_lifecycle)

    async def _startup(_app: web.Application) -> None:
        _app["wan3_prime_lifecycle"].telegram_bot = _app.get("bot")
        await wan3_prime_storage.init_schema()
        await _app["wan3_prime_lifecycle"].startup()
        await _app["wan3_prime_lifecycle"].start_worker()

    async def _cleanup(_app: web.Application) -> None:
        await _app["wan3_prime_lifecycle"].cleanup()

    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    app.router.add_post(f"{miniapp_root}/api/wan3/quote", _http_boundary(_quote_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/generate", _http_boundary(_launch_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/launch", _http_boundary(_launch_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/status", _http_boundary(_status_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/recipe", _http_boundary(_recipe_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/repeat-plan", _http_boundary(_repeat_plan_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/trends/recipe", _http_boundary(_trend_recipe_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/trends/publish", _http_boundary(_trend_publish_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/callback", _http_boundary(_callback_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/import", _http_boundary(_import_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/upload/init", _http_boundary(_upload_init_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/upload/chunk", _http_boundary(_upload_chunk_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/upload/complete", _http_boundary(_upload_complete_route))
    app.router.add_post(f"{miniapp_root}/api/wan3/upload/cancel", _http_boundary(_upload_cancel_route))


async def _telegram_actor(telegram_id: int) -> Wan3PrimeActor:
    from bot.config import config
    from bot.database import get_or_create_user
    if isinstance(telegram_id, bool) or not isinstance(telegram_id, int) or telegram_id <= 0:
        raise Wan3PrimeValidationError('Некорректный пользователь Telegram.')
    from bot.database import is_user_banned

    if await is_user_banned(telegram_id):
        raise Wan3PrimeLifecycleError("Доступ к генерации ограничен.", status=403, code="user_banned")
    user = await get_or_create_user(telegram_id)
    return Wan3PrimeActor(user.id, telegram_id, is_admin=config.is_admin(telegram_id))


async def quote_telegram_wan3_prime(*, telegram_id: int, client_request_id: str, recipe: dict) -> dict:
    actor = await _telegram_actor(telegram_id)
    return _quote_response(await wan3_prime_lifecycle.quote(actor, recipe))


async def launch_telegram_wan3_prime(*, telegram_id: int, client_request_id: str, idempotency_key: str, quote_hash: str, recipe: dict) -> dict:
    actor = await _telegram_actor(telegram_id)
    result = await wan3_prime_lifecycle.launch(actor, recipe, {'quote_hash': quote_hash}, idempotency_key)
    return await _launch_response(actor, result)


async def import_telegram_wan3_prime_reference(*, telegram_id: int, kind: str, url: str) -> dict:
    return await wan3_prime_storage.import_url(await _telegram_actor(telegram_id), kind=kind, url=url)


async def owner_telegram_wan3_prime_recipe(*, telegram_id: int, task_id: str) -> dict:
    return await wan3_prime_lifecycle.owner_recipe(await _telegram_actor(telegram_id), task_id)


async def store_telegram_wan3_prime_media(*, telegram_id: int, bot, file_id: str, filename: str, kind: str, declared_size: int | None) -> dict:
    import asyncio
    import io
    from pathlib import Path

    from bot.services.wan3_prime_files import convert_voice_to_mp3
    from bot.services.wan3_prime_media import canonical_child_path
    from bot.services.wan3_prime_storage import CHUNK_ROOT, _kind_limit, _safe_basename

    actor = await _telegram_actor(telegram_id)
    maximum = min(_kind_limit(kind), 20 * 1024 * 1024)
    if not maximum or declared_size is not None and (isinstance(declared_size, bool) or declared_size < 0 or declared_size > maximum):
        raise Wan3PrimeValidationError('Use Mini App to upload files beyond the Telegram download limit.')
    name = _safe_basename(filename)
    convert_audio = kind == 'audio' and Path(name).suffix.lower() in {'.ogg', '.oga', '.m4a'}
    output_name = 'voice.mp3' if convert_audio else name
    # Quota reservation precedes file download, including Telegram's temp bytes.
    reservation = await wan3_prime_storage.init_upload(actor, kind=kind, filename=output_name,
        size=maximum if convert_audio or not declared_size else declared_size, importing=True)
    upload_id = reservation['upload_id']
    path = canonical_child_path(CHUNK_ROOT, f'{upload_id}/{name}')

    class BoundedFile(io.BufferedWriter):
        def write(self, data):
            if self.tell() + len(data) > maximum:
                raise Wan3PrimeValidationError('File exceeds the Telegram download limit; use Mini App.')
            return super().write(data)
    try:
        from bot.services.wan3_prime_probe_cache import probe_slot

        async with probe_slot(actor.user_id):
            with BoundedFile(io.FileIO(path, 'w')) as output:
                await bot.download(file_id, destination=output, timeout=90, seek=False)
            if convert_audio:
                converted = path.with_name('voice-converted.mp3')
                conversion = asyncio.create_task(asyncio.to_thread(convert_voice_to_mp3, path, converted))
                try:
                    await asyncio.shield(conversion)
                except asyncio.CancelledError:
                    await asyncio.shield(conversion)
                    raise
                path = converted
        return await wan3_prime_storage.save_owned_file(actor, kind=kind, filename=output_name,
            path=path, source='telegram_wan3', upload_id=upload_id)
    finally:
        await wan3_prime_storage.discard_import(actor, upload_id)

