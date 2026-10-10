"""Public-release compatibility layer for Seedance 2.5.

The feature branch originally carried Seedance 2.5 as an admin-only preview.
This module flips the already-tested provider/UI seams to a normal user model
without touching tanyapi:

* Seedance 2.5 is visible to every user and is the only model marked NEW;
* admins keep the established free-generation behaviour;
* regular users are balance-checked and charged before provider launch;
* immediate provider launch failures are refunded;
* asynchronous provider failures claim an idempotent refund marker before the
  dedicated webhook marks the task failed;
* public Telegram/Mini App copy no longer says "admin preview".
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from aiohttp import web
from aiogram import F, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.creator_tariff import VideoQuote, quote_video_for_actor, resolve_video_quote
from bot.services.delivery_state import (
    TelegramDeliveryUncertain,
    tracked_telegram_send,
    TelegramDeliveryRetryable,
    telegram_delivery_retry_delay,
    telegram_delivery_is_definitely_rejected,
    is_terminal_telegram_delivery_error,
    terminal_telegram_delivery_reason,
)
from bot.services.preset_manager import preset_manager
from bot.services.seedance25_identity import (
    IDENTITY_ROLE_VERSION,
    SEEDANCE_25_PROMPT_MAX_CHARS as IDENTITY_PROMPT_MAX_CHARS,
    resolve_identity_transfer_prompt,
    validate_identity_transfer_refs,
)
from bot.video_reference_policy import apply_video_reference_cost
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

from . import generation as generation_module
from . import seedance_25_fullstack as fullstack
from . import seedance_25_preview as preview_module

logger = logging.getLogger(__name__)
MODEL_KEY = "seedance_2_5"


class _PublicVideoAccessError(ValueError):
    """Fixed permission messages are safe to show without revealing recipe data."""


_NEW_MARKERS_RE = re.compile(
    r"(?:\s+NEW(?:🔥+)?|\s+🔥\s*НОВИНКА|\s+НОВИНКА|\s+🆕)",
    flags=re.IGNORECASE,
)


def _public_feature_access(user_id: int | None) -> bool:
    """Seedance feature access is public; authentication still happens upstream."""
    return user_id is not None


def _clean_other_new_markers(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _NEW_MARKERS_RE.sub("", str(text or ""))).strip()


def _copy_button_with_text(button: types.InlineKeyboardButton, text: str):
    try:
        return button.model_copy(update={"text": text})
    except AttributeError:
        button.text = text
        return button


def _public_video_model_keyboard(original):
    @wraps(original)
    def wrapped(current_model: str = "v3_pro", user_id: int | None = None, *, tariff: str = "standard"):
        markup = original(current_model, user_id=user_id, **({"tariff": tariff} if tariff != "standard" else {}))
        rows: list[list[types.InlineKeyboardButton]] = []
        has_seedance = False
        insert_after = None

        for row_index, row in enumerate(markup.inline_keyboard):
            cleaned_row: list[types.InlineKeyboardButton] = []
            for button in row:
                callback = str(button.callback_data or "")
                if callback == "v_model_seedance_2_5":
                    has_seedance = True
                    label = _seedance_public_button_text(current_model, tariff=tariff)
                    cleaned_row.append(_copy_button_with_text(button, label))
                    continue
                cleaned_row.append(
                    _copy_button_with_text(button, _clean_other_new_markers(button.text))
                )
                if callback == "v_model_seedance_2":
                    insert_after = row_index
            rows.append(cleaned_row)

        if not has_seedance:
            seedance_button = types.InlineKeyboardButton(
                text=_seedance_public_button_text(current_model, tariff=tariff),
                callback_data="v_model_seedance_2_5",
            )
            index = (insert_after + 1) if insert_after is not None else max(len(rows) - 1, 0)
            rows.insert(index, [seedance_button])

        return types.InlineKeyboardMarkup(inline_keyboard=rows)

    return wrapped


def _clean_keyboard_new_markers(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        markup = original(*args, **kwargs)
        rows = [
            [
                _copy_button_with_text(button, _clean_other_new_markers(button.text))
                for button in row
            ]
            for row in markup.inline_keyboard
        ]
        return types.InlineKeyboardMarkup(inline_keyboard=rows)

    return wrapped


def _seedance_public_button_text(current_model: str, *, tariff: str = "standard") -> str:
    check = "✅ " if current_model == MODEL_KEY else ""
    quote = resolve_video_quote(MODEL_KEY, 5, "720p", tariff=tariff)
    per_second = preset_manager._format_cost(quote.cost / 5)
    return f"{check}🆕 Seedance 2.5 NEW • {per_second}🍌/с"


def _public_model_meta(*, tariff: str = "standard") -> dict[str, Any]:
    meta = fullstack._seedance25_model_meta_original(tariff=tariff)
    meta.update(
        {
            "label": "🆕 Seedance 2.5 NEW",
            "description": "Новая Bytedance video-модель: текст, first/last frame и мультимодальные фото/видео/аудио референсы",
            "admin_only": False,
            "is_new": True,
        }
    )
    return meta


def _duration_label(value: int) -> str:
    return "Auto" if int(value) == -1 else f"{int(value)}с"


async def _public_show_screen(target, state: FSMContext, *, edit: bool = True, actor_id: int | None = None) -> None:
    data = await state.get_data()
    scenario = data.get("seedance25_scenario", "text")
    first = bool(data.get("seedance25_first_frame_url"))
    last = bool(data.get("seedance25_last_frame_url"))
    images = len(data.get("reference_images") or [])
    videos = len(data.get("v_reference_videos") or [])
    audios = len(data.get("seedance25_reference_audio_urls") or [])
    user_id = actor_id if actor_id is not None else getattr(getattr(target, "from_user", None), "id", None)
    is_admin = bool(user_id and config.is_admin(int(user_id)))
    identity = data.get("seedance25_identity_transfer") is True
    editing = data.get("seedance25_video_editing") is True or identity
    display_data = dict(data, seedance25_editing_allowed=is_admin)
    if editing:
        display_data.update(v_duration=-1, v_ratio="adaptive")
    duration = int(display_data.get("v_duration", 5))
    quote = None
    identity_error = ""
    if identity:
        try:
            identity_payload = _scenario_payload(data, "")
            await _validate_public_payload(identity_payload, is_admin=is_admin, telegram_id=user_id)
            row = await _prepare_measured_quote(user_id, identity_payload)
            billing_quote = VideoQuote(**json.loads(row["billing_json"]))
            current_quote = _identity_quote(identity_payload, cost=billing_quote.cost)
            quote = current_quote["cost"]
            await state.update_data(seedance25_identity_quote=current_quote)
        except ValueError as exc:
            identity_error = str(exc)
            await state.update_data(seedance25_identity_quote=None)
    else:
        pricing_payload = _scenario_payload(display_data, "")
        try:
            if _needs_measured_quote(pricing_payload):
                row = await _prepare_measured_quote(user_id, pricing_payload)
                billing_quote = VideoQuote(**json.loads(row["billing_json"]))
            else:
                billing_quote = await _payload_quote(user_id, pricing_payload)
            quote = billing_quote.cost
        except ValueError as exc:
            identity_error = str(exc)

    if scenario == "first_frame":
        media_hint = f"Загрузите <b>1 фото</b> как первый кадр. Сейчас: {'✅' if first else '—'}"
    elif scenario == "first_last":
        media_hint = (
            "Загрузите последовательно <b>2 фото</b>: первый и последний кадры. "
            f"Сейчас: первый {'✅' if first else '—'}, последний {'✅' if last else '—'}"
        )
    elif scenario == "multimodal":
        media_hint = (
            "Можно присылать фото / видео / аудио прямо сюда. "
            f"Фото <code>{images}/30</code>, видео <code>{videos}/10</code>, "
            f"аудио <code>{audios}/10</code>. Видео суммарно ≤30с."
        )
        if editing:
            media_hint = (
                "Редактирование: загрузите <b>одно исходное видео 4–30с</b>. "
                "Длительность и формат кадра сохраняются из исходника. "
                "Для внешних ссылок длительность проверяет провайдер. "
                f"Сейчас видео: <code>{videos}/1</code>."
            )
    else:
        media_hint = "Медиа не требуется — отправьте текстовый промпт."

    if identity:
        media_hint = (
            "Прямая замена: <b>1–3 фото одного человека</b> и <b>одно исходное видео 4–30с</b>. "
            "Фото и видео отправляются прямо в Seedance, без промежуточных кадров. "
            "Полный промпт с @Image1 и @Video1 идёт без шаблона; короткие пожелания дополнят команду замены. "
            f"Сейчас фото: <code>{images}/3</code>, видео: <code>{videos}/1</code>."
        )
    if identity and quote is not None:
        media_hint += f" Исходник: <b>{identity_payload['source_video_duration_seconds']:g}с</b>."
    billing_line = (
        f"💰 Цена: <code>{quote}</code>🍌. Для администратора списание отключено."
        if is_admin
        else f"💰 Цена: <code>{quote}</code>🍌 — будет списана при запуске."
    )
    if quote is None:
        billing_line = "Цена появится после проверки загруженных фото и видео. " + identity_error
    elif billing_quote.version == 2:
        billing_line += (f" Вход {billing_quote.input_seconds:g}с + "
                         f"результат {billing_quote.selected_output_seconds:g}с.")
    auto_note = (
        "\n⚠️ Auto сейчас доступен только администратору: для пользователей выберите 4–30с."
        if duration == -1 and not is_admin and not identity
        else ""
    )
    text = (
        "🆕 <b>Seedance 2.5 · NEW</b>\n\n"
        f"Сценарий: <b>{'Замена персонажа' if identity else preview_module._scenario_label(scenario)}</b>\n"
        f"Качество: <code>{data.get('seedance25_resolution', '720p')}</code> · "
        f"Формат кадра: <code>{display_data.get('v_ratio', 'adaptive')}</code> · "
        f"Длительность: <code>{_duration_label(duration)}</code>\n"
        f"Выход: <code>{data.get('seedance25_output_format', 'mp4')}</code> · "
        f"аудио: <code>{'on' if data.get('seedance25_generate_audio', True) else 'off'}</code>\n"
        f"Web search: <code>{'on' if data.get('seedance25_web_search') else 'off'}</code> · "
        f"NSFW checker: <code>{'on' if data.get('seedance25_nsfw_checker') else 'off'}</code> · "
        f"последний кадр: <code>{'yes' if data.get('seedance25_return_last_frame') else 'no'}</code>\n\n"
        f"{media_hint}\n\n"
        "🎥 Движение камеры и lock объектива задавайте прямо в промпте.\n\n"
        f"{billing_line}{auto_note}\n\n"
        f"После настройки отправьте промпт до {IDENTITY_PROMPT_MAX_CHARS if identity else seedance_25_service.MAX_PROMPT_LENGTH} символов."
    )
    markup = preview_module._seedance_25_keyboard(display_data)

    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")

    await state.set_state(generation_module.GenerationStates.waiting_for_video_prompt)


def _identity_intent(data: dict[str, Any]) -> bool:
    identity = data.get("seedance25_identity_transfer", data.get("identityTransfer", False))
    if not isinstance(identity, bool):
        raise ValueError("Некорректный режим переноса персонажа")  # noqa: TRY004 - maps input validation to HTTP 400
    if "identityTransfer" in data and data["identityTransfer"] is not identity:
        raise ValueError("Противоречивый режим переноса персонажа")
    if identity:
        if data.get("seedance25_scenario") != "multimodal":
            raise ValueError("Перенос персонажа требует мультимодальный сценарий")
        validate_identity_transfer_refs(
            images=fullstack._clean_urls(data.get("reference_images") or []),
            videos=fullstack._clean_urls(data.get("v_reference_videos") or []),
            audio=fullstack._clean_urls(data.get("seedance25_reference_audio_urls") or []),
            first_frame=data.get("seedance25_first_frame_url"),
            last_frame=data.get("seedance25_last_frame_url"),
        )
    return identity


def _identity_local_path(source: str, kind: str, telegram_id: int) -> str:
    """Require this user's managed upload, including containment after symlinks."""
    parts = urlsplit(source)
    base = urlsplit(config.static_base_url)
    if (parts.scheme, parts.netloc) != (base.scheme, base.netloc) or parts.username or parts.query or parts.fragment:
        raise ValueError("Используйте исходный URL файла, загруженного в приложение")
    prefix = f"/uploads/refs/{kind}/{int(telegram_id)}/"
    if parts.scheme not in {"http", "https"} or not parts.path.startswith(prefix):
        raise ValueError("Для переноса персонажа загрузите свои фото и исходное видео в приложение")
    suffix = parts.path[len(prefix):]
    if not suffix or any(part in {"", ".", ".."} for part in suffix.split("/")) or "%" in suffix or "\\" in suffix:
        raise ValueError("Некорректный путь исходного референса")
    local = fullstack.resolve_local_upload_path(source)
    root = Path("static/uploads/refs", kind, str(int(telegram_id))).resolve()
    expected = Path("static", parts.path.lstrip("/")).resolve()
    if not local or Path(local).resolve() != expected or not Path(local).resolve().is_relative_to(root) or not Path(local).is_file():
        raise ValueError("Исходный референс недоступен; загрузите его заново")
    return local


