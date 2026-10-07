"""Keep Mini App video repeat and share flows on the server-side source contract.

Feed/profile cards intentionally hide prompts/references from clients. A repeat therefore
must restore the original generation payload on the server instead of trusting an empty
browser preset. This layer also makes copied video links open the Mini App remix flow
rather than the text-bot post link.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from functools import wraps
from typing import Any

from aiohttp import web

from bot.database import get_generation_task_payload
from bot.services.media_input_utils import (
    missing_local_upload_sources,
    reference_source_identity,
)

logger = logging.getLogger(__name__)

_REPEAT_LIST_ALIASES: dict[str, tuple[str, ...]] = {
    "reference_images": ("reference_images", "reference_image_urls"),
    "v_reference_videos": (
        "v_reference_videos",
        "reference_videos",
        "reference_video_urls",
    ),
    "seedance25_reference_audio_urls": (
        "seedance25_reference_audio_urls",
        "reference_audios",
        "reference_audio_urls",
        "audio_references",
    ),
}

_REPEAT_SCALAR_ALIASES: dict[str, tuple[str, ...]] = {
    "v_image_url": (
        "v_image_url",
        "seedance25_first_frame_url",
        "first_frame_url",
        "start_image",
        "image_url",
    ),
    "seedance25_first_frame_url": (
        "seedance25_first_frame_url",
        "first_frame_url",
        "v_image_url",
        "start_image",
        "image_url",
    ),
    "seedance25_last_frame_url": (
        "seedance25_last_frame_url",
        "last_frame_url",
        "end_image_url",
    ),
    "audio_url": ("audio_url", "audio_reference"),
    "seedance25_scenario": ("seedance25_scenario", "scenario"),
    "seedance25_video_editing": ("seedance25_video_editing",),
    "seedance25_identity_transfer": ("seedance25_identity_transfer",),
    "seedance25_resolution": ("seedance25_resolution", "resolution"),
    "seedance25_output_format": ("seedance25_output_format", "output_format"),
    "seedance25_generate_audio": ("seedance25_generate_audio", "generate_audio"),
    "seedance25_return_last_frame": (
        "seedance25_return_last_frame",
        "return_last_frame",
    ),
    "seedance25_web_search": ("seedance25_web_search", "web_search"),
    "seedance25_nsfw_checker": ("seedance25_nsfw_checker", "nsfw_checker"),
}

_ADVANCED_VIDEO_KEYS = (
    "grok_mode",
    "grok_resolution",
    "veo_generation_type",
    "veo_translation",
    "veo_resolution",
    "veo_seed",
    "veo_watermark",
    "kling_negative_prompt",
    "kling_cfg_scale",
    "omni_resolution",
    "omni_seed",
    "omni_audio_ids",
    "omni_character_ids",
    "omni_base_voice",
    "omni_voice_name",
    "omni_voice_description",
    "omni_example_dialogue",
    "omni_character_name",
    "omni_character_audio_ids",
)


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _first_value(source: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, set)) and not value:
            continue
        return value
    return None


def _first_list(source: dict[str, Any], keys: Iterable[str]) -> list[str]:
    for key in keys:
        values = _clean_list(source.get(key))
        if values:
            return values
    return []


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _publication_repeat_selection(source_task: dict[str, Any]) -> dict[str, list[str]] | None:
    """Return the author's explicit visible ref selection for server-side reuse.

    Presence of ``feed_reference_selection`` switches modern publications to
    fail-closed semantics: only refs the author explicitly opened in the
    publication may be retained in another user's repeat. Older publications
    without that field keep the legacy exact-repeat behavior.
    """
    raw = source_task.get("feed_reference_selection")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"images": [], "videos": []}
    if not isinstance(raw, dict) or not source_task.get("feed_references_visible"):
        return {"images": [], "videos": []}

    result: dict[str, list[str]] = {}
    for kind in ("images", "videos"):
        values = raw.get(kind)
        result[kind] = _clean_list(values) if isinstance(values, (list, tuple, set)) else []
    return result


class VideoRepeatReferenceError(ValueError):
    """An incomplete source recipe must never reach billing or generation."""


def _merge_selected_reference_slots(
    source_values: list[str],
    selected_values: list[str],
    explicit_values: list[str],
) -> tuple[list[str], list[str]]:
    """Keep selected source refs on their original numbered slots.

    Unselected slots before the last retained source ref must be replaced by
    viewer-supplied media. Insufficient replacements are an error: silently
    dropping retained media would run a different recipe and charge the user.
    Never shift ImageN/VideoN bindings or reuse an unselected source reference.
    """
    selected_set = {reference_source_identity(value) for value in selected_values}
    retained = [value for value in source_values if reference_source_identity(value) in selected_set]
    if not retained:
        return _clean_list(explicit_values), []

    retained_set = {reference_source_identity(value) for value in retained}
    replacements = [
        value for value in _clean_list(explicit_values)
        if reference_source_identity(value) not in retained_set
    ]
    last_retained = max(
        index for index, value in enumerate(source_values)
        if reference_source_identity(value) in retained_set
    )
    replacement_iter = iter(replacements)
    merged: list[str] = []
    for value in source_values[: last_retained + 1]:
        if reference_source_identity(value) in retained_set:
            merged.append(value)
            continue
        replacement = next(replacement_iter, None)
        if replacement is None:
            raise VideoRepeatReferenceError(
                "Для этого повтора не хватает ваших фото или видео для замены "
                "исходных референсов. Добавьте недостающие файлы и попробуйте снова."
            )
        merged.append(replacement)
    merged.extend(replacement_iter)
    return _clean_list(merged), retained


def _source_id(body: dict[str, Any]) -> int | None:
    raw = body.get("source_feed_gen_id") or body.get("sourceFeedGenId")
    return int(raw) if str(raw or "").isdigit() else None


def _source_request_data(task: dict[str, Any]) -> dict[str, Any]:
    request_data = task.get("request_data") or {}
    return request_data if isinstance(request_data, dict) else {}


def _infer_scenario(request_data: dict[str, Any]) -> str:
    scenario = str(
        request_data.get("seedance25_scenario")
        or request_data.get("scenario")
        or request_data.get("v_type")
        or ""
    ).strip().lower()
    if scenario:
        return scenario
    if _first_list(request_data, _REPEAT_LIST_ALIASES["v_reference_videos"]):
        return "video"
    if _first_value(request_data, _REPEAT_SCALAR_ALIASES["v_image_url"]):
        return "imgtxt"
    return "text"


def enrich_video_repeat_body(
    body: dict[str, Any],
    source_task: dict[str, Any],
) -> dict[str, Any]:
    """Merge private source payload into a repeat request without exposing it to UI."""

    normalized = dict(body)
    request_data = _source_request_data(source_task)
    explicit_identity = body.get("seedance25_identity_transfer") is True

    # Keep the browser's explicit media separate from server-restored private
    # references. For Seedance 2.5 repeats, user-selected media must be able to
    # override/extend the original recipe instead of being silently discarded.
    explicit_reference_images = _clean_list(body.get("reference_images"))
    explicit_reference_videos = _clean_list(body.get("v_reference_videos"))
    explicit_audio_references = _clean_list(
        body.get("seedance25_reference_audio_urls")
        or body.get("audio_references")
    )
    explicit_v_image_url = str(body.get("v_image_url") or "").strip()
    if explicit_v_image_url and explicit_v_image_url not in explicit_reference_images:
        explicit_reference_images.insert(0, explicit_v_image_url)

    if not str(normalized.get("prompt") or "").strip():
        normalized["prompt"] = str(source_task.get("prompt") or "")
    if not str(normalized.get("v_model") or "").strip():
        normalized["v_model"] = str(
            source_task.get("model") or request_data.get("v_model") or ""
        )
    if not str(normalized.get("v_type") or "").strip():
        normalized["v_type"] = str(request_data.get("v_type") or _infer_scenario(request_data))
    if _missing(normalized.get("v_duration")):
        normalized["v_duration"] = source_task.get("duration") or request_data.get("v_duration") or 5
    if not str(normalized.get("v_ratio") or "").strip():
        normalized["v_ratio"] = str(
            source_task.get("aspect_ratio") or request_data.get("v_ratio") or "16:9"
        )

    # The Mini App exposes one photo-reference picker instead of a separate start-image field.
    # When a user selected photos for image-to-video, the first one is authoritative and must
    # win over the private source image restored from the feed item.
    if str(normalized.get("v_type") or "").strip().lower() == "imgtxt" and _missing(
        normalized.get("v_image_url")
    ):
        requested_images = _clean_list(normalized.get("reference_images"))
        if requested_images:
            normalized["v_image_url"] = requested_images[0]
            normalized["reference_images"] = requested_images[1:]

    publication_selection = _publication_repeat_selection(source_task)
    private_reference_images: list[str] = []
    private_reference_videos: list[str] = []
    private_reference_audios: list[str] = []

    for target, aliases in _REPEAT_LIST_ALIASES.items():
        # A dedicated identity form owns its complete selection. An explicit
        # empty list means removal, never permission to resurrect private media.
        if explicit_identity and target in body:
            normalized[target] = _clean_list(body[target])
            continue
        restored = _first_list(request_data, aliases)
        if publication_selection is not None and target in {"reference_images", "v_reference_videos"}:
            if target == "reference_images":
                merged, retained = _merge_selected_reference_slots(
                    restored,
                    publication_selection["images"],
                    explicit_reference_images,
                )
                private_reference_images = retained
            else:
                merged, retained = _merge_selected_reference_slots(
                    restored,
                    publication_selection["videos"],
                    explicit_reference_videos,
                )
                private_reference_videos = retained
            if merged:
                normalized[target] = merged
            else:
                normalized.pop(target, None)
            continue

        if not _clean_list(normalized.get(target)) and restored:
            normalized[target] = restored
            if target == "reference_images":
                private_reference_images = restored
            elif target == "v_reference_videos":
                private_reference_videos = restored
            elif target == "seedance25_reference_audio_urls":
                private_reference_audios = restored

    for target, aliases in _REPEAT_SCALAR_ALIASES.items():
        if explicit_identity and target in body:
            continue
        if _missing(normalized.get(target)):
            restored = _first_value(request_data, aliases)
            if restored is not None:
                normalized[target] = restored
                restored_text = str(restored or "").strip()
                if restored_text and target in {
                    "v_image_url",
                    "seedance25_first_frame_url",
                    "seedance25_last_frame_url",
                } and restored_text not in private_reference_images:
                    private_reference_images.append(restored_text)
                if restored_text and target == "audio_url" and restored_text not in private_reference_audios:
                    private_reference_audios.append(restored_text)

    if private_reference_images:
        normalized["_private_repeat_reference_images"] = private_reference_images
    else:
        normalized.pop("_private_repeat_reference_images", None)
    if private_reference_videos:
        normalized["_private_repeat_reference_videos"] = private_reference_videos
    else:
        normalized.pop("_private_repeat_reference_videos", None)
    if private_reference_audios:
        normalized["_private_repeat_reference_audios"] = private_reference_audios
    else:
        normalized.pop("_private_repeat_reference_audios", None)

    if _missing(normalized.get("audio_url")):
        audio_urls = _clean_list(normalized.get("seedance25_reference_audio_urls"))
        if not audio_urls:
            audio_urls = _first_list(
                request_data,
                _REPEAT_LIST_ALIASES["seedance25_reference_audio_urls"],
            )
        if audio_urls:
            normalized["audio_url"] = audio_urls[0]
            normalized.setdefault("audio_references", audio_urls)

    for key in _ADVANCED_VIDEO_KEYS:
        if _missing(normalized.get(key)) and key in request_data:
            normalized[key] = request_data.get(key)

    # Dedicated Seedance 2.5 uses a richer scenario vocabulary than the generic
    #  video form. Preserve the source scenario, while letting media explicitly
    #  selected in the repeat form override the matching source inputs.
    if str(normalized.get("v_model") or "").strip() == "seedance_2_5":
        # Keep strict booleans: malformed values pass through to launch validation,
        # while an explicit False deliberately opts out of the source edit recipe.
        if normalized.get("seedance25_video_editing") is True or normalized.get("seedance25_identity_transfer") is True:
            normalized["v_duration"] = -1
            normalized["v_ratio"] = "adaptive"
        if explicit_identity:
            # Prompt and omitted settings may be inherited, but the user's
            # explicit scenario/media must survive unchanged for validation.
            return normalized
        restored_scenario = str(
            _first_value(
                request_data,
                ("seedance25_scenario", "scenario"),
            )
            or ""
        ).strip().lower()
        if restored_scenario:
            normalized["seedance25_scenario"] = restored_scenario

        if restored_scenario == "first_frame" and explicit_reference_images:
            normalized["seedance25_first_frame_url"] = explicit_reference_images[0]
        elif restored_scenario == "first_last" and explicit_reference_images:
            normalized["seedance25_first_frame_url"] = explicit_reference_images[0]
            if len(explicit_reference_images) > 1:
                normalized["seedance25_last_frame_url"] = explicit_reference_images[1]
        elif (
            explicit_reference_images
            or explicit_reference_videos
            or explicit_audio_references
        ):
            normalized["seedance25_scenario"] = "multimodal"
            # ``reference_images`` / ``v_reference_videos`` may already contain
            # the server-side slot-preserving merge above. Do not overwrite that
            # with only the browser-visible refs.
            if explicit_reference_images and publication_selection is None:
                normalized["reference_images"] = explicit_reference_images
            if explicit_reference_videos and publication_selection is None:
                normalized["v_reference_videos"] = explicit_reference_videos
            if explicit_audio_references:
                normalized["seedance25_reference_audio_urls"] = explicit_audio_references

    return normalized


def _active_video_reference_urls(body: dict[str, Any]) -> list[str]:
    """Validate media used by the selected scenario, not superseded frame aliases."""
    scenario = str(body.get("seedance25_scenario") or "").strip().lower()
    if str(body.get("v_model") or "").strip() == "seedance_2_5":
        if scenario == "text":
            return []
        if scenario in {"first_frame", "first_last"}:
            frames = [body.get("seedance25_first_frame_url")]
            if scenario == "first_last":
                frames.append(body.get("seedance25_last_frame_url"))
            return _clean_list(frames)
        if scenario == "multimodal":
            return _clean_list([
                *_clean_list(body.get("reference_images")),
                *_clean_list(body.get("v_reference_videos")),
                *_clean_list(body.get("seedance25_reference_audio_urls")),
            ])

    return _clean_list([
        *[value for target in _REPEAT_LIST_ALIASES for value in _clean_list(body.get(target))],
        *_clean_list(body.get("audio_references")),
        body.get("v_image_url"),
        body.get("seedance25_first_frame_url"),
        body.get("seedance25_last_frame_url"),
        body.get("audio_url"),
    ])


async def _restore_repeat_request(request: web.Request, body: dict[str, Any]) -> dict[str, Any]:
    source_id = _source_id(body)
    if not source_id:
        return body

    import bot.miniapp as miniapp_module

    _telegram_id, context = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    card = await miniapp_module._get_repeat_source_card(
        source_id,
        viewer_user_id=context["user"].id,
    )
    if not card or str(card.get("gen_type") or "").lower() != "video":
        raise web.HTTPNotFound(reason="Видео для повтора не найдено")
    source_task = await get_generation_task_payload(source_id)
    if not source_task:
        raise web.HTTPNotFound(reason="Видео для повтора не найдено")
    enriched = enrich_video_repeat_body(body, source_task)
    if missing_local_upload_sources(_active_video_reference_urls(enriched)):
        raise VideoRepeatReferenceError(
            "Один или несколько референсов для повтора больше недоступны. "
            "Загрузите недостающие файлы или откройте другую публикацию."
        )
    return enriched


def _replace_cached_json(request: web.Request, body: dict[str, Any]) -> None:
    # aiohttp Request.json() re-reads the cached byte body. Replacing this cache
    # lets established handlers validate the enriched request without duplicating
    # their billing/provider logic.
    request._read_bytes = json.dumps(  # type: ignore[attr-defined]
        body,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _video_remix_link(payload: dict[str, Any]) -> str:
    candidates = (
        payload.get("miniapp_repeat_link"),
        payload.get("miniapp_post_link"),
        payload.get("miniapp_link"),
    )
    for raw in candidates:
        link = str(raw or "").strip()
        if not link:
            continue
        if "startapp=remix_" in link:
            return link
        if "startapp=feed_" in link:
            return link.replace("startapp=feed_", "startapp=remix_", 1)
    return ""


def _response_payload(response: web.StreamResponse) -> dict[str, Any] | None:
    if not isinstance(response, web.Response) or not response.body:
        return None
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_response_like(response: web.Response, payload: dict[str, Any]) -> web.Response:
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return web.json_response(payload, status=response.status, headers=headers)


def install_miniapp_video_continuity_compat() -> None:
    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_video_continuity_compat_installed", False):
        return

    current_generate_video = miniapp_module.miniapp_generate_video
    current_feed_share = miniapp_module.miniapp_feed_share

    @wraps(current_generate_video)
    async def generate_video_with_repeat_context(request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except Exception:
            return await current_generate_video(request)
        if not isinstance(body, dict):
            return await current_generate_video(request)
        try:
            enriched = await _restore_repeat_request(request, body)
        except VideoRepeatReferenceError as exc:
            return web.json_response(
                {"ok": False, "code": "repeat_reference_incomplete", "error": str(exc)},
                status=400,
            )
        except Exception as exc:
            # A retry in the original handler might succeed but lose the
            # private recipe. Never launch after partial restoration failure.
            expected = miniapp_module._miniapp_expected_error_response(exc)
            status = expected.status if expected is not None else 503
            message = {
                401: "Откройте Mini App заново из Telegram.",
                403: "Нет доступа к этому повтору.",
                404: "Видео для повтора не найдено.",
            }.get(status, "Не удалось восстановить данные повтора. Попробуйте ещё раз.")
            logger.warning(
                "Video repeat restoration rejected: source_generation_id=%s error_type=%s status=%s",
                _source_id(body), type(exc).__name__, status,
            )
            return web.json_response(
                {"ok": False, "code": "repeat_source_unavailable", "error": message},
                status=status,
            )
        if enriched != body:
            _replace_cached_json(request, enriched)
        return await current_generate_video(request)

    @wraps(current_feed_share)
    async def feed_share_with_miniapp_video_link(request: web.Request) -> web.StreamResponse:
        response = await current_feed_share(request)
        payload = _response_payload(response)
        if not payload or response.status >= 400:
            return response
        feed_item = payload.get("feed_item")
        if not isinstance(feed_item, dict) or str(feed_item.get("gen_type") or "").lower() != "video":
            return response

        remix_link = _video_remix_link(payload)
        if not remix_link:
            return response

        # Existing web bundle intentionally chooses post_link for videos. Point
        # that compatibility field at the Mini App remix route as well so stale
        # clients immediately receive a usable repeat link.
        payload["link"] = remix_link
        payload["post_link"] = remix_link
        payload["repeat_link"] = remix_link
        payload["miniapp_repeat_link"] = remix_link
        return _json_response_like(response, payload)

    miniapp_module.miniapp_generate_video = generate_video_with_repeat_context
    miniapp_module.miniapp_feed_share = feed_share_with_miniapp_video_link
    miniapp_module._video_continuity_compat_installed = True
