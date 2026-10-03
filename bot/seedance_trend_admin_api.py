"""Admin API for publishing private-reference Seedance trends from completed tasks."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.config import config
from bot.database import (
    approve_prompt,
    create_prompt,
    get_active_seedance_trend_by_source_generation,
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
from bot.services.trend_reference_storage import (
    TrendReferenceStorageError,
    persist_trend_reference,
)
from bot.trend_visibility import sanitize_prompt_for_public
from bot.utils.validators import detect_explicit_prompt_policy_violation

logger = logging.getLogger(__name__)

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
        if not snapshot.images or (
            len(snapshot.images) + len(snapshot.videos) + len(snapshot.audios) < 2
        ):
            raise ValueError(
                "В исходной задаче должно быть лицо автора и хотя бы один закрепляемый референс"
            )
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


def setup_seedance_trend_admin_routes(app: web.Application, miniapp_root: str) -> None:
    root = str(miniapp_root or "/mini-app").rstrip("/") or "/mini-app"
    app.router.add_post(
        f"{root}/api/admin/trends/seedance/source",
        miniapp_admin_seedance_trend_source,
    )
    app.router.add_post(
        f"{root}/api/admin/trends/seedance/publish",
        miniapp_admin_publish_seedance_trend,
    )