def _identity_quote(payload: dict[str, Any], *, cost: float | None = None) -> dict[str, Any]:
    duration = payload["billing_duration"]
    return {
        "cost": float(cost) if cost is not None else float(apply_video_reference_cost(MODEL_KEY, preset_manager.get_video_cost_with_quality(MODEL_KEY, duration, payload["resolution"]), payload["video_urls"])),
        "billing_duration": duration,
        "source_video_url": payload["video_urls"][0],
        "source_feed_gen_id": payload.get("source_feed_gen_id"),
        "parent_generation_id": payload.get("parent_generation_id"),
        "resolution": payload["resolution"],
    }


async def _payload_quote(telegram_id: int | None, payload: dict[str, Any]) -> VideoQuote:
    """Legacy/no-reference quote seam. Measured launches use durable quotes below."""
    duration = payload.get("billing_duration", payload["duration"])
    kwargs = {"duration": 5 if duration == -1 else int(duration),
              "quality": payload["resolution"], "video_references": payload["video_urls"]}
    if telegram_id is None:
        return resolve_video_quote(MODEL_KEY, **kwargs)
    return await quote_video_for_actor(telegram_id, MODEL_KEY, **kwargs)


def _needs_measured_quote(payload):
    return bool(payload["video_urls"] and (payload["duration"] > 0 or payload.get("seedance25_video_editing")))


async def _prepare_measured_quote(telegram_id, payload):
    from bot.services.seedance_quote_lifecycle import prepare_quote

    return await prepare_quote(telegram_id, MODEL_KEY, payload, video_key="video_urls",
                               duration=payload["duration"], quality=payload["resolution"],
                               source_locked=bool(payload.get("seedance25_video_editing")))


async def _bind_measured_seedance25(row):
    from bot.database import get_generation_task_payload
    from bot.services.seedance_quote_lifecycle import receipt_store

    payload = json.loads(row["provider_json"])
    billing = VideoQuote(**json.loads(row["billing_json"]))
    task_id = row["provider_task_id"]
    source_feed_gen_id = payload.get("source_feed_gen_id")
    request_data = _request_data(payload, is_admin=billing.profile == "admin", quote=billing.cost,
                                 source=payload.get("_launch_surface", "miniapp"), billing_quote=billing)
    request_data["seedance_quote_id"] = row["quote_id"]
    for key in ("trend_id", "action_type", "prompt_source_id", "reference_contract", "fixed_asset_counts", "prompt_hidden", "prompt_actions_allowed"):
        if payload.get(key) is not None:
            request_data[key] = payload[key]
    if payload.get("_private_repeat"):
        request_data["video_repeat_contract_version"] = 1
    inserted = await generation_module.add_generation_task(
        row["user_id"], row["telegram_id"], task_id, "video", "no_preset_video", model=MODEL_KEY,
        duration=payload["duration"], aspect_ratio=payload["ratio"], prompt=payload["prompt"],
        cost=row["charged_cost"], request_data=request_data, provider_accepted=True,
        source_feed_gen_id=source_feed_gen_id,
        parent_generation_id=payload.get("parent_generation_id") if source_feed_gen_id else None,
        action_type="repeat" if source_feed_gen_id else payload.get("action_type"),
    )
    if not inserted:
        existing = await get_generation_task_payload(task_id, user_id=int(row["user_id"]))
        raw = existing.get("request_data") if existing else None
        metadata = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(metadata, dict) or metadata.get("seedance_quote_id") != row["quote_id"]:
            raise RuntimeError("Seedance canonical binding does not match quote receipt")
    await (await receipt_store()).mark_bound(row["quote_id"], task_id)
    if payload.get("trend_id"):
        from bot import trend_api
        await trend_api._record_trend_use(payload["trend_id"], row["user_id"], credits_spent=row["charged_cost"], repeat_task_id=task_id)
    if source_feed_gen_id and row["charged_cost"] > 0:
        import bot.miniapp as miniapp_module
        await miniapp_module.credit_feed_prompt_repeat(
            payload.get("parent_generation_id"), row["user_id"], repeat_task_id=task_id,
            credits_spent=row["charged_cost"],
        )


