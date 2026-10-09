from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from bot.config import config
from bot.creator_tariff import quote_video_for_actor, resolve_video_quote
from bot.database import (
    add_credits,
    check_can_afford,
    complete_trend_run_claim,
    deduct_credits,
    get_or_create_user,
    get_prompt_by_id,
    list_trend_reference_assets,
    reserve_trend_run_claim,
    touch_saved_references,
    use_prompt,
)
from bot.seedance_trend_recipe import (
    REFERENCE_CONTRACT,
    SeedanceTrendRecipeError,
    assemble_seedance_trend_inputs,
    assemble_seedance_trend_slot_inputs,
)
from bot.seedance_trend_recipe import (
    SUPPORTED_MODELS as PRIVATE_REFERENCE_MODELS,
)
from bot.services.media_input_utils import (
    is_local_upload_source,
    missing_local_upload_sources,
)
from bot.trend_user_fields import (
    TrendUserFieldsError,
    clean_submitted_user_values,
    render_trend_prompt,
)
from bot.video_reference_policy import (
    get_max_audio_references,
    get_max_video_image_references,
    get_max_video_references,
)

logger = logging.getLogger(__name__)

MAX_TREND_REFERENCES = 12


class TrendRunValidationError(ValueError):
    """Raised when a curated trend cannot be run safely."""


@dataclass(frozen=True)
class TrendRunRequest:
    trend_id: int
    reference_urls: tuple[str, ...]
    user_values: dict[str, str]
    reference_inputs: tuple[dict[str, Any], ...] = ()
    client_request_id: str | None = None


@dataclass(frozen=True)
class TrustedTrendRun:
    trend_id: int
    kind: str
    prompt: str
    model: str
    ratio: str
    reference_urls: tuple[str, ...]
    settings: dict[str, Any]
    template_image_urls: tuple[str, ...] = ()
    template_video_urls: tuple[str, ...] = ()
    template_audio_urls: tuple[str, ...] = ()
    user_reference_inputs: tuple[dict[str, Any], ...] = ()
    assembled_image_urls: tuple[str, ...] = ()
    assembled_video_urls: tuple[str, ...] = ()
    assembled_audio_urls: tuple[str, ...] = ()
    reference_contract: str = ""

    @property
    def provider_image_urls(self) -> tuple[str, ...]:
        return self.assembled_image_urls or (
            *self.reference_urls,
            *self.template_image_urls,
        )

    @property
    def provider_video_urls(self) -> tuple[str, ...]:
        return self.assembled_video_urls or self.template_video_urls

    @property
    def provider_audio_urls(self) -> tuple[str, ...]:
        return self.assembled_audio_urls or self.template_audio_urls


def _fallback_trend_settings(trend: Mapping[str, Any]) -> dict[str, Any]:
    tags = {
        str(tag or "").strip().lower()
        for tag in list(trend.get("tags") or [])
        if str(tag or "").strip()
    }
    model = str(trend.get("model") or "").strip()
    is_video = (
        str(trend.get("category") or "").strip().lower() == "video"
        or "trend-video" in tags
    )
    if not is_video:
        return {
            "kind": "image",
            "user_input": "photo",
            "model": model or "banana_pro",
            "ratio": "1:1",
            "quality": "2K" if model in {"banana_pro", "banana_2"} else "basic",
            "count": 1,
            "nsfw_checker": False,
            "nsfw_enabled": False,
        }

    return {
        "kind": "video",
        "user_input": "photo",
        "model": model or "v3_pro",
        "scenario": "imgtxt",
        "ratio": "16:9",
        "duration": 5,
        "grok_mode": "normal",
        "grok_resolution": "480p",
        "veo_generation_type": "IMAGE_2_VIDEO",
        "veo_translation": True,
        "veo_resolution": "720p",
        "veo_seed": None,
        "veo_watermark": "",
        "kling_negative_prompt": "",
        "kling_cfg_scale": 0.5,
        "omni_resolution": "720p",
        "omni_seed": None,
        "omni_audio_ids": [],
        "omni_character_ids": [],
        "omni_base_voice": "achernar",
        "omni_voice_name": "",
        "omni_voice_description": "",
        "omni_example_dialogue": "",
        "omni_character_name": "",
        "omni_character_audio_ids": [],
    }


