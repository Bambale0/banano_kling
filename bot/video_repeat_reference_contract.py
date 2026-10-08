"""Versioned, server-only image/video consent for ordinary video repeats.

This module never reads media or performs I/O. Public descriptors contain only
slot positions, structural roles and bindings; source URLs stay in the plan.
"""
from __future__ import annotations

import json
from math import isfinite
from typing import Any

from bot.services.media_input_utils import (
    canonicalize_local_upload_url,
    resolve_reference_source,
)
from bot.video_reference_policy import apply_video_reference_cost

IMAGE_LIST_KEYS = ("reference_images", "reference_image_urls")
VIDEO_LIST_KEYS = ("v_reference_videos", "reference_videos", "reference_video_urls", "video_references")
AUDIO_LIST_KEYS = ("seedance25_reference_audio_urls", "reference_audios", "reference_audio_urls", "audio_references")
FIRST_KEYS = ("seedance25_first_frame_url", "first_frame_url", "v_image_url", "start_image", "image_url")
START_KEYS = ("v_image_url", "seedance25_first_frame_url", "first_frame_url", "start_image", "image_url")
LAST_KEYS = ("seedance25_last_frame_url", "last_frame_url", "end_image_url")
AUDIO_KEYS = ("audio_url", "audio_reference", "avatar_audio_url")
PROVIDER_ASSET_KEYS = ("omni_audio_ids", "omni_character_ids", "omni_character_audio_ids")
MEDIA_KEYS = set(IMAGE_LIST_KEYS + VIDEO_LIST_KEYS + AUDIO_LIST_KEYS + FIRST_KEYS + LAST_KEYS + AUDIO_KEYS + PROVIDER_ASSET_KEYS)


class VideoRepeatContractError(ValueError):
    """A safe, user-facing repeat-consent or recipe validation error."""


def parse_video_repeat_grant(raw: Any) -> dict[str, Any] | None:
    """Only known historical empty image-only records retain legacy semantics."""
    if raw is None:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError) as exc:
        raise VideoRepeatContractError("Разрешение на повтор повреждено. Попросите автора обновить публикацию.") from exc
    if isinstance(data, dict) and set(data) <= {"images"} and data.get("images", []) == []:
        return None
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise VideoRepeatContractError("Разрешение на повтор устарело. Попросите автора обновить публикацию.")
    result: dict[str, Any] = {"version": 1}
    for kind in ("images", "videos"):
        values = data.get(kind)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise VideoRepeatContractError("Разрешение на повтор повреждено. Попросите автора обновить публикацию.")
        result[kind] = list(dict.fromkeys(value.strip() for value in values))
    return result


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _list(data: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        values = data.get(key)
        if isinstance(values, list):
            clean = list(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))
            if clean:
                return clean
    return []