async def _launch_measured_seedance25(telegram_id, payload, quote_id, quote_hash):
    from bot.services.seedance_quote_lifecycle import claim_quote, submit_claimed_quote

    row = await claim_quote(telegram_id, quote_id, quote_hash, payload)
    return await submit_claimed_quote(row, submit=_launch_provider, bind=_bind_measured_seedance25)


async def _measured_miniapp_response(row):
    from bot.database import get_generation_task_payload

    if row["phase"] != "accepted":
        rejected = row["phase"] == "rejected"
        return web.json_response({"ok": False, "quote_id": row["quote_id"],
                                  "code": "video_rejected" if rejected else "video_status_pending",
                                  "error": "Провайдер отклонил запрос. Оплата возвращена." if rejected else
                                  "Исход запуска проверяется. Не запускайте повторно."}, status=409)
    payload = json.loads(row["provider_json"])
    billing = json.loads(row["billing_json"])
    user = await generation_module.get_or_create_user(row["telegram_id"])
    canonical = await get_generation_task_payload(row["provider_task_id"], user_id=int(row["user_id"]))
    canonical_status = canonical.get("status") if canonical else "pending"
    return web.json_response({"ok": True, "status": "done" if canonical_status == "completed" else
                              "failed" if canonical_status == "failed" else "queued",
                              "task_id": row["provider_task_id"], "credits": user.credits,
                              "cost": billing["cost"], "model": MODEL_KEY, "model_label": "Seedance 2.5",
                              "admin_free": billing["profile"] == "admin", "resolution": payload["resolution"],
                              "duration": payload["duration"], "aspect_ratio": payload["ratio"],
                              "scenario": payload["scenario"], "quote_id": row["quote_id"],
                              "saved_url": canonical.get("result_url") if canonical else None,
                              "prompt_hidden": bool(payload.get("trend_id") or payload.get("source_feed_gen_id")),
                              "prompt_actions_allowed": not bool(payload.get("trend_id") or payload.get("source_feed_gen_id")),
                              "task_type": "video", "trend_id": payload.get("trend_id")})


def _scenario_payload(data: dict[str, Any], prompt: str) -> dict[str, Any]:
    identity = _identity_intent(data)
    editing = data.get("seedance25_video_editing", False)
    if not isinstance(editing, bool):
        raise ValueError("Некорректный режим редактирования видео")  # noqa: TRY004 - user-input validation maps to HTTP 400
    editing = editing or identity
    scenario = str(data.get("seedance25_scenario") or "text")
    first = data.get("seedance25_first_frame_url") if scenario in {"first_frame", "first_last"} else None
    last = data.get("seedance25_last_frame_url") if scenario == "first_last" else None
    images = fullstack._clean_urls(data.get("reference_images") or [], 30) if scenario == "multimodal" else []
    videos = fullstack._clean_urls(data.get("v_reference_videos") or [], 10) if scenario == "multimodal" else []
    audios = fullstack._clean_urls(data.get("seedance25_reference_audio_urls") or [], 10) if scenario == "multimodal" else []
    return {
        "scenario": scenario,
        "prompt": str(prompt or "").strip(),
        "duration": -1 if editing else int(data.get("v_duration", 5)),
        "ratio": "adaptive" if editing else str(data.get("v_ratio") or "adaptive"),
        "seedance25_video_editing": editing,
        "seedance25_identity_transfer": identity,
        "resolution": str(data.get("seedance25_resolution") or "720p"),
        "first_frame": str(first or "").strip() or None,
        "last_frame": str(last or "").strip() or None,
        "image_urls": images,
        "video_urls": videos,
        "audio_urls": audios,
        "return_last_frame": bool(data.get("seedance25_return_last_frame", False)),
        "generate_audio": bool(data.get("seedance25_generate_audio", True)),
        "output_format": str(data.get("seedance25_output_format") or "mp4"),
        "web_search": bool(data.get("seedance25_web_search", False)),
        "nsfw_checker": bool(data.get("seedance25_nsfw_checker", False)),
    }


async def _validate_public_payload(
    payload: dict[str, Any],
    *,
    is_admin: bool,
    trusted_trend: bool = False,
    telegram_id: int | None = None,
) -> None:
    scenario = payload["scenario"]
    identity = payload.get("seedance25_identity_transfer", False)
    if not isinstance(identity, bool):
        raise ValueError("Некорректный режим переноса персонажа")  # noqa: TRY004 - maps input validation to HTTP 400
    # Resolve and freeze the exact provider prompt before debit. A later admin
    # template edit must not change the already-validated paid request.
    provider_prompt = payload["prompt"]
    if identity:
        validate_identity_transfer_refs(
            images=payload["image_urls"], videos=payload["video_urls"], audio=payload["audio_urls"],
            first_frame=payload["first_frame"], last_frame=payload["last_frame"],
        )
        provider_prompt = await resolve_identity_transfer_prompt(provider_prompt, image_count=len(payload["image_urls"]))
    # Shared adapter validation runs before credit checks, debit or any provider call.
    payload["provider_prompt"] = seedance_25_service.prepare_prompt(
        provider_prompt, image_urls=payload["image_urls"], video_urls=payload["video_urls"],
        audio_urls=payload["audio_urls"], identity_transfer=identity,
        first_frame=payload["first_frame"], last_frame=payload["last_frame"],
    )
    seedance_25_service.normalize_duration(payload["duration"])
    if payload["ratio"] not in seedance_25_service.ALLOWED_RATIOS:
        raise ValueError("Некорректный формат Seedance 2.5")
    if payload["resolution"] not in seedance_25_service.ALLOWED_RESOLUTIONS:
        raise ValueError("Некорректное качество Seedance 2.5")
    if payload["output_format"] not in seedance_25_service.ALLOWED_OUTPUT_FORMATS:
        raise ValueError("Некорректный формат файла Seedance 2.5")
    if identity:
        if telegram_id is None:
            raise ValueError("Не удалось проверить владельца исходного видео")
        for source in payload["image_urls"]:
            _identity_local_path(source, "image", telegram_id)
        _identity_local_path(payload["video_urls"][0], "video", telegram_id)
        measured = await fullstack._validate_local_source(payload["video_urls"][0], "video")
        if measured is None or not math.isfinite(measured) or not 4 <= measured <= 30:
            raise ValueError("Для переноса персонажа загрузите исходное видео 4–30 секунд; длительность должна быть проверена сервером")
        payload["billing_duration"] = math.ceil(measured)
        payload["source_video_duration_seconds"] = measured
        payload["duration"], payload["ratio"] = -1, "adaptive"
        payload["seedance25_video_editing"] = True
    editing = payload.get("seedance25_video_editing", False)
    if not isinstance(editing, bool):
        raise ValueError("Некорректный режим редактирования видео")  # noqa: TRY004 - user-input validation maps to HTTP 400
    if editing and not identity:
        if not is_admin and not trusted_trend:
            raise _PublicVideoAccessError("Редактирование видео пока доступно только администратору: длительность определяется исходником")
        if scenario != "multimodal" or len(payload["video_urls"]) != 1:
            raise ValueError("Для редактирования выберите режим по референсам и одно исходное видео 4–30 секунд")
        duration = await fullstack._validate_local_source(payload["video_urls"][0], "video")
        if duration is not None and not 4 <= duration <= 30:
            raise ValueError("Для редактирования исходное видео должно быть 4–30 секунд")
    if len(payload["prompt"]) > seedance_25_service.MAX_PROMPT_LENGTH:
        raise ValueError(f"Промпт Seedance 2.5 — максимум {seedance_25_service.MAX_PROMPT_LENGTH} символов")
    if scenario == "text" and not payload["prompt"]:
        raise ValueError("Для Text-to-Video нужен промпт")
    if scenario in {"first_frame", "first_last"} and not payload["first_frame"]:
        raise ValueError("Сначала загрузите первый кадр")
    if scenario == "first_last" and not payload["last_frame"]:
        raise ValueError("Для этого режима нужен последний кадр")
    if scenario == "multimodal" and not (
        payload["image_urls"] or payload["video_urls"] or payload["audio_urls"]
    ):
        raise ValueError("Добавьте хотя бы один мультимодальный референс")
    if payload["duration"] == -1 and not is_admin and not trusted_trend and not identity:
        raise _PublicVideoAccessError("Auto-длительность пока доступна только администратору; выберите 4–30 секунд")
    await fullstack._validate_seedance_sources(
        first_frame_url=payload["first_frame"],
        last_frame_url=payload["last_frame"],
        image_urls=payload["image_urls"],
        video_urls=payload["video_urls"],
        audio_urls=payload["audio_urls"],
    )


