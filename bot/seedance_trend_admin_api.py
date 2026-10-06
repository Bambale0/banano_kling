"""Admin API for private-reference Seedance trends from tasks or owned uploads."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

from bot.config import config
from bot.database import (
    approve_prompt,
    create_prompt,
    get_active_seedance_trend_by_source_generation,
    get_active_seedance_trend_by_upload_fingerprint,
    get_generation_task_payload,
)
from bot.seedance_trend_recipe import (
    REFERENCE_CONTRACT,
    REFERENCE_PLAN_VERSION,
    SUPPORTED_MODELS,
    SeedanceTrendRecipeError,
    SeedanceUserReferenceSlot,
    compile_seedance_trend_recipe,
    extract_seedance_reference_snapshot,
)
from bot.services.feed_persist import persist_feed_result_urls
from bot.services.media_input_utils import (
    is_local_upload_source,
    resolve_local_upload_path,
)
from bot.services.trend_reference_storage import (
    TrendReferenceStorageError,
    persist_trend_reference,
    validate_seedance2_reference_videos,
    validate_trend_reference_source,
)
from bot.trend_user_fields import normalize_user_fields_settings
from bot.trend_visibility import sanitize_prompt_for_public
from bot.utils.validators import detect_explicit_prompt_policy_violation

logger = logging.getLogger(__name__)

_UPLOAD_PUBLISH_LOCK = web.AppKey("seedance_upload_publish_lock", asyncio.Lock)

_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")


def _integer_list(value: Any, *, field: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field} должен быть списком")
    result: list[int] = []
    for raw in value:
        try:
            item = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Некорректный индекс в {field}") from exc
        if item not in result:
            result.append(item)
    return result


def _preview_kind(url: str) -> str:
    path = Path(str(url or "").split("?", 1)[0].split("#", 1)[0].lower())
    return "video" if path.suffix in _VIDEO_EXTENSIONS else "image"


def _task_request_data(task: Mapping[str, Any]) -> dict[str, Any]:
    value = task.get("request_data")
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_reference_payload(snapshot: Any) -> dict[str, list[dict[str, Any]]]:
    return {
        "images": [
            {
                "index": index,
                "preview_url": url,
                "default_action": "replace_with_user" if index == 1 else "keep_hidden",
            }
            for index, url in enumerate(snapshot.images, start=1)
        ],
        "videos": [
            {"index": index, "preview_url": url, "default_action": "keep_hidden"}
            for index, url in enumerate(snapshot.videos, start=1)
        ],
        "audios": [
            {"index": index, "preview_url": url, "default_action": "keep_hidden"}
            for index, url in enumerate(snapshot.audios, start=1)
        ],
    }


async def _admin_source_task(
    request: web.Request,
    body: Mapping[str, Any],
) -> tuple[int, Any, dict[str, Any]]:
    from bot import miniapp as miniapp_module

    telegram_id, context = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    if not config.is_admin(telegram_id):
        raise web.HTTPForbidden(text="Нет доступа")
    task_id = str(body.get("task_id") or body.get("source_task_id") or "").strip()
    if not task_id:
        raise ValueError("Выберите готовую Seedance-задачу")
    task = await get_generation_task_payload(task_id, user_id=context["user"].id)
    if not task:
        raise web.HTTPNotFound(text="Задача не найдена")
    model = str(task.get("model") or "").strip()
    if model not in SUPPORTED_MODELS or str(task.get("type") or "") != "video":
        raise ValueError(
            "Тренд с закреплёнными референсами поддерживает только Seedance 2.0/2.5"
        )
    if str(task.get("status") or "") != "completed" or not task.get("result_url"):
        raise ValueError("Сначала дождитесь готового результата Seedance")
    task_request_data = _task_request_data(task)
    if (
        task.get("source_feed_gen_id")
        or str(task.get("action_type") or "").lower() == "trend"
        or task_request_data.get("trend_id")
    ):
        raise ValueError(
            "Нельзя создавать новый приватный рецепт из чужого повтора или тренда"
        )
    return telegram_id, context["user"], task


async def miniapp_admin_seedance_trend_source(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, Mapping):
            raise TypeError("Некорректный запрос")
        _telegram_id, _user, task = await _admin_source_task(request, body)
        request_data = _task_request_data(task)
        snapshot = extract_seedance_reference_snapshot(
            str(task.get("model") or ""), request_data
        )
        if not snapshot.images:
            raise ValueError("В исходной задаче должно быть фото для замены лица")
        return web.json_response(
            {
                "ok": True,
                "source": {
                    "task_id": task["task_id"],
                    "generation_id": task["id"],
                    "model": task["model"],
                    "duration": task.get("duration"),
                    "aspect_ratio": task.get("aspect_ratio"),
                    "prompt": str(task.get("prompt") or ""),
                    "result_url": task.get("result_url"),
                    "references": _safe_reference_payload(snapshot),
                },
            }
        )
    except (TypeError, ValueError, SeedanceTrendRecipeError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except web.HTTPException as error:
        return web.json_response(
            {"ok": False, "error": str(error.text or "Нет доступа")},
            status=int(error.status),
        )
    except Exception:
        logger.exception("Seedance trend source inspection failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось прочитать исходную Seedance-задачу"},
            status=500,
        )


async def _persist_recipe_assets(recipe: Any) -> list[dict[str, Any]]:
    persisted: list[dict[str, Any]] = []
    # Persist sequentially: a recipe may contain several large videos and loading
    # all of them into memory concurrently can exhaust the production container.
    for asset in recipe.assets:
        stored = await persist_trend_reference(
            asset.source_url,
            media_type=asset.media_type,
        )
        persisted.append(
            {
                **stored.as_dict(),
                "position": asset.position,
                "source_position": asset.source_position,
                "role": asset.role,
                "label": asset.label,
            }
        )
    return persisted


async def _generation_settings(
    task: Mapping[str, Any],
    request_data: Mapping[str, Any],
    recipe: Any,
    persisted_assets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    model = str(task.get("model") or "").strip()
    duration = int(task.get("duration") or request_data.get("duration") or 5)
    ratio = str(
        task.get("aspect_ratio") or request_data.get("aspect_ratio") or "adaptive"
    ).strip()
    video_editing = (
        bool(request_data.get("seedance25_video_editing"))
        if model == "seedance_2_5"
        else False
    )
    editing_source_duration: int | None = None
    replaceable_editing_video = False
    user_slots = tuple(
        getattr(recipe, "user_slots", ())
        or (
            SeedanceUserReferenceSlot(
                media_type="image",
                position=1,
                source_position=1,
                label="ВАШЕ ЛИЦО",
            ),
        )
    )
    if video_editing:
        fixed_videos = [
            asset
            for asset in persisted_assets
            if str(asset.get("media_type") or "").strip().lower() == "video"
        ]
        replaceable_videos = [slot for slot in user_slots if slot.media_type == "video"]
        if len(fixed_videos) + len(replaceable_videos) != 1:
            raise ValueError(
                "Seedance 2.5 video editing trend requires exactly one fixed or replaceable video reference"
            )
        replaceable_editing_video = bool(replaceable_videos)
        source_video_url = (
            str(fixed_videos[0].get("file_url") or "")
            if fixed_videos
            else extract_seedance_reference_snapshot(model, request_data).videos[
                replaceable_videos[0].source_position - 1
            ]
        )
        from bot.handlers import seedance_25_fullstack as fullstack

        measured_duration = await fullstack._validate_local_source(
            source_video_url,
            "video",
        )
        if measured_duration is None or not 4 <= measured_duration <= 30:
            raise ValueError(
                "Editing source video must be locally available and 4–30 seconds long"
            )
        editing_source_duration = math.ceil(measured_duration)
        duration = -1
        ratio = "adaptive"
    settings: dict[str, Any] = {
        "kind": "video",
        "user_input": "photo",
        "model": model,
        "scenario": "multimodal",
        "ratio": ratio,
        "duration": duration,
        "reference_count": len(user_slots),
        "reference_labels": [slot.label for slot in user_slots],
        "reference_slots": [
            {
                "media_type": slot.media_type,
                "position": slot.position,
                "label": slot.label,
            }
            for slot in user_slots
        ],
        "automatic_hidden_references": bool(persisted_assets),
        "reference_contract": REFERENCE_CONTRACT,
        "reference_plan_version": REFERENCE_PLAN_VERSION,
        "identity_image_index": 1,
        "fixed_image_reference_count": len(recipe.image_assets),
        "fixed_video_reference_count": len(recipe.video_assets),
        "fixed_audio_reference_count": len(recipe.audio_assets),
        "seedance25_video_editing": video_editing,
    }
    if editing_source_duration is not None:
        settings["source_video_duration_seconds"] = editing_source_duration
        if replaceable_editing_video:
            settings["required_video_duration_seconds"] = editing_source_duration
    if model == "seedance_2_5":
        settings.update(
            {
                "seedance25_resolution": str(
                    request_data.get("resolution") or "720p"
                ).lower(),
                "generate_audio": bool(request_data.get("generate_audio", True)),
                "return_last_frame": bool(request_data.get("return_last_frame", False)),
                "output_format": str(
                    request_data.get("output_format") or "mp4"
                ).lower(),
                "web_search": bool(request_data.get("web_search", False)),
                "nsfw_checker": bool(request_data.get("nsfw_checker", False)),
            }
        )
    else:
        settings["seedance_resolution"] = str(
            request_data.get("resolution") or "720p"
        ).lower()
    return settings


async def miniapp_admin_publish_seedance_trend(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, Mapping):
            raise TypeError("Некорректный запрос")
        telegram_id, user, task = await _admin_source_task(request, body)
        existing = await get_active_seedance_trend_by_source_generation(
            int(task["id"]),
            author_id=int(user.id),
        )
        if existing:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Из этой Seedance-задачи тренд уже опубликован",
                    "prompt": sanitize_prompt_for_public(existing),
                },
                status=409,
            )
        request_data = _task_request_data(task)
        snapshot = extract_seedance_reference_snapshot(
            str(task.get("model") or ""), request_data
        )

        title = str(body.get("title") or "").strip()[:80]
        description = str(body.get("description") or "").strip()[:240]
        if not title:
            raise ValueError("Укажите название тренда")
        try:
            identity_index = int(body.get("identity_image_index") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Выберите фото лица автора") from exc
        recipe = compile_seedance_trend_recipe(
            prompt=str(task.get("prompt") or ""),
            model=str(task.get("model") or ""),
            source_images=snapshot.images,
            source_videos=snapshot.videos,
            source_audios=snapshot.audios,
            identity_image_index=identity_index,
            fixed_image_indices=_integer_list(
                body.get("fixed_image_indices"), field="fixed_image_indices"
            ),
            fixed_video_indices=_integer_list(
                body.get("fixed_video_indices"), field="fixed_video_indices"
            ),
            fixed_audio_indices=_integer_list(
                body.get("fixed_audio_indices"), field="fixed_audio_indices"
            ),
            replaceable_image_indices=_integer_list(
                body.get("replaceable_image_indices"),
                field="replaceable_image_indices",
            ),
            replaceable_video_indices=_integer_list(
                body.get("replaceable_video_indices"),
                field="replaceable_video_indices",
            ),
            replaceable_audio_indices=_integer_list(
                body.get("replaceable_audio_indices"),
                field="replaceable_audio_indices",
            ),
        )
        policy_error = detect_explicit_prompt_policy_violation(recipe.prompt)
        if policy_error:
            raise ValueError(policy_error)

        assets = await _persist_recipe_assets(recipe)
        settings = await _generation_settings(task, request_data, recipe, assets)
        source_preview_url = str(task.get("result_url") or "").strip()
        if not source_preview_url:
            raise ValueError("Не найден результат для превью тренда")
        persisted_preview = await persist_feed_result_urls(
            [source_preview_url],
            require_local=True,
        )
        if len(persisted_preview) != 1:
            raise ValueError("Не удалось закрепить результат для превью тренда")
        preview_url = persisted_preview[0]
        settings["preview_type"] = _preview_kind(preview_url)

        try:
            prompt = await create_prompt(
                author_id=user.id,
                prompt_text=recipe.prompt,
                title=title,
                description=description or None,
                category="video",
                preview_url=preview_url,
                model=str(task.get("model") or ""),
                tags=["trend", "trend-video", "seedance-private-references"],
                generation_settings=settings,
                is_public=True,
                source_generation_id=int(task["id"]),
                trend_reference_assets=assets,
            )
        except Exception:
            raced = await get_active_seedance_trend_by_source_generation(
                int(task["id"]),
                author_id=int(user.id),
            )
            if raced:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "Из этой Seedance-задачи тренд уже опубликован",
                        "prompt": sanitize_prompt_for_public(raced),
                    },
                    status=409,
                )
            raise
        if not prompt:
            raise RuntimeError("Prompt row was not created")
        approved = await approve_prompt(int(prompt["id"]))
        if not approved:
            raise RuntimeError("Trend approval failed")
        logger.info(
            "Seedance private-reference trend published: trend_id=%s source_task=%s model=%s admin=%s fixed_images=%s fixed_videos=%s fixed_audio=%s user_slots=%s",
            approved["id"],
            task["task_id"],
            task["model"],
            telegram_id,
            len(recipe.image_assets),
            len(recipe.video_assets),
            len(recipe.audio_assets),
            len(recipe.user_slots),
        )
        return web.json_response(
            {"ok": True, "prompt": sanitize_prompt_for_public(approved)}
        )
    except (
        TypeError,
        ValueError,
        SeedanceTrendRecipeError,
        TrendReferenceStorageError,
    ) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except web.HTTPException as error:
        return web.json_response(
            {"ok": False, "error": str(error.text or "Нет доступа")},
            status=int(error.status),
        )
    except Exception:
        logger.exception("Seedance private-reference trend publish failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось опубликовать Seedance-тренд"},
            status=500,
        )


def _upload_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} должен быть целым числом")
    return value


def _upload_indices(value: Any, *, field: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field} должен быть списком")
    result = [_upload_integer(item, field=field) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"Повторяющиеся индексы в {field}")
    return result


def _owned_upload_path(
    value: Any, *, telegram_id: int, media_type: str
) -> tuple[str, Path]:
    """Accept canonical owner-scoped local uploads, never arbitrary URLs/paths."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Загрузите файл через форму тренда")
    url = value.strip()
    parsed = urlsplit(url)
    if (
        parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or "%" in url
        or "\\" in url
        or any(ord(char) < 32 for char in url)
        or not is_local_upload_source(url)
    ):
        raise ValueError("Некорректная ссылка на загруженный файл")
    prefix = f"/uploads/refs/{media_type}/{telegram_id}/"
    if not parsed.path.startswith(prefix):
        raise ValueError("Тип или владелец загруженного файла не совпадает")
    filename = parsed.path[len(prefix) :]
    if any(part in {"", ".", ".."} for part in filename.split("/")):
        raise ValueError("Некорректный путь загруженного файла")
    local_path = resolve_local_upload_path(url)
    if not local_path:
        raise ValueError("Загруженный файл уже удалён. Загрузите его заново")
    path = Path(local_path).resolve()
    owner_root = Path("static/uploads/refs").resolve() / media_type / str(telegram_id)
    try:
        path.relative_to(owner_root)
    except ValueError as exc:
        raise ValueError("Файл находится вне папки владельца") from exc
    if not path.is_file():
        raise ValueError("Загруженный файл недоступен")
    return url, path