def source_request(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("request_data")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def active_video_recipe(task: dict[str, Any]) -> dict[str, Any]:
    data = source_request(task)
    model = str(task.get("model") or data.get("v_model") or "")
    declared_scenario = data.get("seedance25_scenario") or data.get("scenario")
    scenario = str(declared_scenario or data.get("v_type") or "").lower()
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    audio: list[str] = []
    if model == "seedance_2_5":
        if not scenario:
            scenario = "multimodal" if _list(data, IMAGE_LIST_KEYS) or _list(data, VIDEO_LIST_KEYS) else "first_frame" if _first(data, FIRST_KEYS) else "text"
        if scenario in {"imgtxt", "video"}:
            scenario = "first_frame" if scenario == "imgtxt" else "multimodal"
        if scenario in {"first_frame", "first_last"}:
            first = _first(data, FIRST_KEYS)
            # Generic I2V promotes a sole selected photo to the start frame.
            legacy_images = _list(data, IMAGE_LIST_KEYS)
            if not first and not declared_scenario and data.get("v_type") == "imgtxt" and len(legacy_images) == 1:
                first = legacy_images[0]
            last = _first(data, LAST_KEYS)
            if not first or (scenario == "first_last" and not last):
                raise VideoRepeatContractError("Исходные кадры для повтора сохранены не полностью.")
            images.append({"role": "first_frame", "url": first})
            if scenario == "first_last":
                images.append({"role": "last_frame", "url": last})
        elif scenario == "multimodal":
            images = [{"role": "reference", "url": value} for value in _list(data, IMAGE_LIST_KEYS)]
            videos = [{"role": "reference", "url": value} for value in _list(data, VIDEO_LIST_KEYS)]
            audio = _list(data, AUDIO_LIST_KEYS)
        elif scenario != "text":
            raise VideoRepeatContractError("Сценарий исходного видео не поддерживает безопасный повтор.")
    else:
        # Dedicated Seedance scenario fields do not select generic provider
        # modes. Match the generic handler's own v_type/generation_type data.
        scenario = str(data.get("v_type") or data.get("generation_type") or "").lower()
        first = _first(data, START_KEYS)
        if first:
            images.append({"role": "first_frame", "url": first})
        images.extend({"role": "reference", "url": value} for value in _list(data, IMAGE_LIST_KEYS) if value != first)
        videos = [{"role": "reference", "url": value} for value in _list(data, VIDEO_LIST_KEYS)]
        audio_value = _first(data, AUDIO_KEYS)
        audio = [audio_value] if audio_value else _list(data, AUDIO_LIST_KEYS)[:1]
        if not scenario:
            scenario = "video" if videos else "imgtxt" if first else "text"
    for kind, slots in (("images", images), ("videos", videos)):
        for index, slot in enumerate(slots):
            slot["index"] = index
            slot["kind"] = kind
    public_scenario = scenario
    if model == "seedance_2_5":
        public_scenario = (
            "imgtxt" if scenario in {"first_frame", "first_last"}
            else "video" if videos else "imgtxt" if images else "text"
        )
    return {"model": model, "scenario": scenario, "public_scenario": public_scenario,
            "images": images, "videos": videos, "audio": audio}



def _validate_provider_list_slots(values: list[str]) -> None:
    canonical = [canonicalize_local_upload_url(value) for value in values]
    if len(set(canonical)) != len(canonical):
        raise VideoRepeatContractError(
            "Одинаковые файлы занимают разные места в списке референсов. "
            "Обновите публикацию или загрузите разные файлы."
        )


def build_video_repeat_plan(
    task: dict[str, Any], *, replaced_kinds: set[str] | None = None,
    allow_audio_replacement: bool = False,
) -> dict[str, Any] | None:
    grant = parse_video_repeat_grant(task.get("feed_repeat_reference_selection"))
    if grant is None:
        return None
    if task.get("source_feed_gen_id") or str(task.get("action_type") or "").lower() in {"remix", "repeat"}:
        raise VideoRepeatContractError("Повтор по чужим исходным материалам нельзя передать как новый рецепт.")
    data = source_request(task)
    if any(data.get(key) for key in PROVIDER_ASSET_KEYS):
        raise VideoRepeatContractError("Этот рецепт использует сохранённые аудио или персонажей провайдера, не входящие в разрешение на фото и видео.")
    model = str(task.get("model") or data.get("v_model") or "")
    if model == "seedance_2_5":
        identity = data.get("seedance25_identity_transfer", data.get("identityTransfer", False))
        editing = data.get("seedance25_video_editing", False)
        if not isinstance(identity, bool) or not isinstance(editing, bool):
            raise VideoRepeatContractError("Режим исходной Seedance 2.5 задачи повреждён.")
        if "identityTransfer" in data and data["identityTransfer"] is not identity:
            raise VideoRepeatContractError("Режим исходной Seedance 2.5 задачи противоречив.")
        if identity or editing:
            raise VideoRepeatContractError("Для переноса персонажа и редактирования видео нужен специальный сценарий; приватный повтор через эту форму недоступен.")
    if str(data.get("v_type") or data.get("generation_type") or "").lower() in {"motion_control", "motion"}:
        raise VideoRepeatContractError("Для Motion Control нужен специальный сценарий; приватный повтор через эту форму недоступен.")
    recipe = active_video_recipe(task)
    if model.startswith("veo3"):
        mode = str(data.get("veo_generation_type") or (
            "FIRST_AND_LAST_FRAMES_2_VIDEO" if recipe["scenario"] == "imgtxt" else "TEXT_2_VIDEO"
        ))
        # Match the existing generic Veo adapter: only I2V forwards images,
        # capped at two; text mode cannot promise retained image inputs.
        if (mode not in {"TEXT_2_VIDEO", "FIRST_AND_LAST_FRAMES_2_VIDEO", "REFERENCE_2_VIDEO"}
                or recipe["videos"] or len(recipe["images"]) > 2
                or (recipe["images"] and (recipe["scenario"] != "imgtxt" or mode == "TEXT_2_VIDEO"))):
            raise VideoRepeatContractError("Режим Veo исходной задачи не поддерживает сохранённые референсы через эту форму.")
        recipe["veo_generation_type"] = mode
    if recipe["audio"] and not allow_audio_replacement:
        raise VideoRepeatContractError("Приватные аудиореференсы пока не поддерживаются. Загрузите своё аудио для повтора.")
    replaced = replaced_kinds or set()
    for kind in ("images", "videos"):
        candidates = [slot["url"] for slot in recipe[kind]]
        fixed: set[str] = set()
        for value in ([] if kind in replaced else grant[kind]):
            try:
                resolved = resolve_reference_source(value, candidates)
            except ValueError as exc:
                raise VideoRepeatContractError("Неоднозначный референс. Попросите автора обновить публикацию.") from exc
            if resolved is None:
                raise VideoRepeatContractError("Исходные референсы для повтора сохранены не полностью.")
            fixed.add(resolved)
        for slot in recipe[kind]:
            slot["binding"] = "fixed" if slot["url"] in fixed else "upload"
        _validate_provider_list_slots([
            slot["url"] for slot in recipe[kind]
            if slot["binding"] == "fixed" and slot["role"] == "reference"
        ])
    return {"version": 1, "grant": grant, **recipe}


def video_repeat_descriptors(task: dict[str, Any]) -> dict[str, Any] | None:
    try:
        plan = build_video_repeat_plan(task)
        if plan is None:
            return None
        cost_multiplier = float(apply_video_reference_cost(plan["model"], 1, [slot["url"] for slot in plan["videos"]]))
        if not isfinite(cost_multiplier) or cost_multiplier <= 0:
            raise VideoRepeatContractError("Не удалось определить стоимость повтора.")
    except VideoRepeatContractError:
        return {"version": 1, "available": False, "images": [], "videos": []}
    return {
        "version": 1, "available": True, "cost_multiplier": cost_multiplier,
        **{kind: [{key: slot[key] for key in ("index", "role", "binding")} for slot in plan[kind]]
           for kind in ("images", "videos")},
    }


def merge_typed_video_inputs(
    task: dict[str, Any], body: dict[str, Any], normalized: dict[str, Any],
) -> dict[str, Any]:
    if any(body.get(key) for key in PROVIDER_ASSET_KEYS):
        raise VideoRepeatContractError("Сохранённые аудио и персонажи провайдера не входят в этот договор повтора.")
    identity = body.get("seedance25_identity_transfer") is True and normalized.get("v_model") == "seedance_2_5"
    replaced = {kind for kind, field in (("images", "reference_images"), ("videos", "v_reference_videos"))
                if identity and field in body}
    explicit_audio = _first(body, AUDIO_KEYS) or _list(body, AUDIO_LIST_KEYS)
    plan = build_video_repeat_plan(task, replaced_kinds=replaced,
                                  allow_audio_replacement=bool(explicit_audio or (identity and len(replaced) == 2)))
    if plan is None:
        return normalized
    result = dict(normalized)
    for key in MEDIA_KEYS:
        result.pop(key, None)
    result.update(reference_images=[], v_reference_videos=[], v_image_url=None,
                  seedance25_first_frame_url=None, seedance25_last_frame_url=None,
                  seedance25_reference_audio_urls=[], audio_references=[], audio_url=None)
    # The public Omni video selector and its stored provider model are aliases.
    public_aliases = {"gemini_omni_video": "gemini_omni"}
    if public_aliases.get(result.get("v_model"), result.get("v_model")) != public_aliases.get(plan["model"], plan["model"]):
        raise VideoRepeatContractError("Для этого повтора используйте модель исходной публикации.")
    if result.get("v_model") == "seedance_2_5" and not identity:
        requested = body.get("seedance25_scenario")
        if requested and requested != plan["scenario"]:
            raise VideoRepeatContractError("Для этого повтора используйте сценарий исходной публикации.")
        result["seedance25_scenario"] = plan["scenario"]
        result["v_type"] = "text" if plan["scenario"] == "text" else "imgtxt" if plan["scenario"] in {"first_frame", "first_last"} else "video"
    elif not identity:
        if body.get("v_type") and body["v_type"] != plan["scenario"]:
            raise VideoRepeatContractError("Для этого повтора используйте сценарий исходной публикации.")
        result["v_type"] = plan["scenario"]
    if plan["model"].startswith("veo3"):
        # Public forms send their default advanced mode even for hidden recipes.
        # It cannot override the author's provider input contract.
        result["veo_generation_type"] = plan["veo_generation_type"]
    for kind, field in (("images", "reference_images"), ("videos", "v_reference_videos")):
        values = body.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise VideoRepeatContractError("Добавьте файл для каждого заменяемого референса.")
        uploads = [value.strip() for value in values]
        if len(set(uploads)) != len(uploads):
            raise VideoRepeatContractError("Для каждого заменяемого места нужен отдельный загруженный файл.")
        if kind in replaced:
            result[field] = uploads
            result.pop(f"_private_repeat_reference_{kind}", None)
            continue
        slots = plan[kind]
        if len(uploads) != sum(slot["binding"] == "upload" for slot in slots):
            raise VideoRepeatContractError("Добавьте по одному файлу для каждого заменяемого места в публикации.")
        candidates = [slot["url"] for slot in slots]
        for value in uploads:
            try:
                inherited = resolve_reference_source(value, candidates)
            except ValueError as exc:
                raise VideoRepeatContractError("Загрузите свои файлы для заменяемых референсов.") from exc
            if inherited is not None:
                raise VideoRepeatContractError("Загрузите свои файлы для заменяемых референсов.")
        iterator = iter(uploads)
        private: list[str] = []
        for slot in slots:
            value = slot["url"] if slot["binding"] == "fixed" else next(iterator)
            if slot["binding"] == "fixed":
                private.append(value)
            if kind == "videos" or slot["role"] == "reference":
                result[field].append(value)
            elif slot["role"] == "first_frame":
                if plan["model"] == "seedance_2_5":
                    result["seedance25_first_frame_url"] = value
                else:
                    result["v_image_url"] = value
            elif slot["role"] == "last_frame":
                result["seedance25_last_frame_url"] = value
        if private:
            result[f"_private_repeat_reference_{kind}"] = private
        else:
            result.pop(f"_private_repeat_reference_{kind}", None)
    _validate_provider_list_slots(result["reference_images"])
    _validate_provider_list_slots(result["v_reference_videos"])
    result.pop("_private_repeat_reference_audios", None)
    # Source audio is never part of the new typed grant.
    audio_list = _list(body, AUDIO_LIST_KEYS)
    audio_scalar = _first(body, AUDIO_KEYS)
    result["seedance25_reference_audio_urls"] = audio_list
    result["audio_references"] = audio_list
    result["audio_url"] = audio_scalar or (audio_list[0] if audio_list else None)
    return result