async def _launch_provider(payload: dict[str, Any]) -> dict[str, Any]:
    return await seedance_25_service.generate_video(
        prompt=payload.get("provider_prompt", payload["prompt"]),
        duration=payload["duration"],
        aspect_ratio=payload["ratio"],
        resolution=payload["resolution"],
        first_frame_url=payload["first_frame"],
        last_frame_url=payload["last_frame"],
        reference_image_urls=payload["image_urls"] or None,
        reference_video_urls=payload["video_urls"] or None,
        reference_audio_urls=payload["audio_urls"] or None,
        return_last_frame=payload["return_last_frame"],
        generate_audio=payload["generate_audio"],
        output_format=payload["output_format"],
        web_search=payload["web_search"],
        nsfw_checker=payload["nsfw_checker"],
        callBackUrl=get_seedance25_callback_url(),
        **({"_prompt_is_prepared": True} if payload.get("_snapshot_media_ids") and payload.get("provider_prompt") else {}),
        **({"video_editing": True} if payload.get("seedance25_video_editing") is True else {}),
        **({"identity_transfer": True} if payload.get("seedance25_identity_transfer") is True else {}),
    )


def _request_data(
    payload: dict[str, Any], *, is_admin: bool, quote: float, source: str,
    billing_quote: VideoQuote | None = None,
) -> dict[str, Any]:
    # The optional argument preserves compatibility with existing trend callers.
    # Public launches always supply the immutable, server-resolved quote.
    price_quote = float(billing_quote.cost if billing_quote is not None else quote)
    charged_cost = float(billing_quote.charge_cost if billing_quote is not None else 0.0 if is_admin else price_quote)
    if billing_quote is not None:
        is_admin = billing_quote.profile == "admin"
    return {
        "source": source,
        "release": "seedance_2_5_public",
        "v_model": MODEL_KEY,
        "v_type": "text" if payload["scenario"] == "text" else "imgtxt" if payload["scenario"] in {"first_frame", "first_last"} else "video",
        "seedance25_scenario": payload["scenario"],
        "seedance25_video_editing": payload.get("seedance25_video_editing", False),
        "seedance25_identity_transfer": payload.get("seedance25_identity_transfer", False),
        "seedance25_identity_role_version": IDENTITY_ROLE_VERSION if payload.get("seedance25_identity_transfer") else None,
        "seedance25_provider_prompt_sha256": (
            hashlib.sha256(payload["provider_prompt"].encode("utf-8")).hexdigest()
            if payload.get("seedance25_identity_transfer") and payload.get("provider_prompt") else None
        ),
        "seedance25_reference_roles": ({"images": "same_person_identity", "video": "motion_scene_camera_only"} if payload.get("seedance25_identity_transfer") else None),
        "billing_duration": payload.get("billing_duration", payload["duration"]),
        "source_video_duration_seconds": payload.get("source_video_duration_seconds"),
        "duration": payload["duration"],
        "aspect_ratio": payload["ratio"],
        "first_frame_url": payload["first_frame"],
        "last_frame_url": payload["last_frame"],
        "reference_images": payload["image_urls"],
        "v_reference_videos": payload["video_urls"],
        "reference_audios": payload["audio_urls"],
        "resolution": payload["resolution"],
        "generate_audio": payload["generate_audio"],
        "return_last_frame": payload["return_last_frame"],
        "output_format": payload["output_format"],
        "web_search": payload["web_search"],
        "nsfw_checker": payload["nsfw_checker"],
        "price_quote": price_quote,
        **({"billing_quote": billing_quote.to_dict()} if billing_quote is not None else {}),
        "charged": charged_cost > 0,
        "charged_cost": charged_cost,
        "admin_free": is_admin,
        "refund_on_failure": charged_cost > 0,
        "refund_claimed": False,
        "callback_url": get_seedance25_callback_url(),
        "provider_model": seedance_25_service.MODEL_NAME,
    }


async def _verify_telegram_repeat_context(telegram_id, data):
    context = data.get("seedance25_repeat_context")
    if not context:
        return
    from bot.handlers.seedance_25_telegram_compat import _repeat_request_data, _repeat_state_payload

    task = await generation_module.get_task_by_id(context["task_id"])
    user = await generation_module.get_or_create_user(telegram_id)
    if not task or task.user_id != user.id or task.model != MODEL_KEY:
        raise ValueError("Исходная генерация больше недоступна владельцу")
    metadata = _repeat_request_data(task.request_data)
    prompt = str(metadata.get("user_prompt") or metadata.get("prompt") or task.prompt or "").strip()
    restored = _repeat_state_payload(task, metadata, prompt)
    fingerprint = hashlib.sha256(json.dumps(restored, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fingerprint != context.get("fingerprint"):
        raise ValueError("Данные исходной генерации изменились. Откройте повтор заново")


async def _public_message_launch(message: types.Message, state: FSMContext, prompt: str, *, actor_id: int | None = None) -> None:
    telegram_id = actor_id if actor_id is not None else message.from_user.id
    data = await state.get_data()
    is_admin = config.is_admin(telegram_id)
    try:
        await _verify_telegram_repeat_context(telegram_id, data)
        payload = _scenario_payload(data, prompt)
        await _validate_public_payload(payload, is_admin=is_admin, telegram_id=telegram_id)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return

    if _needs_measured_quote(payload):
        payload["_launch_surface"] = "telegram"
        try:
            row = await _prepare_measured_quote(telegram_id, payload)
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return
        billing = json.loads(row["billing_json"])
        await state.update_data(seedance25_pending_quote={"id": row["quote_id"], "hash": row["quote_hash"],
                                                         "prompt": prompt})
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(
            text=f"Создать видео · {billing['charge_cost']:g}🍌", callback_data="seedquote:" + row["quote_id"])]])
        await message.answer(f"Видеорефы {billing['input_seconds']:g}с + результат "
                             f"{billing['selected_output_seconds']:g}с. Цена: {billing['cost']:g}🍌. "
                             "Подтвердите запуск по этой цене.", reply_markup=keyboard)
        return
    billing_quote = await _payload_quote(telegram_id, payload)
    quote, charge_cost = billing_quote.cost, billing_quote.charge_cost
    is_admin = billing_quote.profile == "admin"
    if payload.get("seedance25_identity_transfer") and not is_admin and data.get("seedance25_identity_quote") != _identity_quote(payload, cost=quote):
        await _public_show_screen(message, state, edit=False, actor_id=telegram_id)
        await message.answer("Проверьте обновлённую цену выше и отправьте промпт ещё раз для запуска.")
        return
    if charge_cost > 0 and not await generation_module.check_can_afford(telegram_id, charge_cost):
        credits = await generation_module.get_user_credits(telegram_id)
        await message.answer(
            f"❌ Недостаточно бананов. Нужно <b>{quote:g}🍌</b>, на балансе <b>{credits:g}🍌</b>.",
            parse_mode="HTML",
        )
        return

    charged = refund_attempted = False
    accepted_task_id = None
    processing = await message.answer(
        "🆕 <b>Seedance 2.5 · NEW</b>\n"
        f"Цена: <code>{quote:g}</code>🍌 · отправляю задачу в Kie.ai…",
        parse_mode="HTML",
    )
    try:
        if charge_cost > 0:
            debited = await generation_module.deduct_credits(telegram_id, charge_cost)
            if debited is False:
                await processing.delete()
                await message.answer("❌ Не удалось списать бананы. Обновите баланс и попробуйте снова.")
                return
            charged = True

        result = await _launch_provider(payload)
        if not result or not result.get("task_id"):
            if charged:
                refund_attempted = True
                refunded = await generation_module.add_credits(telegram_id, charge_cost)
                if refunded is False:
                    raise RuntimeError("video_refund_unconfirmed")
                charged = False
            error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            await processing.delete()
            await message.answer(
                f"❌ Seedance 2.5 не запустилась: <code>{str(error)[:500]}</code>"
                + ("\n🍌 Списание возвращено." if refund_attempted and not charged else ""),
                parse_mode="HTML",
            )
            return

        # Acceptance is the financial boundary, before persistence or Telegram
        # delivery. Subsequent errors must never undo this accepted job's debit.
        task_id = accepted_task_id = str(result["task_id"])
        user = await generation_module.get_or_create_user(telegram_id)
        await generation_module.add_generation_task(
            user.id,
            telegram_id,
            task_id,
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=payload["duration"],
            aspect_ratio=payload["ratio"],
            prompt=payload["prompt"],
            cost=charge_cost,
            request_data=_request_data(payload, is_admin=is_admin, quote=quote, source="telegram", billing_quote=billing_quote),
            provider_accepted=True,
        )
        await processing.delete()
        billing = "администратору бесплатно" if is_admin else f"списано {quote:g}🍌"
        await message.answer(
            "✅ <b>Seedance 2.5 запущена</b>\n"
            f"🆔 <code>{task_id}</code>\n"
            f"⏱ <code>{_duration_label(payload['duration'])}</code> · "
            f"📐 <code>{payload['ratio']}</code> · 🖥 <code>{payload['resolution']}</code>\n"
            f"💰 {billing}.\n\n"
            "Результат придёт автоматически после завершения.",
            parse_mode="HTML",
        )
    except Exception as exc:
        if accepted_task_id:
            logger.error("Seedance 2.5 Telegram job accepted; status delivery failed: task_id=%s error_type=%s",
                         accepted_task_id, type(exc).__name__)
            try:
                await message.answer(
                    "Видео принято провайдером, но статус пока не подтверждён. "
                    "Не повторяйте запуск сразу.\n"
                    f"🆔 <code>{accepted_task_id}</code>", parse_mode="HTML",
                )
            except Exception:
                logger.exception("Seedance 2.5 accepted-job notice unavailable: task_id=%s", accepted_task_id)
            return
        logger.exception("Public Seedance 2.5 Telegram launch failed")
        if charged and not refund_attempted:
            # A raised credit call can have committed already. Never retry it
            # in this exception handler without an idempotent refund claim.
            refund_attempted = True
            try:
                refunded = await generation_module.add_credits(telegram_id, charge_cost)
                if refunded is not False:
                    charged = False
            except Exception:
                logger.exception("Seedance 2.5 immediate refund unconfirmed for %s", telegram_id)
        try:
            await processing.delete()
        except Exception:
            pass
        refund_notice = (
            "\n🍌 Не удалось подтвердить возврат бананов. Требуется проверка платежа; не повторяйте запуск сразу."
            if charged else "\n🍌 Списание возвращено." if refund_attempted else ""
        )
        await message.answer(
            f"❌ Seedance 2.5: <code>{str(exc)[:500]}</code>" + refund_notice,
            parse_mode="HTML",
        )
    finally:
        await state.clear()