def _clean_reference_urls(raw_urls: Any, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(raw_urls, list):
        raise TrendRunValidationError("Передайте список фото-референсов")

    cleaned: list[str] = []
    for raw_url in raw_urls:
        url = str(raw_url or "").strip()
        if not url or url in cleaned:
            continue
        if url.startswith(("blob:", "data:", "file:")):
            raise TrendRunValidationError(
                "Дождитесь окончания загрузки референсов и попробуйте снова"
            )
        if not url.startswith(("https://", "http://", "/uploads/")):
            raise TrendRunValidationError("Некорректная ссылка на референс")
        cleaned.append(url)
        if len(cleaned) > MAX_TREND_REFERENCES:
            raise TrendRunValidationError(
                f"Слишком много референсов. Максимум: {MAX_TREND_REFERENCES}"
            )

    if not cleaned and not allow_empty:
        raise TrendRunValidationError("Загрузите хотя бы одно фото")
    return tuple(cleaned)


def _clean_reference_inputs(raw_inputs: Any) -> tuple[dict[str, Any], ...]:
    if raw_inputs is None:
        return ()
    if not isinstance(raw_inputs, list):
        raise TrendRunValidationError("Передайте типизированные референсы списком")
    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    seen_urls: set[str] = set()
    for raw in raw_inputs:
        if not isinstance(raw, Mapping):
            raise TrendRunValidationError("Некорректный слот референса")
        media_type = str(raw.get("media_type") or "").strip().lower()
        try:
            position = int(raw.get("position"))
        except (TypeError, ValueError) as exc:
            raise TrendRunValidationError("Некорректная позиция референса") from exc
        urls = _clean_reference_urls([raw.get("url")])
        key = (media_type, position)
        if (
            media_type not in {"image", "video", "audio"}
            or position < 1
            or key in seen
            or urls[0] in seen_urls
        ):
            raise TrendRunValidationError("Некорректный или повторяющийся слот референса")
        seen.add(key)
        seen_urls.add(urls[0])
        cleaned.append(
            {"media_type": media_type, "position": position, "url": urls[0]}
        )
        if len(cleaned) > MAX_TREND_REFERENCES:
            raise TrendRunValidationError(
                f"Слишком много референсов. Максимум: {MAX_TREND_REFERENCES}"
            )
    return tuple(cleaned)


def _local_reference_media_type(url: str) -> str | None:
    match = re.search(r"/uploads/refs/(image|video|audio)/\d+/", str(url or ""))
    return match.group(1) if match else None


def parse_trend_run_request(body: Any) -> TrendRunRequest:
    """Accept a trend ID, uploaded references and declared template values.

    Any client-supplied model, prompt, ratio, quality, duration or provider
    options are deliberately ignored. Template values are validated against
    the administrator-owned ``generation_settings.user_fields`` schema before
    they are interpolated into the hidden prompt on the server.
    """

    if not isinstance(body, Mapping):
        raise TrendRunValidationError("Некорректный запрос")

    raw_trend_id = body.get("trend_id")
    if not str(raw_trend_id or "").isdigit():
        raise TrendRunValidationError("Тренд не найден")

    try:
        user_values = clean_submitted_user_values(body.get("user_values"))
    except TrendUserFieldsError as exc:
        raise TrendRunValidationError(str(exc)) from exc

    client_request_id = str(body.get("client_request_id") or "").strip() or None
    if client_request_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", client_request_id):
        raise TrendRunValidationError("Некорректный идентификатор запуска тренда")

    reference_inputs = _clean_reference_inputs(body.get("reference_inputs"))
    reference_urls = _clean_reference_urls(
        body.get("reference_urls"),
        allow_empty=bool(reference_inputs),
    )
    if reference_inputs:
        typed_urls = tuple(str(item["url"]) for item in reference_inputs)
        if reference_urls and reference_urls != typed_urls:
            raise TrendRunValidationError("Состав референсов запуска не совпадает со слотами")
        reference_urls = typed_urls

    return TrendRunRequest(
        trend_id=int(raw_trend_id),
        reference_urls=reference_urls,
        user_values=user_values,
        reference_inputs=reference_inputs,
        client_request_id=client_request_id,
    )


def trusted_trend_run(
    trend: Mapping[str, Any] | None,
    reference_urls: tuple[str, ...],
    user_values: Mapping[str, str] | None = None,
    *,
    template_assets: Sequence[Mapping[str, Any]] = (),
    reference_inputs: Sequence[Mapping[str, Any]] = (),
) -> TrustedTrendRun:
    if not trend:
        raise TrendRunValidationError("Тренд не найден")
    if trend.get("status") != "approved" or not bool(trend.get("is_public")):
        raise TrendRunValidationError("Тренд недоступен")

    tags = {
        str(tag or "").strip().lower()
        for tag in list(trend.get("tags") or [])
        if str(tag or "").strip()
    }
    if "trend" not in tags:
        raise TrendRunValidationError("Выбранный шаблон не является трендом")

    stored_settings = trend.get("generation_settings")
    settings = (
        dict(stored_settings)
        if isinstance(stored_settings, Mapping) and stored_settings
        else _fallback_trend_settings(trend)
    )
    if not settings:
        raise TrendRunValidationError(
            "Настройки тренда не сохранены. Администратору нужно пересоздать тренд"
        )
    kind = str(settings.get("kind") or "").strip().lower()
    if kind not in {"image", "video"}:
        raise TrendRunValidationError("Неизвестный тип тренда")
    if str(settings.get("user_input") or "photo") != "photo":
        raise TrendRunValidationError("Этот тренд не поддерживает фото-референсы")
    if str(settings.get("genjutsu_recipe_id") or "").strip():
        raise TrendRunValidationError(
            "Этот Genjutsu-тренд запускается через актуальную студию. Обновите Mini App."
        )

    prompt = str(trend.get("prompt_text") or "").strip()
    try:
        prompt = render_trend_prompt(prompt, settings, user_values)
    except TrendUserFieldsError as exc:
        raise TrendRunValidationError(str(exc)) from exc
    model = str(settings.get("model") or trend.get("model") or "").strip()
    ratio = str(settings.get("ratio") or "").strip()
    if not prompt or not model or not ratio:
        raise TrendRunValidationError(
            "Настройки тренда заполнены не полностью. "
            "Администратору нужно пересохранить тренд"
        )

    reference_contract = str(settings.get("reference_contract") or "").strip()
    template_images: tuple[str, ...] = ()
    template_videos: tuple[str, ...] = ()
    template_audios: tuple[str, ...] = ()
    assembled_images: tuple[str, ...] = ()
    assembled_videos: tuple[str, ...] = ()
    assembled_audios: tuple[str, ...] = ()
    if reference_contract:
        if reference_contract != REFERENCE_CONTRACT:
            raise TrendRunValidationError("Неизвестный контракт референсов тренда")
        if kind != "video" or model not in PRIVATE_REFERENCE_MODELS:
            raise TrendRunValidationError(
                "Приватные референсы поддерживаются только в Seedance 2.0/2.5 трендах"
            )
        try:
            reference_plan_version = int(settings.get("reference_plan_version") or 1)
        except (TypeError, ValueError) as exc:
            raise TrendRunValidationError("Повреждена версия плана референсов") from exc
        if not template_assets and reference_plan_version < 2:
            raise TrendRunValidationError(
                "Закреплённые референсы тренда недоступны. Обратитесь к администратору"
            )
        try:
            if reference_plan_version >= 2:
                raw_slots = settings.get("reference_slots")
                if not isinstance(raw_slots, list) or not raw_slots:
                    raise SeedanceTrendRecipeError("Trend reference slot plan is missing")
                provider_images, provider_videos, provider_audios = (
                    assemble_seedance_trend_slot_inputs(
                        reference_inputs,
                        raw_slots,
                        template_assets,
                    )
                )
            else:
                provider_images, provider_videos, provider_audios = assemble_seedance_trend_inputs(
                    reference_urls,
                    template_assets,
                )
        except SeedanceTrendRecipeError as exc:
            raise TrendRunValidationError(str(exc)) from exc
        template_images = tuple(
            str(asset.get("file_url") or "").strip()
            for asset in template_assets
            if str(asset.get("media_type") or "").strip().lower() == "image"
        )
        template_videos = tuple(
            str(asset.get("file_url") or "").strip()
            for asset in template_assets
            if str(asset.get("media_type") or "").strip().lower() == "video"
        )
        template_audios = tuple(
            str(asset.get("file_url") or "").strip()
            for asset in template_assets
            if str(asset.get("media_type") or "").strip().lower() == "audio"
        )
        assembled_images = tuple(provider_images)
        assembled_videos = tuple(provider_videos)
        assembled_audios = tuple(provider_audios)
        for key, actual in (
            ("fixed_image_reference_count", len(template_images)),
            ("fixed_video_reference_count", len(template_videos)),
            ("fixed_audio_reference_count", len(template_audios)),
        ):
            try:
                configured = int(settings.get(key) or 0)
            except (TypeError, ValueError) as exc:
                raise TrendRunValidationError("Повреждены настройки референсов тренда") from exc
            if configured != actual:
                raise TrendRunValidationError(
                    "Состав закреплённых референсов тренда изменился. "
                    "Администратору нужно пересохранить тренд"
                )

    return TrustedTrendRun(
        trend_id=int(trend["id"]),
        kind=kind,
        prompt=prompt,
        model=model,
        ratio=ratio,
        reference_urls=reference_urls,
        settings=settings,
        template_image_urls=template_images,
        template_video_urls=template_videos,
        template_audio_urls=template_audios,
        user_reference_inputs=tuple(dict(item) for item in reference_inputs),
        assembled_image_urls=assembled_images,
        assembled_video_urls=assembled_videos,
        assembled_audio_urls=assembled_audios,
        reference_contract=reference_contract,
    )


def _int_setting(settings: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _optional_int(settings: Mapping[str, Any], key: str) -> int | None:
    value = settings.get(key)
    if value in (None, "", False):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(
    settings: Mapping[str, Any],
    key: str,
    default: float | None = None,
) -> float | None:
    value = settings.get(key)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_list(settings: Mapping[str, Any], key: str) -> list[str]:
    raw = settings.get(key)
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def estimate_trend_repeat_cost(
    trend: Mapping[str, Any] | TrustedTrendRun,
    *, tariff: str = "standard",
) -> float | None:
    """Return the current retail cost for repeating a saved trend.

    Pricing is resolved from the same live pricing services used by the launch
    path. The client never computes or stores its own trend price.
    """

    from bot import miniapp as miniapp_module

    if isinstance(trend, TrustedTrendRun) or hasattr(trend, "settings"):
        settings = dict(getattr(trend, "settings", {}) or {})
        model = str(getattr(trend, "model", "") or "").strip()
        kind = str(
            getattr(trend, "kind", "")
            or settings.get("kind")
            or ("video" if model == "seedance_2_5" else "")
        ).strip().lower()
    else:
        stored_settings = trend.get("generation_settings")
        settings = (
            dict(stored_settings)
            if isinstance(stored_settings, Mapping) and stored_settings
            else _fallback_trend_settings(trend)
        )
        kind = str(settings.get("kind") or "").strip().lower()
        model = str(settings.get("model") or trend.get("model") or "").strip()

    if not model or kind not in {"image", "video"}:
        return None

    try:
        if kind == "image":
            quality = str(settings.get("quality") or "basic")
            return float(miniapp_module._resolve_image_unit_cost(model, quality))

        duration = _int_setting(settings, "duration", 5)
        pricing_duration = (
            _int_setting(settings, "source_video_duration_seconds", 5)
            if bool(settings.get("seedance25_video_editing", False))
            else duration
        )
        provider_video_urls = tuple(
            str(value or "").strip()
            for value in getattr(trend, "provider_video_urls", ()) or ()
            if str(value or "").strip()
        )
        try:
            fixed_video_count = int(settings.get("fixed_video_reference_count") or 0)
        except (TypeError, ValueError):
            fixed_video_count = 0
        raw_slots = settings.get("reference_slots")
        has_replaceable_video = isinstance(raw_slots, list) and any(
            isinstance(slot, Mapping)
            and str(slot.get("media_type") or "").strip().lower() == "video"
            for slot in raw_slots
        )
        pricing_video_refs = provider_video_urls or (
            ("video-reference",)
            if fixed_video_count > 0 or has_replaceable_video
            else ()
        )
        if model == "seedance_2_5":
            resolution = str(
                settings.get("seedance25_resolution") or "720p"
            ).strip().lower()
            return resolve_video_quote(
                model, pricing_duration, resolution, pricing_video_refs, tariff=tariff,
            ).cost

        scenario = str(settings.get("scenario") or "imgtxt")
        effective_model = miniapp_module._resolve_gemini_omni_model(
            model,
            scenario,
        )
        pricing_quality = miniapp_module._video_pricing_quality(
            effective_model,
            str(settings.get("veo_resolution") or "720p"),
            str(settings.get("omni_resolution") or "720p"),
        )
        return resolve_video_quote(
            effective_model, duration, pricing_quality, pricing_video_refs, tariff=tariff,
        ).cost
    except Exception:
        trend_id = getattr(trend, "trend_id", None)
        if trend_id is None and isinstance(trend, Mapping):
            trend_id = trend.get("id")
        logger.exception(
            "Unable to estimate trend repeat cost: trend_id=%s model=%s",
            trend_id,
            model,
        )
        return None


def with_trend_repeat_cost(trend: Mapping[str, Any], *, tariff: str = "standard") -> dict[str, Any]:
    enriched = dict(trend)
    enriched["repeat_cost"] = estimate_trend_repeat_cost(trend, tariff=tariff)
    return enriched


async def _record_trend_use(
    trend_id: int,
    user_id: int,
    *,
    credits_spent: float,
) -> None:
    try:
        await use_prompt(trend_id, user_id, credits_spent=credits_spent)
    except Exception:
        logger.exception("Failed to record trend use: trend_id=%s", trend_id)


async def _debit_for_generation(
    telegram_id: int,
    user: Any,
    amount: float,
) -> tuple[bool, web.Response | None]:
    if config.is_admin(telegram_id):
        return False, None
    if not await check_can_afford(telegram_id, amount):
        return False, web.json_response(
            {
                "ok": False,
                "error": f"Недостаточно бананов. Нужно {amount}🍌",
                "credits": user.credits,
            },
            status=400,
        )
    if not await deduct_credits(telegram_id, amount):
        return False, web.json_response(
            {"ok": False, "error": "Не удалось списать бананы. Обновите баланс"},
            status=409,
        )
    return True, None


def _validate_uploaded_references(
    references: list[str],
    miniapp_module: Any,
) -> None:
    if miniapp_module._browser_local_reference_urls(references):
        raise TrendRunValidationError(
            "Дождитесь окончания загрузки референсов и попробуйте снова"
        )
    if missing_local_upload_sources(references):
        raise TrendRunValidationError(
            "Один или несколько референсов уже удалены. Загрузите их заново"
        )


async def _run_image_trend(
    request: web.Request,
    *,
    telegram_id: int,
    user: Any,
    trend: TrustedTrendRun,
) -> web.Response:
    from bot import miniapp as miniapp_module

    model_meta = next(
        (item for item in miniapp_module.IMAGE_MODELS if item["id"] == trend.model),
        None,
    )
    if not model_meta:
        raise TrendRunValidationError("Модель фото-тренда больше недоступна")
    if trend.ratio not in model_meta.get("ratios", []):
        raise TrendRunValidationError("Формат фото-тренда больше не поддерживается")

    max_references = int(model_meta.get("max_references", 0) or 0)
    if max_references and len(trend.reference_urls) > max_references:
        raise TrendRunValidationError(
            f"Слишком много референсов. Максимум: {max_references}"
        )

    quality = str(trend.settings.get("quality") or "basic")
    allowed_qualities = list(model_meta.get("qualities") or [])
    if trend.model in {"banana_pro", "banana_2"}:
        allowed_qualities = ["1K", "2K", "4K"]
    if allowed_qualities and quality not in allowed_qualities:
        raise TrendRunValidationError("Качество фото-тренда больше не поддерживается")

    configured_count = _int_setting(trend.settings, "count", 1)
    if configured_count != 1:
        raise TrendRunValidationError(
            "Тренд нужно пересохранить с одной генерацией за запуск"
        )

    references = list(trend.reference_urls)
    _validate_uploaded_references(references, miniapp_module)
    await touch_saved_references(telegram_id, references, kind="image")

    cost = estimate_trend_repeat_cost(trend)
    if cost is None:
        raise TrendRunValidationError("Не удалось определить стоимость фото-тренда")
    debited, debit_error = await _debit_for_generation(telegram_id, user, cost)
    if debit_error is not None:
        return debit_error

    launched = False
    try:
        launch_result = await miniapp_module._start_image_generation_task_lazy(
            user=user,
            telegram_id=telegram_id,
            img_service=trend.model,
            prompt=trend.prompt,
            img_ratio=trend.ratio,
            reference_images=references,
            unit_cost=cost,
            img_quality=quality,
            img_nsfw_checker=bool(trend.settings.get("nsfw_checker", False)),
            nsfw_enabled=bool(trend.settings.get("nsfw_enabled", False)),
            callback_url=(
                config.kie_notification_url if config.WEBHOOK_HOST else None
            ),
            prompt_source_id=trend.trend_id,
            action_type="trend",
        )
        if launch_result["status"] == "failed":
            if debited:
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": "Не удалось запустить тренд. Бананы уже возвращены.",
                },
                status=500,
            )
        launched = True

        await miniapp_module._notify_miniapp_image_task_queued(
            request.app,
            telegram_id,
            launch_result,
            img_service=trend.model,
            img_ratio=trend.ratio,
            unit_cost=cost,
        )
        await miniapp_module._deliver_miniapp_direct_image_result(
            request.app,
            telegram_id,
            launch_result,
            img_service=trend.model,
            img_ratio=trend.ratio,
            unit_cost=cost,
            prompt_hidden=True,
        )
        await _record_trend_use(
            trend.trend_id,
            user.id,
            credits_spent=float(cost),
        )

        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "image"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model": trend.model,
                "model_label": miniapp_module.get_image_model_label(trend.model),
                "aspect_ratio": trend.ratio,
                "duration": None,
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "trend_id": trend.trend_id,
            }
        )
    except Exception:
        if debited and not launched:
            await add_credits(telegram_id, cost)
        raise