def _upload_generation_config(body: Mapping[str, Any], model: str) -> dict[str, Any]:
    from bot import miniapp as miniapp_module
    from bot.services.seedance_25_service import Seedance25Service
    from bot.services.seedance_service import SeedanceService

    editing = body.get("seedance25_video_editing", False)
    if not isinstance(editing, bool):
        raise TypeError("Некорректный режим редактирования видео")
    if editing and model != "seedance_2_5":
        raise ValueError("Редактирование видео поддерживается только Seedance 2.5")
    duration = _upload_integer(body.get("duration", 5), field="duration")
    ratio = str(body.get("aspect_ratio") or "9:16").strip().lower()
    resolution = str(body.get("resolution") or "720p").strip().lower()
    if model == "seedance_2_5":
        from bot.handlers import seedance_25_public_release as public_release

        meta = public_release._public_model_meta()
        resolutions = Seedance25Service.ALLOWED_RESOLUTIONS
    else:
        meta = miniapp_module._find_video_model_meta(model) or {}
        resolutions = SeedanceService.SUPPORTED_RESOLUTIONS
    if resolution not in resolutions:
        raise ValueError("Качество не поддерживается выбранной моделью")
    if duration not in meta.get("durations", []):
        raise ValueError("Длительность не поддерживается выбранной моделью")
    if ratio not in meta.get("ratios", []):
        raise ValueError("Формат кадра не поддерживается выбранной моделью")
    if not editing and duration == -1:
        raise ValueError("Для тренда выберите точную длительность")
    return {
        "duration": -1 if editing else duration,
        "aspect_ratio": "adaptive" if editing else ratio,
        "resolution": resolution,
        "seedance25_video_editing": editing,
    }