async def _public_miniapp_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
    import bot.miniapp as miniapp_module

    telegram_id, ctx = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    user = ctx["user"]
    if body.get("seedance25_status_only") is True:
        from bot.services.seedance_quote_lifecycle import receipt_store
        from bot.services.seedance_quote_receipts import QuoteConflict

        try:
            row = await (await receipt_store()).find(telegram_id, body.get("video_quote_id"))
        except QuoteConflict as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        if not row:
            return web.json_response({"ok": False, "code": "video_quote_missing", "error": "Расчёт не найден"}, status=404)
        if row["phase"] == "accepted":
            await _bind_measured_seedance25(row)
            return await _measured_miniapp_response(row)
        return web.json_response({"ok": True, "status": row["phase"], "quote_id": row["quote_id"]})
    if not isinstance(body.get("seedance25_quote_only", False), bool):
        return web.json_response({"ok": False, "error": "Некорректный запрос расчёта цены"}, status=400)
    is_admin = config.is_admin(telegram_id)
    source_feed_gen_id_raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
    source_feed_gen_id = (
        int(source_feed_gen_id_raw)
        if str(source_feed_gen_id_raw or "").isdigit()
        else None
    )
    immediate_parent_id = source_feed_gen_id
    if source_feed_gen_id:
        source_card = await miniapp_module._get_repeat_source_card(
            source_feed_gen_id,
            viewer_user_id=user.id,
        )
        if (
            not source_card
            or str(source_card.get("gen_type") or "").lower() != "video"
            or str(source_card.get("model") or "") != MODEL_KEY
        ):
            return web.json_response(
                {"ok": False, "error": "Исходное видео для повтора не найдено"},
                status=404,
            )
        # Match the common Mini App repeat contract: keep the root source on
        # the generated task, but reward the immediate parent on each repeat.
        source_feed_gen_id = int(
            source_card.get("source_feed_gen_id") or source_feed_gen_id
        )

    data = {
        "seedance25_scenario": str(body.get("seedance25_scenario") or "text").strip().lower(),
        "seedance25_video_editing": body.get("seedance25_video_editing", False),
        "seedance25_identity_transfer": body.get("seedance25_identity_transfer", body.get("identityTransfer", False)),
        "v_duration": int(body.get("v_duration", 5)),
        "v_ratio": str(body.get("v_ratio") or "adaptive").strip().lower(),
        "seedance25_resolution": str(body.get("seedance25_resolution") or "720p").strip().lower(),
        "seedance25_first_frame_url": str(body.get("seedance25_first_frame_url") or "").strip() or None,
        "seedance25_last_frame_url": str(body.get("seedance25_last_frame_url") or "").strip() or None,
        "reference_images": fullstack._clean_urls(body.get("reference_images") or [], 30),
        "v_reference_videos": fullstack._clean_urls(body.get("v_reference_videos") or [], 10),
        "seedance25_reference_audio_urls": fullstack._clean_urls(body.get("seedance25_reference_audio_urls") or [], 10),
        "seedance25_return_last_frame": bool(body.get("seedance25_return_last_frame", False)),
        "seedance25_generate_audio": bool(body.get("seedance25_generate_audio", True)),
        "seedance25_output_format": str(body.get("seedance25_output_format") or "mp4").strip().lower(),
        "seedance25_web_search": bool(body.get("seedance25_web_search", False)),
        "seedance25_nsfw_checker": bool(body.get("seedance25_nsfw_checker", False)),
    }
    try:
        if "identityTransfer" in body:
            data["identityTransfer"] = body["identityTransfer"]
        _identity_intent(data)
    except ValueError as exc:
        error = (
            "Не удалось проверить входные данные повтора. Проверьте свои файлы."
            if source_feed_gen_id else str(exc)
        )
        return web.json_response({"ok": False, "error": error}, status=400)
    scenario = data["seedance25_scenario"]
    if scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        return web.json_response({"ok": False, "error": "Некорректный сценарий Seedance 2.5"}, status=400)

    if scenario == "text":
        data.update(
            seedance25_first_frame_url=None,
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
        )
    elif scenario == "first_frame":
        data.update(
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
        )
    elif scenario == "first_last":
        data.update(reference_images=[], v_reference_videos=[], seedance25_reference_audio_urls=[])
    else:
        data.update(seedance25_first_frame_url=None, seedance25_last_frame_url=None)

    try:
        payload = _scenario_payload(data, str(body.get("prompt") or ""))
        if source_feed_gen_id and len(payload["prompt"]) > seedance_25_service.MAX_PROMPT_LENGTH:
            return miniapp_module._video_repeat_prompt_too_long_response()
        await _validate_public_payload(payload, is_admin=is_admin, telegram_id=telegram_id)
    except _PublicVideoAccessError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except ValueError as exc:
        error = (
            "Не удалось проверить входные данные повтора. Проверьте свои файлы."
            if source_feed_gen_id else str(exc)
        )
        return web.json_response({"ok": False, "code": "video_input_invalid", "error": error}, status=400)

    payload.update(source_feed_gen_id=source_feed_gen_id, parent_generation_id=immediate_parent_id)
    payload["_launch_surface"] = "miniapp"
    payload["_private_repeat"] = bool(getattr(request, "_video_repeat_authorization", None))
    payload["_authorized_video_sources"] = list(body.get("_private_repeat_reference_videos") or []) if payload["_private_repeat"] else []
    if _needs_measured_quote(payload):
        from bot.handlers.miniapp_video_continuity_compat import verify_video_repeat_before_charge
        from bot.services.seedance_quote_lifecycle import public_quote
        from bot.services.seedance_quote_receipts import InsufficientCredits, QuoteConflict

        permission_error = await verify_video_repeat_before_charge(request)
        if permission_error is not None:
            return permission_error
        try:
            if body.get("seedance25_quote_only") is True:
                row = await _prepare_measured_quote(telegram_id, payload)
                result = public_quote(row)
                if payload.get("seedance25_identity_transfer"):
                    result.update(source_video_duration_seconds=payload["source_video_duration_seconds"],
                                  seedance25_identity_quote=_identity_quote(payload, cost=result["cost"]))
                return web.json_response(result)
            row = await _launch_measured_seedance25(telegram_id, payload, body.get("video_quote_id"),
                                                    body.get("video_quote_hash"))
            return await _measured_miniapp_response(row)
        except QuoteConflict as exc:
            return web.json_response({"ok": False, "code": "video_quote_changed", "error": str(exc)}, status=409)
        except InsufficientCredits as exc:
            return web.json_response({"ok": False, "code": "video_not_reserved", "error": str(exc)}, status=400)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
    billing_quote = await _payload_quote(telegram_id, payload)
    quote, charge_cost = billing_quote.cost, billing_quote.charge_cost
    is_admin = billing_quote.profile == "admin"
    if body.get("seedance25_quote_only") is True:
        return web.json_response({"ok": False, "error": "Добавьте видео для измеренного расчёта"}, status=400)
    if charge_cost > 0 and not await miniapp_module.check_can_afford(telegram_id, charge_cost):
        fresh = await miniapp_module.get_or_create_user(telegram_id)
        return web.json_response(
            {"ok": False, "error": f"Недостаточно бананов. Нужно {quote:g}🍌", "credits": fresh.credits},
            status=400,
        )

    from bot.handlers.miniapp_video_continuity_compat import (
        record_video_repeat_launch, recover_video_repeat_launch, reserve_video_repeat_launch,
        verify_video_repeat_before_charge, video_repeat_pending_response,
    )
    private_repeat = bool(getattr(request, "_video_repeat_authorization", None))
    receipt_id = None
    launch_started = debit_attempted = debit_completed = provider_rejected = task_persisted = False
    charged = False
    refund_attempted = False
    accepted_task_id = None
    try:
        receipt_id, pending_response = await reserve_video_repeat_launch(
            request, user=user, telegram_id=telegram_id, model=MODEL_KEY,
            duration=payload["duration"], aspect_ratio=payload["ratio"],
        )
        if pending_response is not None:
            return pending_response
        permission_error = await verify_video_repeat_before_charge(request)
        if permission_error is not None:
            await record_video_repeat_launch(receipt_id, user.id, phase="permission_rejected", terminal=True)
            return permission_error
        if charge_cost > 0:
            await record_video_repeat_launch(receipt_id, user.id, phase="debit_pending", attempted_cost=charge_cost)
            debit_attempted = True
            debited = await miniapp_module.deduct_credits(telegram_id, charge_cost)
            debit_completed = True
            if debited is False:
                await record_video_repeat_launch(receipt_id, user.id, phase="debit_rejected", terminal=True)
                return web.json_response(
                    {"ok": False, "error": "Не удалось списать бананы. Обновите баланс и попробуйте снова."}, status=400,
                )
            charged = True

        await record_video_repeat_launch(receipt_id, user.id, phase="launching", cost=charge_cost if charged else 0)
        launch_started = True
        result = await _launch_provider(payload)
        if not result or not result.get("task_id"):
            provider_rejected = True
            if charged:
                refund_attempted = True
                refunded = await miniapp_module.add_credits(telegram_id, charge_cost)
                if refunded is False:
                    raise RuntimeError("video_refund_unconfirmed")
                charged = False
            await record_video_repeat_launch(receipt_id, user.id, phase="rejected", cost=0, terminal=True)
            error = (
                "провайдер не принял запрос"
                if source_feed_gen_id
                else result.get("error") if isinstance(result, dict) else "provider response has no task_id"
            )
            return web.json_response(
                {"ok": False, "error": f"Seedance 2.5 не запустилась: {error}."
                 + (" Списание возвращено." if refund_attempted and not charged else "")},
                status=502,
            )

        task_id = str(result["task_id"])
        accepted_task_id = task_id
        request_data = _request_data(
            payload,
            is_admin=is_admin,
            quote=quote,
            source="miniapp",
            billing_quote=billing_quote,
        )
        if getattr(request, "_video_repeat_authorization", None):
            request_data["video_repeat_contract_version"] = 1
        if source_feed_gen_id:
            request_data.update(
                source_feed_gen_id=source_feed_gen_id,
                parent_generation_id=immediate_parent_id,
                action_type="repeat",
            )
        persisted = await generation_module.add_generation_task(
            user.id,
            telegram_id,
            task_id,
            "video",
            "no_preset_video",
            model=MODEL_KEY,
            duration=payload["duration"],
            aspect_ratio=payload["ratio"],
            prompt=payload["prompt"],
            cost=charge_cost,
            request_data=request_data,
            source_feed_gen_id=source_feed_gen_id,
            parent_generation_id=(immediate_parent_id if source_feed_gen_id else None),
            action_type="repeat" if source_feed_gen_id else None,
            **({"reserved_task_id": receipt_id} if receipt_id else {}),
            provider_accepted=True,
        )
        if receipt_id and persisted is not True:
            raise RuntimeError("video_repeat_receipt_binding_failed")
        task_persisted = True
        if source_feed_gen_id and not is_admin:
            try:
                await miniapp_module.credit_feed_prompt_repeat(
                    immediate_parent_id,
                    user.id,
                    repeat_task_id=task_id,
                    credits_spent=charge_cost,
                )
            except Exception as reward_error:
                if source_feed_gen_id:
                    logger.error("Private Seedance repeat reward failed: task_id=%s error_type=%s",
                                 task_id, type(reward_error).__name__)
                else:
                    logger.exception(
                        "Seedance 2.5 repeat reward failed for source=%s task=%s",
                        source_feed_gen_id, task_id,
                    )
        fresh_user = await miniapp_module.get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": "queued",
                "task_id": task_id,
                "credits": fresh_user.credits,
                "cost": quote,
                "task_type": "video",
                "model": MODEL_KEY,
                "model_label": "Seedance 2.5",
                "prompt_hidden": bool(source_feed_gen_id),
                "prompt_actions_allowed": not bool(source_feed_gen_id),
                "source_feed_gen_id": source_feed_gen_id,
                "admin_free": is_admin,
                "resolution": payload["resolution"],
                "duration": payload["duration"],
                "aspect_ratio": payload["ratio"],
                "scenario": payload["scenario"],
                "billing_duration": payload.get("billing_duration", payload["duration"]),
                "source_video_duration_seconds": payload.get("source_video_duration_seconds"),
                "seedance25_identity_transfer": payload.get("seedance25_identity_transfer", False),
            }
        )
    except Exception as exc:
        if accepted_task_id:
            if not task_persisted and receipt_id:
                task_persisted = await recover_video_repeat_launch(receipt_id, user.id, accepted_task_id)
            logger.error("Seedance accepted; status reconciliation needed: task_id=%s error_type=%s",
                         accepted_task_id, type(exc).__name__)
            return web.json_response(
                {"ok": False, "code": "video_status_pending", "task_id": accepted_task_id if task_persisted or not receipt_id else receipt_id,
                 "error": "Видео принято провайдером, но статус пока не подтверждён. Не повторяйте запуск сразу."},
                status=500,
            )
        if private_repeat:
            if charged and not refund_attempted:
                refund_attempted = True
                try:
                    refunded = await miniapp_module.add_credits(telegram_id, charge_cost)
                    if refunded is not False:
                        charged = False
                except Exception as refund_error:
                    logger.error("Private Seedance refund unconfirmed: telegram_id=%s error_type=%s",
                                 telegram_id, type(refund_error).__name__)
                logger.warning("Private Seedance launch outcome unknown: telegram_id=%s refunded=%s error_type=%s",
                               telegram_id, not charged, type(exc).__name__)
            if charged:
                return web.json_response(
                    {"ok": False, "code": "video_refund_pending",
                     "error": "Не удалось подтвердить возврат бананов. Требуется проверка платежа; не повторяйте запуск сразу."},
                    status=500,
                )
            if receipt_id:
                terminal = provider_rejected or (not launch_started and (not debit_attempted or debit_completed))
                try:
                    await record_video_repeat_launch(receipt_id, user.id,
                        phase=("prelaunch_failed" if terminal else "debit_unknown"
                               if debit_attempted and not debit_completed else "outcome_unknown"),
                        cost=None if debit_attempted and not debit_completed else 0, terminal=terminal)
                except Exception as receipt_error:
                    logger.error("Private Seedance receipt reconciliation needed: task_id=%s error_type=%s",
                                 receipt_id, type(receipt_error).__name__)
                    return video_repeat_pending_response(receipt_id)
                if not terminal:
                    return video_repeat_pending_response(receipt_id)
            logger.error("Private Seedance video repeat failed: error_type=%s", type(exc).__name__)
            return web.json_response({"ok": False, "error": "Не удалось запустить видео. Попробуйте ещё раз."}, status=500)
        if source_feed_gen_id:
            logger.error("Seedance video repeat failed: error_type=%s", type(exc).__name__)
        else:
            logger.exception("Public Seedance 2.5 Mini App launch failed")
        if charged and not refund_attempted:
            refund_attempted = True
            try:
                refunded = await miniapp_module.add_credits(telegram_id, charge_cost)
                if refunded is not False:
                    charged = False
            except Exception as refund_error:
                if source_feed_gen_id:
                    logger.error("Seedance video repeat refund unconfirmed: telegram_id=%s error_type=%s",
                                 telegram_id, type(refund_error).__name__)
                else:
                    logger.exception("Seedance 2.5 Mini App immediate refund unconfirmed for %s", telegram_id)
        if charged:
            return web.json_response(
                {"ok": False, "code": "video_refund_pending",
                 "error": "Не удалось подтвердить возврат бананов. Требуется проверка платежа; не повторяйте запуск сразу."},
                status=500,
            )
        error = "Не удалось запустить видео. Попробуйте ещё раз." if source_feed_gen_id else str(exc)
        return web.json_response({"ok": False, "error": error}, status=500)