async def _run_video_trend(
    *,
    telegram_id: int,
    user: Any,
    trend: TrustedTrendRun,
) -> web.Response:
    from bot import miniapp as miniapp_module

    private_reference_run = trend.reference_contract == REFERENCE_CONTRACT
    scenario = str(trend.settings.get("scenario") or "imgtxt")
    if private_reference_run:
        if trend.model != "seedance_2":
            raise TrendRunValidationError("Неверный runtime приватного Seedance-тренда")
        runtime_generation_type = "video"
    else:
        if scenario != "imgtxt":
            raise TrendRunValidationError(
                "Видео-тренд должен быть сохранён в режиме «Фото + текст»"
            )
        runtime_generation_type = scenario

    model_meta = miniapp_module._find_video_model_meta(trend.model)
    if not model_meta:
        raise TrendRunValidationError("Модель видео-тренда больше недоступна")
    if not private_reference_run and scenario not in model_meta.get("supports", []):
        raise TrendRunValidationError("Модель тренда больше не поддерживает фото")
    if trend.ratio not in model_meta.get("ratios", []):
        raise TrendRunValidationError("Формат видео-тренда больше не поддерживается")

    duration = _int_setting(trend.settings, "duration", 5)
    if duration not in model_meta.get("durations", []):
        raise TrendRunValidationError(
            "Длительность видео-тренда больше не поддерживается"
        )

    provider_images = list(trend.provider_image_urls)
    max_extra_references = int(model_meta.get("max_image_references", 0) or 0)
    max_references = (
        get_max_video_image_references(trend.model)
        if private_reference_run
        else max(1, max_extra_references + 1)
    )
    if max_references and len(provider_images) > max_references:
        raise TrendRunValidationError(
            f"В тренде слишком много фото-референсов. Максимум: {max_references}"
        )
    max_videos = get_max_video_references(trend.model)
    if len(trend.provider_video_urls) > max_videos:
        raise TrendRunValidationError(
            f"В тренде слишком много видео-референсов. Максимум: {max_videos}"
        )
    max_audio = get_max_audio_references(trend.model)
    if len(trend.provider_audio_urls) > max_audio:
        raise TrendRunValidationError(
            f"В тренде слишком много аудио-референсов. Максимум: {max_audio}"
        )

    image_url = provider_images[0]
    image_references = provider_images[1:]
    all_references = [
        *provider_images,
        *trend.provider_video_urls,
        *trend.provider_audio_urls,
    ]
    _validate_uploaded_references(all_references, miniapp_module)
    if trend.user_reference_inputs:
        for media_type in ("image", "video", "audio"):
            user_urls = [
                str(item["url"])
                for item in trend.user_reference_inputs
                if item.get("media_type") == media_type
            ]
            if user_urls:
                await touch_saved_references(telegram_id, user_urls, kind=media_type)
    else:
        await touch_saved_references(telegram_id, list(trend.reference_urls), kind="image")

    effective_model = miniapp_module._resolve_gemini_omni_model(
        trend.model,
        scenario,
    )
    veo_resolution = str(trend.settings.get("veo_resolution") or "720p")
    omni_resolution = str(trend.settings.get("omni_resolution") or "720p")
    billing_quote = await quote_video_for_actor(
        telegram_id, effective_model, duration,
        miniapp_module._video_pricing_quality(effective_model, veo_resolution, omni_resolution),
        trend.provider_video_urls,
    )
    cost = billing_quote.cost

    debited, debit_error = await _debit_for_generation(telegram_id, user, cost)
    if debit_error is not None:
        return debit_error

    launched = False
    launch_observation = {}
    refund_attempted = False
    try:
        launch_result = await miniapp_module._launch_video_generation_task(
            telegram_id=telegram_id,
            user=user,
            model=effective_model,
            billing_quote=billing_quote,
            _launch_observation=launch_observation,
            prompt=trend.prompt,
            duration=duration,
            aspect_ratio=trend.ratio,
            generation_type=runtime_generation_type,
            image_url=image_url,
            image_references=image_references,
            video_references=list(trend.provider_video_urls),
            audio_references=list(trend.provider_audio_urls),
            grok_mode=str(trend.settings.get("grok_mode") or "normal"),
            grok_resolution=str(
                trend.settings.get("grok_resolution") or "480p"
            ),
            veo_generation_type=str(
                trend.settings.get("veo_generation_type") or "IMAGE_2_VIDEO"
            ),
            veo_translation=bool(trend.settings.get("veo_translation", True)),
            veo_resolution=veo_resolution,
            veo_seed=_optional_int(trend.settings, "veo_seed"),
            veo_watermark=(
                str(trend.settings.get("veo_watermark") or "") or None
            ),
            kling_negative_prompt=(
                str(trend.settings.get("kling_negative_prompt") or "") or None
            ),
            kling_cfg_scale=_optional_float(
                trend.settings,
                "kling_cfg_scale",
                0.5,
            ),
            omni_resolution=omni_resolution,
            omni_seed=_optional_int(trend.settings, "omni_seed"),
            omni_audio_ids=_string_list(trend.settings, "omni_audio_ids"),
            omni_character_ids=_string_list(
                trend.settings,
                "omni_character_ids",
            ),
            omni_base_voice=str(
                trend.settings.get("omni_base_voice") or "achernar"
            ),
            omni_voice_name=(
                str(trend.settings.get("omni_voice_name") or "") or None
            ),
            omni_voice_description=(
                str(trend.settings.get("omni_voice_description") or "") or None
            ),
            omni_example_dialogue=(
                str(trend.settings.get("omni_example_dialogue") or "") or None
            ),
            omni_character_name=(
                str(trend.settings.get("omni_character_name") or "") or None
            ),
            omni_character_audio_ids=_string_list(
                trend.settings,
                "omni_character_audio_ids",
            )[:1],
            action_type="trend",
            prompt_source_id=trend.trend_id,
            reference_contract=trend.reference_contract or None,
            fixed_asset_counts={
                "image": len(trend.template_image_urls),
                "video": len(trend.template_video_urls),
                "audio": len(trend.template_audio_urls),
            },
        )
        if launch_result["status"] == "failed":
            if debited:
                refund_attempted = True
                await add_credits(telegram_id, cost)
            return web.json_response(
                {
                    "ok": False,
                    "error": launch_result.get("error")
                    or "Не удалось запустить видео-тренд. Бананы уже возвращены.",
                },
                status=500,
            )
        launched = True

        await _record_trend_use(
            trend.trend_id,
            user.id,
            credits_spent=float(cost),
        )
        fresh_user = await get_or_create_user(telegram_id)
        return web.json_response(
            {
                "ok": True,
                "status": launch_result["status"],
                "task_id": launch_result["task_id"],
                "saved_url": launch_result.get("saved_url"),
                "task_type": launch_result.get("task_type", "video"),
                "credits": fresh_user.credits,
                "cost": cost,
                "model": effective_model,
                "model_label": miniapp_module.get_video_model_label(
                    effective_model
                ),
                "aspect_ratio": trend.ratio,
                "duration": duration,
                "prompt_hidden": True,
                "prompt_actions_allowed": False,
                "trend_id": trend.trend_id,
            }
        )
    except Exception:
        if debited and not launched and not launch_observation.get("accepted") and not refund_attempted:
            await add_credits(telegram_id, cost)
        raise