async def _upload_reference_sources(
    body: Mapping[str, Any], *, telegram_id: int, model: str
) -> tuple[dict[str, list[str]], dict[str, str], str, str]:
    from bot.video_reference_policy import (
        get_max_audio_references,
        get_max_video_image_references,
        get_max_video_references,
    )

    limits = {
        "image": get_max_video_image_references(model),
        "video": get_max_video_references(model),
        "audio": get_max_audio_references(model),
    }
    sources: dict[str, list[str]] = {}
    paths: set[Path] = set()
    digests: dict[str, str] = {}
    # Validate even excluded inputs. Never deduplicate silently: it changes tags.
    for media_type, limit in limits.items():
        raw = body.get(f"{media_type}_urls", [])
        if not isinstance(raw, list):
            raise TypeError(f"{media_type}_urls должен быть списком")
        if len(raw) > limit:
            raise ValueError(f"Слишком много {media_type}-референсов: максимум {limit}")
        sources[media_type] = []
        for value in raw:
            url, path = _owned_upload_path(
                value, telegram_id=telegram_id, media_type=media_type
            )
            if path in paths:
                raise ValueError("Один файл нельзя добавить в референсы несколько раз")
            paths.add(path)
            digest = await validate_trend_reference_source(url, media_type=media_type)
            if digest in digests.values():
                raise ValueError("Референсы не должны повторять один и тот же файл")
            digests[url] = digest
            sources[media_type].append(url)

    raw_preview = body.get("preview_url")
    if not isinstance(raw_preview, str):
        raise TypeError("Загрузите отдельное публичное превью тренда")
    preview_path = urlsplit(raw_preview).path
    preview_type = (
        "video" if preview_path.startswith("/uploads/refs/video/") else "image"
    )
    if body.get("preview_type") not in {None, preview_type}:
        raise ValueError("Тип превью не совпадает с загруженным файлом")
    preview_url, preview_file = _owned_upload_path(
        raw_preview, telegram_id=telegram_id, media_type=preview_type
    )
    preview_digest = await validate_trend_reference_source(
        preview_url, media_type=preview_type
    )
    if preview_file in paths or preview_digest in digests.values():
        raise ValueError("Превью должно быть отдельным файлом, не приватным референсом")
    digests[preview_url] = preview_digest
    return sources, digests, preview_url, preview_type