async def _claim_async_refund(task_id: str) -> tuple[int, float] | None:
    """Atomically refund one failed paid Seedance 2.5 task.

    The refund marker and balance credit are committed in the same DB
    transaction so a crash cannot leave the marker without the money
    being restored.
    """
    row = await fullstack._load_task_row(task_id)
    if not row or str(row["status"] or "").lower() != "pending":
        return None
    try:
        request_data = json.loads(row["request_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not request_data.get("refund_on_failure") or request_data.get("refund_claimed"):
        return None

    cost = float(request_data["charged_cost"] if "charged_cost" in request_data else row["cost"] or 0)
    if cost <= 0:
        return None

    telegram_id = int(row["telegram_id"])
    internal_user_id = int(row["user_id"])
    old_json = row["request_data"] or "{}"
    request_data["refund_claimed"] = True
    request_data["refund_state"] = "refunded"
    new_json = json.dumps(request_data, ensure_ascii=False, separators=(",", ":"))

    async with fullstack.db_backend.connect() as db:
        try:
            cursor = await db.execute(
                """
                UPDATE generation_tasks
                SET request_data = ?, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ? AND status = 'pending' AND request_data = ?
                """,
                (new_json, task_id, old_json),
            )
            if int(getattr(cursor, "rowcount", 0) or 0) != 1:
                await db.rollback()
                raise RuntimeError(f"Seedance 2.5 refund claim changed; retry task {task_id}")

            credit_cursor = await db.execute(
                """
                UPDATE users
                SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (cost, internal_user_id),
            )
            if int(getattr(credit_cursor, "rowcount", 0) or 0) != 1:
                raise RuntimeError(
                    f"Seedance 2.5 refund user row missing for task {task_id}"
                )
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            raise

    return telegram_id, cost


async def _public_process_payload(app: web.Application, payload: dict[str, Any]) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    task_id = str((data or {}).get("taskId") or payload.get("taskId") or "").strip()
    state = str((data or {}).get("state") or payload.get("state") or "").lower()
    try:
        code = int(payload.get("code") or 200)
    except (TypeError, ValueError):
        code = 200
    provider_fail_code = str((data or {}).get("failCode") or "").strip()
    failure_codes = {"400", "501", "500", "422", "402", "429", "455", "505"}
    is_failure = (
        state in {"fail", "failed", "error"}
        or str(code) in failure_codes
        or provider_fail_code in failure_codes
    )
    if task_id and is_failure:
        row = await fullstack._load_task_row(task_id)
        metadata = json.loads(row["request_data"] or "{}") if row else {}
        if metadata.get("seedance_quote_id"):
            # A transport/code anomaly is not terminal provider evidence. New
            # immutable recipes are never silently retried with altered refs.
            if state not in {"fail", "failed", "error"}:
                return False
            from bot.services.task_watchdog import force_fail_task
            return await force_fail_task(int(row["id"]), int(row["user_id"]), float(metadata.get("charged_cost") or 0),
                                         expected_provider_task_id=task_id, provider_confirmed_failed=True)
    if is_failure and task_id:
        fail_msg = str((data or {}).get("failMsg") or payload.get("msg") or "")
        try:
            if await fullstack._auto_retry_seedance25_video_editing(task_id, fail_msg):
                return True
        except Exception:
            logger.exception(
                "Seedance 2.5 edit fallback preflight failed before refund: task_id=%s",
                task_id,
            )
            return False
        payload["_seedance25_edit_retry_checked"] = True
        try:
            claimed = await _claim_async_refund(task_id)
            if claimed:
                _telegram_id, cost = claimed
                logger.info(
                    "Seedance 2.5 refunded %.2f credits atomically for failed task %s",
                    cost,
                    task_id,
                )
        except Exception:
            logger.exception("Seedance 2.5 async refund failed for task %s", task_id)
            return False
    return await fullstack._process_seedance25_payload_original(app, payload)


async def _public_send_results(
    app: web.Application,
    telegram_id: int,
    task_id: str,
    video_url: str,
    last_frame_url: str | None,
    request_data: dict[str, Any],
) -> bool:
    bot = app["bot"]
    output_format = str(request_data.get("output_format") or fullstack._extension_from_url(video_url) or "mp4").lower()
    resolution = str(request_data.get("resolution") or "720p")
    duration = request_data.get("duration")
    scenario = str(request_data.get("seedance25_scenario") or "text")
    identity = request_data.get("seedance25_identity_transfer") is True
    if identity:
        scenario = "Замена персонажа"
    admin_free = bool(request_data.get("admin_free"))
    cost = float(request_data.get("charged_cost") or 0)
    billing = "без списания для администратора" if admin_free else f"списано {cost:g}🍌"
    caption = (
        "✅ <b>Seedance 2.5 готово</b>\n"
        f"• ID задачи: <code>{task_id}</code>\n"
        f"• Сценарий: <code>{scenario}</code>\n"
        f"• Качество: <code>{resolution}</code>\n"
        f"• Формат: <code>{output_format.upper()}</code>\n"
        f"• Оплата: <code>{billing}</code>"
    )
    locked_quote = request_data.get("billing_quote") or {}
    if locked_quote.get("version") == 2:
        caption += (f"\n• Расчёт: вход <code>{locked_quote['input_seconds']:g}с</code> + "
                    f"результат <code>{locked_quote['selected_output_seconds']:g}с</code>")
    elif identity and request_data.get("source_video_duration_seconds") is not None:
        measured = float(request_data["source_video_duration_seconds"])
        billed = int(request_data["billing_duration"])
        caption += f"\n• Исходное видео: <code>{measured:g}с</code> · расчёт: <code>{billed}с</code>"
    elif duration is not None:
        caption += f"\n• Длительность: <code>{'Auto' if int(duration) == -1 else str(duration) + 'с'}</code>"
    from bot import keyboards as keyboard_module

    result_markup = keyboard_module.get_video_result_keyboard(
        video_url,
        task_id=task_id,
        model=MODEL_KEY,
        is_public_feed=False,
    )

    delivered = False
    suffix = ".mov" if output_format == "mov" else ".mp4"
    if output_format == "mp4":
        try:
            await tracked_telegram_send(request_data, True, bot.send_video,
                telegram_id,
                video=video_url,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                reply_markup=result_markup,
            )
            delivered = True
        except Exception as exc:
            delay = telegram_delivery_retry_delay(exc)
            if delay is not None:
                raise TelegramDeliveryRetryable(delay) from exc
            if not telegram_delivery_is_definitely_rejected(exc):
                if is_terminal_telegram_delivery_error(exc):
                    raise
                raise TelegramDeliveryUncertain("Telegram send outcome is unknown") from exc
            if is_terminal_telegram_delivery_error(exc):
                raise
            logger.info("Seedance 2.5 URL delivery failed; trying downloaded file")

    if not delivered:
        temp_path = await fullstack._download_to_temp(video_url, suffix=suffix)
        if temp_path:
            try:
                if output_format == "mp4":
                    await tracked_telegram_send(request_data, True, bot.send_video,
                        telegram_id,
                        video=types.FSInputFile(temp_path),
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        reply_markup=result_markup,
                    )
                else:
                    await tracked_telegram_send(request_data, True, bot.send_document,
                        telegram_id,
                        document=types.FSInputFile(temp_path, filename=f"seedance25-{task_id}.mov"),
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=result_markup,
                    )
                delivered = True
            except Exception as exc:
                delay = telegram_delivery_retry_delay(exc)
                if delay is not None:
                    raise TelegramDeliveryRetryable(delay) from exc
                if not telegram_delivery_is_definitely_rejected(exc):
                    if is_terminal_telegram_delivery_error(exc):
                        raise
                    raise TelegramDeliveryUncertain("Telegram send outcome is unknown") from exc
                if is_terminal_telegram_delivery_error(exc):
                    raise
                logger.exception("Seedance 2.5 file delivery failed for task %s", task_id)
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    if not delivered and not request_data.get("delivery_link_sent"):
        try:
            await tracked_telegram_send(request_data, False, bot.send_message,
                telegram_id,
                caption + f"\n\n🔗 Оригинал:\n{video_url}",
                parse_mode="HTML",
                disable_web_page_preview=False,
                reply_markup=result_markup,
            )
            await fullstack._mark_seedance25_delivery(task_id, "link_sent")
        except Exception as exc:
            delay = telegram_delivery_retry_delay(exc)
            if delay is not None:
                raise TelegramDeliveryRetryable(delay) from exc
            if not telegram_delivery_is_definitely_rejected(exc):
                if is_terminal_telegram_delivery_error(exc):
                    raise
                raise TelegramDeliveryUncertain("Telegram send outcome is unknown") from exc
            if is_terminal_telegram_delivery_error(exc):
                raise
            logger.exception(
                "Seedance 2.5 fallback link delivery failed for task %s",
                task_id,
            )

    if last_frame_url:
        try:
            await tracked_telegram_send(request_data, False, bot.send_photo,
                telegram_id,
                photo=last_frame_url,
                caption=f"🖼 <b>Последний кадр Seedance 2.5</b>\nID: <code>{task_id}</code>",
                parse_mode="HTML",
            )
        except Exception as photo_exc:
            if is_terminal_telegram_delivery_error(photo_exc):
                from bot.database import mark_telegram_chat_unavailable

                await mark_telegram_chat_unavailable(telegram_id)
                logger.info(
                    "Telegram delivery unavailable: event=seedance25_last_frame reason=%s task_id=%s telegram_id=%s",
                    terminal_telegram_delivery_reason(photo_exc),
                    task_id,
                    telegram_id,
                )
                return delivered
            if not telegram_delivery_is_definitely_rejected(photo_exc):
                # The primary video is already handled. Never replay a possibly
                # accepted auxiliary photo as a link after a lost response.
                logger.warning("Seedance 2.5 last-frame outcome unknown: task_id=%s", task_id)
                return delivered
            try:
                await tracked_telegram_send(request_data, False, bot.send_message,
                    telegram_id,
                    f"🖼 Последний кадр Seedance 2.5:\n{last_frame_url}",
                    disable_web_page_preview=False,
                )
            except Exception as exc:
                delay = telegram_delivery_retry_delay(exc)
                if delay is not None:
                    raise TelegramDeliveryRetryable(delay) from exc
                if not telegram_delivery_is_definitely_rejected(exc):
                    if is_terminal_telegram_delivery_error(exc):
                        raise
                    raise TelegramDeliveryUncertain("Telegram send outcome is unknown") from exc
                if is_terminal_telegram_delivery_error(exc):
                    from bot.database import mark_telegram_chat_unavailable

                    await mark_telegram_chat_unavailable(telegram_id)
                    logger.info(
                        "Telegram delivery unavailable: event=seedance25_last_frame reason=%s task_id=%s telegram_id=%s",
                        terminal_telegram_delivery_reason(exc),
                        task_id,
                        telegram_id,
                    )
                else:
                    logger.exception(
                        "Seedance 2.5 last-frame fallback delivery failed for task %s",
                        task_id,
                    )

    return delivered


def install_seedance_25_public_release() -> None:
    """Install public access after preview/fullstack compatibility layers."""
    import bot.keyboards as keyboard_module
    import bot.miniapp as miniapp_module

    if getattr(generation_module, "_seedance_25_public_release_installed", False):
        return

    async def confirm_measured_quote(callback, state):
        data = await state.get_data()
        pending = data.get("seedance25_pending_quote")
        quote_id = str(callback.data).removeprefix("seedquote:")
        if (data.get("v_model") != MODEL_KEY or not isinstance(pending, dict)
                or pending.get("id") != quote_id):
            await callback.answer("Откройте актуальный расчёт перед запуском", show_alert=True)
            return
        await callback.answer()
        telegram_id = callback.from_user.id
        try:
            await _verify_telegram_repeat_context(telegram_id, data)
            payload = _scenario_payload(data, str(pending.get("prompt") or ""))
            await _validate_public_payload(payload, is_admin=config.is_admin(telegram_id), telegram_id=telegram_id)
            payload["_launch_surface"] = "telegram"
            row = await _launch_measured_seedance25(telegram_id, payload, quote_id, pending["hash"])
            if row["phase"] == "accepted":
                await callback.message.answer("✅ Видео принято. Результат придёт после завершения.")
            elif row["phase"] == "rejected":
                await callback.message.answer("Провайдер отклонил запрос. Оплата возвращена. Для нового запуска нужен новый расчёт.")
            else:
                await callback.message.answer("Исход запуска проверяется. Повторная отправка и повторное списание заблокированы.")
        except ValueError as exc:
            await callback.message.answer(f"❌ {exc}. Отправьте промпт для нового расчёта.")
        except Exception as exc:
            logger.error("Seedance quote confirmation deferred: quote_id=%s error_type=%s", quote_id, type(exc).__name__)
            await callback.message.answer("Статус запуска пока не подтверждён. Не запускайте повторно.")

    preview_module.router.callback_query.register(confirm_measured_quote, F.data.startswith("seedquote:"))

    # Access checks inside the isolated Seedance modules become feature-access
    # checks. Global config.is_admin is still used for billing/admin privileges.
    fullstack._is_admin = _public_feature_access
    preview_module._is_admin = _public_feature_access

    # Preserve originals for public wrappers and tests.
    if not hasattr(fullstack, "_seedance25_model_meta_original"):
        fullstack._seedance25_model_meta_original = fullstack._seedance25_model_meta
    if not hasattr(fullstack, "_process_seedance25_payload_original"):
        fullstack._process_seedance25_payload_original = fullstack._process_seedance25_payload

    fullstack._seedance25_model_meta = _public_model_meta
    fullstack._process_seedance25_payload = _public_process_payload
    fullstack._send_seedance25_results = _public_send_results
    preview_module._show_seedance_25_screen = _public_show_screen

    # Telegram model lists: expose Seedance to everybody and remove NEW/НОВИНКА
    # badges from all other models.
    original_video_keyboard = keyboard_module.get_video_model_selection_keyboard
    original_image_keyboard = keyboard_module.get_image_model_selection_keyboard
    public_video_keyboard = _public_video_model_keyboard(original_video_keyboard)
    public_image_keyboard = _clean_keyboard_new_markers(original_image_keyboard)
    keyboard_module.get_video_model_selection_keyboard = public_video_keyboard
    keyboard_module.get_image_model_selection_keyboard = public_image_keyboard
    generation_module.get_video_model_selection_keyboard = public_video_keyboard
    generation_module.get_image_model_selection_keyboard = public_image_keyboard

    # Mini App bootstrap: the admin-preview wrapper only exposed Seedance to
    # admins. Rebuild the model entry for every authenticated user.
    current_bootstrap = miniapp_module.miniapp_bootstrap

    @wraps(current_bootstrap)
    async def public_bootstrap(request: web.Request) -> web.Response:
        response = await current_bootstrap(request)
        if response.status != 200:
            return response
        payload = fullstack._json_response_payload(response)
        if not payload:
            return response
        models = [
            item for item in list(payload.get("video_models") or [])
            if not (isinstance(item, dict) and str(item.get("id")) == MODEL_KEY)
        ]
        models.append(_public_model_meta(tariff=getattr(request, "_creator_tariff", "standard")))
        payload["video_models"] = models
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    miniapp_module.miniapp_bootstrap = public_bootstrap

    # Preserve large-video assembly requests; all real generation requests use
    # the public billed path.
    current_seedance_generate = fullstack._miniapp_seedance25_generate

    async def public_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
        if body.get("seedance25_upload_only"):
            return await current_seedance_generate(request, body)
        return await _public_miniapp_generate(request, body)

    fullstack._miniapp_seedance25_generate = public_generate

    # Replace preview's admin-guard launch wrappers after preview installation.
    current_apply_model = generation_module._apply_video_model_selection
    current_message_launch = generation_module.run_no_preset_video_from_message
    current_callback_launch = generation_module.run_no_preset_video_from_callback

    @wraps(current_apply_model)
    async def public_apply_model(callback, state, model):
        if model != MODEL_KEY:
            return await current_apply_model(callback, state, model)
        await state.clear()
        await state.update_data(**preview_module._defaults())
        await _public_show_screen(callback, state)
        await callback.answer()

    @wraps(current_message_launch)
    async def public_message_launch(message, state, prompt):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await current_message_launch(message, state, prompt)
        return await _public_message_launch(message, state, prompt)

    @wraps(current_callback_launch)
    async def public_callback_launch(callback, state, prompt, cost, is_admin, **kwargs):
        data = await state.get_data()
        if data.get("v_model") != MODEL_KEY:
            return await current_callback_launch(callback, state, prompt, cost, is_admin, **kwargs)
        await _public_message_launch(callback.message, state, prompt, actor_id=callback.from_user.id)
        try:
            await callback.answer("Seedance 2.5 запускаю")
        except Exception:
            pass

    generation_module._apply_video_model_selection = public_apply_model
    generation_module.run_no_preset_video_from_message = public_message_launch
    generation_module.run_no_preset_video_from_callback = public_callback_launch
    generation_module._seedance_25_public_release_installed = True