def _trend_run_request_hash(parsed: TrendRunRequest) -> str:
    payload = {
        "trend_id": parsed.trend_id,
        "reference_urls": list(parsed.reference_urls),
        "reference_inputs": list(parsed.reference_inputs),
        "user_values": dict(sorted(parsed.user_values.items())),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trend_response_payload(response: web.StreamResponse) -> dict[str, Any]:
    body = getattr(response, "body", None)
    if not body:
        return {"ok": False, "error": "Пустой ответ запуска тренда"}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return {"ok": False, "error": "Некорректный ответ запуска тренда"}
    return (
        parsed
        if isinstance(parsed, dict)
        else {"ok": False, "error": "Некорректный ответ запуска тренда"}
    )


async def _safe_complete_trend_run_claim(
    *,
    claim_context: tuple[int, int, str],
    status: str,
    http_status: int,
    response_payload: dict[str, Any],
    task_id: str | None = None,
) -> None:
    try:
        await complete_trend_run_claim(
            user_id=claim_context[0],
            trend_id=claim_context[1],
            client_request_id=claim_context[2],
            status=status,
            http_status=http_status,
            response_payload=response_payload,
            task_id=task_id,
        )
    except Exception:
        logger.exception(
            "Failed to finalize trend run claim: user_id=%s trend_id=%s request_id=%s",
            claim_context[0],
            claim_context[1],
            claim_context[2],
        )


async def miniapp_run_trend(request: web.Request) -> web.Response:
    """Run a curated trend using only settings stored by an administrator."""

    claim_context: tuple[int, int, str] | None = None
    claim_reserved = False
    try:
        body = await request.json()
        parsed = parse_trend_run_request(body)

        from bot import miniapp as miniapp_module

        telegram_id, context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        user = context["user"]
        prompt = await get_prompt_by_id(
            parsed.trend_id,
            approved_public_only=True,
        )
        if not prompt:
            raise TrendRunValidationError("Тренд не найден")

        if parsed.client_request_id:
            claim_context = (int(user.id), parsed.trend_id, parsed.client_request_id)
            claim = await reserve_trend_run_claim(
                user_id=claim_context[0],
                trend_id=claim_context[1],
                client_request_id=claim_context[2],
                request_hash=_trend_run_request_hash(parsed),
            )
            if not claim.get("claimed"):
                if claim.get("conflict"):
                    return web.json_response(
                        {
                            "ok": False,
                            "error": "Этот идентификатор уже использован для другого запуска",
                            "retry_same_request": False,
                        },
                        status=409,
                    )
                previous = claim.get("response")
                if isinstance(previous, Mapping):
                    return web.json_response(
                        dict(previous),
                        status=int(claim.get("http_status") or 200),
                    )
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Этот запуск уже обрабатывается. Не нажимайте кнопку повторно.",
                        "retry_same_request": True,
                    },
                    status=409,
                )
            claim_reserved = True

        raw_settings = prompt.get("generation_settings")
        settings = raw_settings if isinstance(raw_settings, Mapping) else {}
        template_assets: Sequence[Mapping[str, Any]] = ()
        if str(settings.get("reference_contract") or "").strip():
            template_assets = await list_trend_reference_assets(parsed.trend_id)
        if str(settings.get("reference_contract") or "").strip():
            trend = trusted_trend_run(
                prompt,
                parsed.reference_urls,
                parsed.user_values,
                template_assets=template_assets,
                reference_inputs=parsed.reference_inputs,
            )
        else:
            trend = trusted_trend_run(prompt, parsed.reference_urls, parsed.user_values)

        if trend.reference_contract == REFERENCE_CONTRACT:
            typed_by_url = {
                str(item.get("url") or ""): str(item.get("media_type") or "")
                for item in trend.user_reference_inputs
            }
            for identity_url in trend.reference_urls:
                owner_telegram_id = miniapp_module._reference_upload_owner_telegram_id(
                    identity_url
                )
                if (
                    owner_telegram_id != int(telegram_id)
                    or not is_local_upload_source(identity_url)
                ):
                    raise TrendRunValidationError(
                        "Для повтора загрузите своё фото или другие свои референсы через форму тренда"
                    )
                expected_media_type = typed_by_url.get(identity_url)
                if (
                    expected_media_type
                    and _local_reference_media_type(identity_url)
                    != expected_media_type
                ):
                    raise TrendRunValidationError(
                        "Тип загруженного файла не совпадает со слотом тренда"
                    )
            logger.info(
                "Seedance trend references validated: trend_id=%s user_id=%s plan_version=%s user_slots=%s fixed_assets=%s",
                trend.trend_id,
                user.id,
                trend.settings.get("reference_plan_version") or 1,
                [
                    f"{item.get('media_type')}:{item.get('position')}"
                    for item in trend.user_reference_inputs
                ]
                or ["image:1"],
                len(template_assets),
            )

        if trend.reference_contract == REFERENCE_CONTRACT and trend.model == "seedance_2":
            from bot.services.trend_reference_storage import (
                TrendReferenceStorageError,
                validate_seedance2_reference_videos,
            )

            try:
                await validate_seedance2_reference_videos(list(trend.provider_video_urls))
            except TrendReferenceStorageError as exc:
                raise TrendRunValidationError(str(exc)) from exc

        if trend.kind == "video":
            response = await _run_video_trend(
                telegram_id=telegram_id,
                user=user,
                trend=trend,
            )
        else:
            response = await _run_image_trend(
                request,
                telegram_id=telegram_id,
                user=user,
                trend=trend,
            )

        response_payload = _trend_response_payload(response)
        if int(response.status) >= 400:
            response_payload["retry_same_request"] = False
            response = web.json_response(response_payload, status=int(response.status))

        if claim_reserved and claim_context:
            await _safe_complete_trend_run_claim(
                claim_context=claim_context,
                status="completed" if int(response.status) < 400 else "failed",
                http_status=int(response.status),
                response_payload=response_payload,
                task_id=str(response_payload.get("task_id") or "") or None,
            )
        return response
    except TrendRunValidationError as error:
        response = web.json_response(
            {"ok": False, "error": str(error), "retry_same_request": False},
            status=400,
        )
        if claim_reserved and claim_context:
            await _safe_complete_trend_run_claim(
                claim_context=claim_context,
                status="failed",
                http_status=400,
                response_payload=_trend_response_payload(response),
            )
        return response
    except Exception:
        logger.exception("Mini App trend generation failed")
        response = web.json_response(
            {
                "ok": False,
                "error": "Не удалось запустить тренд. Попробуйте ещё раз.",
                "retry_same_request": True,
            },
            status=500,
        )
        # Keep a reserved claim in processing state. The provider may already
        # have accepted the task before the local exception, so marking it
        # failed and allowing a new request id could create a duplicate charge.
        return response


def setup_trend_routes(app: web.Application, miniapp_root: str) -> None:
    """Register the exact route before Mini App's catch-all API handler."""

    app.router.add_post(miniapp_root + "/api/trends/run", miniapp_run_trend)