async def miniapp_admin_publish_seedance_upload_trend(
    request: web.Request,
) -> web.Response:
    """Publish a private recipe directly from the admin's typed uploads."""
    try:
        body = await request.json()
        if not isinstance(body, Mapping):
            raise TypeError("Некорректный запрос")
        from bot import miniapp as miniapp_module

        telegram_id, context = await miniapp_module._get_user_context(
            request.app,
            str(body.get("init_data") or ""),
            body.get("start_param_fallback"),
        )
        if not config.is_admin(telegram_id):
            raise web.HTTPForbidden(text="Нет доступа")
        user = context["user"]
        model = str(body.get("model") or "").strip()
        if model not in SUPPORTED_MODELS:
            raise ValueError("Поддерживаются только Seedance 2.0/2.5")
        title = str(body.get("title") or "").strip()
        description = str(body.get("description") or "").strip()
        if not title or len(title) > 80 or len(description) > 240:
            raise ValueError(
                "Укажите название до 80 символов и описание до 240 символов"
            )
        prompt_text = str(body.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError("Введите текст промпта")
        settings_input = _upload_generation_config(body, model)
        (
            sources,
            digests,
            source_preview,
            preview_type,
        ) = await _upload_reference_sources(body, telegram_id=telegram_id, model=model)
        selections = {
            f"{mode}_{media_type}_indices": _upload_indices(
                body.get(f"{mode}_{media_type}_indices"),
                field=f"{mode}_{media_type}_indices",
            )
            for mode in ("fixed", "replaceable")
            for media_type in ("image", "video", "audio")
        }
        recipe = compile_seedance_trend_recipe(
            prompt=prompt_text,
            model=model,
            source_images=sources["image"],
            source_videos=sources["video"],
            source_audios=sources["audio"],
            identity_image_index=_upload_integer(
                body.get("identity_image_index"), field="identity_image_index"
            ),
            **selections,
        )
        policy_error = detect_explicit_prompt_policy_violation(recipe.prompt)
        if policy_error:
            raise ValueError(policy_error)
        user_fields = normalize_user_fields_settings(
            {"user_fields": body.get("user_fields", [])}, prompt=recipe.prompt
        )
        request_data = {
            **settings_input,
            "reference_images": sources["image"],
            "v_reference_videos": sources["video"],
            "reference_audios": sources["audio"],
        }
        # Validate the exact included recipe against the same media validator as
        # the generator. Excluded inputs were still checked for owner/type above.
        if model == "seedance_2_5":
            from bot.handlers import seedance_25_fullstack as fullstack

            included: dict[str, list[str]] = {}
            for kind in ("image", "video", "audio"):
                positions = {
                    asset.source_position
                    for asset in recipe.assets
                    if asset.media_type == kind
                } | {
                    slot.source_position
                    for slot in recipe.user_slots
                    if slot.media_type == kind
                }
                included[kind] = [
                    (config.static_base_url.rstrip("/") + url)
                    if url.startswith("/")
                    else url
                    for pos in sorted(positions)
                    for url in [sources[kind][pos - 1]]
                ]
            await fullstack._validate_seedance_sources(
                first_frame_url=None,
                last_frame_url=None,
                image_urls=included["image"],
                video_urls=included["video"],
                audio_urls=included["audio"],
            )
        if model == "seedance_2":
            included_video_positions = {
                asset.source_position
                for asset in recipe.assets
                if asset.media_type == "video"
            } | {
                slot.source_position
                for slot in recipe.user_slots
                if slot.media_type == "video"
            }
            await validate_seedance2_reference_videos(
                [
                    sources["video"][position - 1]
                    for position in sorted(included_video_positions)
                ]
            )
        task = {"model": model, **settings_input}
        # Validate editing counts/duration before copying any private assets.
        provisional_assets = [
            {"media_type": asset.media_type, "file_url": asset.source_url}
            for asset in recipe.assets
        ]
        settings = await _generation_settings(
            task, request_data, recipe, provisional_assets
        )
        settings.update(user_fields)
        settings["preview_type"] = preview_type
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "model": model,
                    "prompt": recipe.prompt,
                    "title": title,
                    "description": description,
                    "settings": settings,
                    "sources": {
                        kind: [digests[url] for url in urls]
                        for kind, urls in sources.items()
                    },
                    "preview": digests[source_preview],
                    "selections": selections,
                    "identity": recipe.identity_source_position,
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        settings["seedance_upload_fingerprint"] = fingerprint

        # Best-effort creation dedupe, including response-loss retries. The
        # process-local lock is not a cross-worker uniqueness guarantee.
        lock = request.app.setdefault(_UPLOAD_PUBLISH_LOCK, asyncio.Lock())
        async with lock:
            existing = await get_active_seedance_trend_by_upload_fingerprint(
                fingerprint, author_id=int(user.id)
            )
            if existing:
                approved = (
                    existing
                    if existing.get("status") == "approved"
                    else await approve_prompt(int(existing["id"]))
                )
                if not approved:
                    raise RuntimeError("Trend approval failed")
                return web.json_response(
                    {"ok": True, "prompt": sanitize_prompt_for_public(approved)}
                )
            assets = await _persist_recipe_assets(recipe)
            persisted_preview = await persist_feed_result_urls(
                [source_preview], require_local=True
            )
            if len(persisted_preview) != 1:
                raise ValueError("Не удалось сохранить превью тренда")
            prompt = await create_prompt(
                author_id=user.id,
                prompt_text=recipe.prompt,
                title=title,
                description=description or None,
                category="video",
                preview_url=persisted_preview[0],
                model=model,
                tags=["trend", "trend-video", "seedance-private-references"],
                generation_settings=settings,
                is_public=True,
                trend_reference_assets=assets,
            )
            if not prompt:
                raise RuntimeError("Prompt row was not created")
            approved = await approve_prompt(int(prompt["id"]))
            if not approved:
                raise RuntimeError("Trend approval failed")
        logger.info(
            "Seedance upload trend published: trend_id=%s model=%s admin=%s fixed_assets=%s user_slots=%s",
            approved["id"],
            model,
            telegram_id,
            len(recipe.assets),
            len(recipe.user_slots),
        )
        return web.json_response(
            {"ok": True, "prompt": sanitize_prompt_for_public(approved)}
        )
    except (TypeError, ValueError, TrendReferenceStorageError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except web.HTTPException as error:
        return web.json_response(
            {"ok": False, "error": str(error.text or "Нет доступа")},
            status=int(error.status),
        )
    except Exception:
        logger.exception("Seedance upload trend publish failed")
        return web.json_response(
            {"ok": False, "error": "Не удалось опубликовать Seedance-тренд"}, status=500
        )


def setup_seedance_trend_admin_routes(app: web.Application, miniapp_root: str) -> None:
    root = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app[_UPLOAD_PUBLISH_LOCK] = asyncio.Lock()
    app.router.add_post(
        f"{root}/api/admin/trends/seedance/publish-upload",
        miniapp_admin_publish_seedance_upload_trend,
    )
    app.router.add_post(
        f"{root}/api/admin/trends/seedance/source",
        miniapp_admin_seedance_trend_source,
    )
    app.router.add_post(
        f"{root}/api/admin/trends/seedance/publish",
        miniapp_admin_publish_seedance_trend,
    )
