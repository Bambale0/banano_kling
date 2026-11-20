"""Independent paid browser generation using the existing KIE provider adapters.

The web lifecycle never invokes legacy Telegram debit, sendMessage, or owner ID.
Task insertion and wallet reservation are ONE DB transaction. Acknowledged
provider IDs are polled, results archived to S3, then captured; errors release
the reservation. Uncertain provider creation is NEVER blindly retried.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from aiohttp import web

from bot import db as db_backend
from bot.config import config
from bot.services.gpt_image_service import gpt_image_service
from bot.services.kie_market_service import kie_market_service
from bot.services.kling_service import KlingService
from bot.services.preset_manager import preset_manager
from bot.shared_accounts.wallet import (
    InsufficientFunds,
    WalletConflict,
    WalletService,
    amount_units,
    format_units,
)
from bot.web_tasks import ensure_web_tasks_schema

logger = logging.getLogger(__name__)
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_TASK_ID = re.compile(r"^web_[a-f0-9]{32}$")
# The Mini App's IMAGE_MODELS/VIDEO_MODELS tuples are the canonical public
# catalog. Only models with audited account-native provider adapters may be
# charged. An unavailable model must remain visible but explicitly disabled.
_IMAGE_MODELS = {
    "nano-banana-2-lite",
    "flux_pro",
    "banana_pro",
    "banana_2",
    "seedream_5_pro",
    "seedream_55",
    "seedream_55_layers",
    "seedream_edit",
    "wan_27",
    "grok_imagine_i2i",
}
_VIDEO_MODELS = {
    "v3_std", "v3_pro", "v26_pro",
    "grok_imagine", "grok_imagine_v15", "seedance_2", "veo3_fast",
    "motion_control_v26", "motion_control_v30",
    "avatar_std", "avatar_pro", "gemini_omni",
    "wan_3", "wan_3_prime",
}
_POLL_INTERVAL_SECONDS = 8
_SUBMIT_TIMEOUT_SECONDS = 240
_PENDING_DEADLINE_SECONDS = 2 * 3600
_POLL_LEASE_SECONDS = 180
_TASK_BATCH = 12


def _enabled() -> bool:
    return os.getenv("WEB_NATIVE_GENERATION_ENABLED", "0").strip().lower() in ("1", "true", "yes")


def _seconds(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def _model_meta(model: str) -> tuple[str, dict]:
    from bot import miniapp

    for item in miniapp.IMAGE_MODELS:
        if item["id"] == model:
            return "image", item
    for item in miniapp.VIDEO_MODELS:
        if item["id"] == model:
            return "video", item
    raise ValueError("Unknown model in the current Mini App catalog")


def _web_durations(model: str, meta: dict) -> list[int]:
    original = list(meta.get("durations") or [5])
    # Wan3 auto -1 reserves 30 seconds and settles after verified S3 output probe.
    if model == "veo3_fast":
        from bot.services.veo_service import VEO_SUPPORTED_DURATIONS

        # Veo's API normalizes unsupported values to a *different* duration.
        # Never charge for 2/10 seconds and silently generate 4/8 instead.
        original = [duration for duration in original if duration in VEO_SUPPORTED_DURATIONS]
    return original


def _web_max_image_refs(model: str, meta: dict) -> int:
    from bot.web_references import _max_references

    original = int(meta.get("max_references", meta.get("max_image_references", 0)))
    if model in ("motion_control_v26", "motion_control_v30",
                    "avatar_std", "avatar_pro", "grok_imagine_v15", "v26_pro"):
        original = min(1, original if original else 1)
    elif model == "seedream_edit":
        from bot.services.seedream_service import seedream_service

        original = min(original, seedream_service.MAX_REFERENCE_IMAGES)
    elif model == "veo3_fast":
        # FIRST_AND_LAST_FRAMES_2_VIDEO accepts at most two frames.
        original = min(original, 2)
    return min(_max_references(), original)


def _quality_value(model: str, meta: dict, quality: str | None) -> str:
    choices = list(meta.get("qualities") or []) + (
        ["auto"] if model == "seedream_55_layers" else []
    ) or meta.get("motion_modes") or (
        meta.get("omni_resolutions") if model == "gemini_omni" else
        meta.get("wan_resolutions") if model in ("wan_3", "wan_3_prime") else
        meta.get("grok_resolutions") if model == "grok_imagine_v15" else
        meta.get("veo_resolutions") if model == "veo3_fast"
        else []
    ) or []
    if not choices:
        if quality:
            raise ValueError("Quality option is not supported for this model")
        return ""
    selected = quality or (
        "2K" if "2K" in choices else
        "720p" if "720p" in choices else
        "720P" if "720P" in choices else choices[0]
    )
    if selected not in choices:
        raise ValueError("Unsupported quality for this model")
    return selected


def _price(media_type: str, model: str, duration: int,
           quality: str | None = None, reference_count: int = 0,
           max_images: int = 30) -> str:
    actual_type, meta = _model_meta(model)
    if media_type != actual_type:
        raise ValueError("Model/media type mismatch")
    if media_type == "image":
        if model not in _IMAGE_MODELS:
            raise ValueError("Model is not enabled for independent browser generation")
        from bot.miniapp import _resolve_image_unit_cost

        selected = _quality_value(model, meta, quality)
        if model == "seedream_55_layers":
            from bot.services.seedream55_pricing import image_generation_cost

            raw = image_generation_cost(
                model, selected, reference_count=reference_count,
                max_images=max_images,
            )
        else:
            raw = _resolve_image_unit_cost(
                model, selected, reference_count=reference_count,
            )
    else:
        if model not in _VIDEO_MODELS:
            raise ValueError("Model is not enabled for independent browser generation")
        if duration not in meta.get("durations", ()):
            raise ValueError("Unsupported duration")
        if model in ("grok_imagine_v15", "veo3_fast"):
            selected_quality = _quality_value(model, meta, quality)
            available_rates = {
                str(key).lower(): value
                for key, value in preset_manager.get_video_quality_costs(model).items()
            }
            rate = available_rates.get(selected_quality.lower())
            if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
                raise ValueError("Missing verified resolution rate for video model")
            raw = preset_manager.get_video_cost_with_quality(
                model, duration, selected_quality,
            )
        elif model in ("wan_3", "wan_3_prime"):
            if duration != -1 and not 2 <= duration <= 30:
                raise ValueError("Wan3 output duration must be 2-30 or auto")
            selected_quality = _quality_value(model, meta, quality)
            raw_rates = preset_manager.get_video_quality_costs(model)
            rates = {str(key).lower(): value for key, value in raw_rates.items()}
            rate = rates.get(selected_quality.lower())
            if (type(rate) not in (float, int) or not math.isfinite(rate)
                    or rate <= 0):
                raise ValueError("Wan 3.0 quality rate not configured")
            from bot.services.wan3_prime_lifecycle import _round_half_credit

            raw = _round_half_credit(float(rate) * (30 if duration == -1 else duration))
            if raw <= 0:
                raise ValueError("Wan 3.0 rate too small")
        elif model == "gemini_omni":
            selected_quality = _quality_value(model, meta, quality)
            rates = {
                str(k).lower(): v
                for k, v in preset_manager.get_video_quality_costs(model).items()
            }
            if selected_quality.lower() not in rates:
                raise ValueError("No verified Gemini Omni quality rate")
            raw = preset_manager.get_video_cost_with_quality(
                model, duration, selected_quality,
            )
        elif model in ("motion_control_v26", "motion_control_v30"):
            selected_quality = _quality_value(model, meta, quality)
            raw = preset_manager.get_video_cost_with_quality(
                model, duration, selected_quality,
            )
        else:
            raw = preset_manager.get_video_cost(model, duration)
    amount = Decimal(str(raw))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Invalid or missing live tariff")
    amount_units(amount)
    return str(amount)


def _price_for_request(normalized: dict) -> str:
    args = (
        normalized["media_type"], normalized["model"],
        normalized["duration"], normalized["quality"],
        len(normalized["reference_ids"]),
    )
    if normalized["model"] == "seedream_55_layers":
        return _price(*args, normalized["max_images"])
    if normalized["model"] in ("wan_3", "wan_3_prime"):
        input_seconds = Decimal(str(normalized.get("wan_input_seconds") or "0"))
        if not input_seconds.is_finite() or not 0 <= input_seconds <= 15:
            raise ValueError("Invalid Wan3 input duration")
        reserved_seconds = (
            Decimal(30) if normalized["duration"] == -1
            else input_seconds + normalized["duration"]
        )
        if reserved_seconds > 30:
            raise ValueError("Wan3 total duration cannot exceed 30 seconds")
        configured = preset_manager.get_video_quality_costs(normalized["model"])
        rate = next((v for k,v in configured.items()
                     if str(k).lower() == normalized["quality"].lower()), None)
        if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
            raise ValueError("Missing Wan3 resolution rate")
        from bot.services.wan3_prime_lifecycle import _round_half_credit

        value = _round_half_credit(float(Decimal(str(rate)) * reserved_seconds))
        if value <= 0:
            raise ValueError("Wan3 reserve rounded to zero")
        return str(Decimal(value))
    return _price(*args)


def _models() -> list[dict]:
    from bot import miniapp

    all_models = []
    for media_type, inventory in (
        ("image", miniapp.IMAGE_MODELS), ("video", miniapp.VIDEO_MODELS),
    ):
        for canonical in inventory:
            model = canonical["id"]
            supported = model in (_IMAGE_MODELS if media_type == "image" else _VIDEO_MODELS)
            entry = {
                "id": model, "label": canonical["label"],
                "type": media_type,
                "description": canonical.get("description", ""),
                "ratios": list(canonical.get("ratios", [])),
                "max_references": _web_max_image_refs(model, canonical),
                "max_video_references": (
                    1 if model == "gemini_omni"
                    else min(
                        5 if model in ("wan_3", "wan_3_prime") else 1,
                        int(canonical.get("max_video_references", 0)),
                    )
                ),
                "max_audio_references": (
                    min(
                        5 if model in ("wan_3", "wan_3_prime") else 1,
                        int(canonical.get("max_audio_references", 0)),
                    )
                ),
                "max_file_references": 1 if model in ("wan_3", "wan_3_prime") else 0,
                "max_link_references": 1 if model in ("wan_3", "wan_3_prime") else 0,
                "enabled": bool(supported),
                "unavailable_reason": None if supported else (
                    "Для этой модели ещё не подключены безопасные веб-тарификация, "
                    "провайдерский контракт или доставка результата."
                ),
            }
            for option in (
                "requires_reference", "requires_audio", "requires_image",
                "supports_layers", "supports_nsfw_checker",
                "supports_output_format", "supports_background",
                "supports_negative_prompt", "supports_cfg_scale",
                "wan_resolutions", "omni_modes", "veo_generation_types",
                "veo_resolutions", "grok_modes", "grok_resolutions",
            ):
                if option in canonical:
                    entry[option] = canonical[option]
            if media_type == "image":
                qualities = list(canonical.get("qualities") or [])
                if model == "seedream_55_layers":
                    qualities.append("auto")
                    entry["supports_layers"] = True
                    entry["layers_max_images"] = {"min": 2, "max": 100, "default": 30}
                    entry["layers_formats"] = ["png", "jpeg"]
                entry["qualities"] = qualities
                if supported:
                    default_quality = _quality_value(model, canonical, None)
                    try:
                        default_refs = 1 if model == "seedream_55_layers" else 0
                        entry["price"] = _price(media_type, model, 5,
                                                quality=default_quality,
                                                reference_count=default_refs)
                        entry["quality_costs"] = {
                            q: _price(media_type, model, 5, quality=q,
                                      reference_count=default_refs)
                            for q in qualities
                        }
                    except (ValueError, TypeError, KeyError):
                        entry["enabled"] = False
                        entry["unavailable_reason"] = "Нет корректного тарифа для этой модели."
            else:
                entry["durations"] = _web_durations(model, canonical)
                entry["qualities"] = list(
                    canonical.get("omni_resolutions") if model == "gemini_omni"
                    else canonical.get("wan_resolutions") if model in ("wan_3", "wan_3_prime")
                    else canonical.get("grok_resolutions") if model == "grok_imagine_v15"
                    else canonical.get("veo_resolutions") if model == "veo3_fast"
                    else canonical.get("motion_modes") or []
                )
                if model in ("wan_3", "wan_3_prime"):
                    # Video/audio/file/link modes need measured input duration
                    # and first-party asset probes, so expose only image modes.
                    entry["supported_modes"] = [
                        "text", "first_frame", "first_last", "reference",
                        "edit", "file", "link",
                    ]
                if model == "gemini_omni":
                    # Audio ID and Character ID need separate account-owned
                    # asset lifecycles; do not make them look purchasable.
                    entry["supported_modes"] = [
                        "video_text", "video_images", "video_reference",
                        "audio_id", "character_id",
                    ]
                if supported:
                    try:
                        by_duration = {
                            str(d): _price(media_type, model, d, entry["qualities"][0]
                                            if entry["qualities"] else None)
                            for d in entry["durations"]
                        }
                        entry["prices_by_duration"] = by_duration
                        first = entry["durations"][0]
                        entry["price"] = by_duration[str(first)]
                        if entry["qualities"]:
                            entry["quality_costs"] = {
                                quality: _price(media_type, model, first, quality)
                                for quality in entry["qualities"]
                            }
                    except (ValueError, TypeError, KeyError):
                        entry["enabled"] = False
                        entry["unavailable_reason"] = "Нет корректного тарифа для длительности."
            all_models.append(entry)
    return all_models


def _normalize_request(body: dict) -> dict:
    allowed = {
        "model", "prompt", "request_key", "aspect_ratio", "duration",
        "reference_ids", "video_reference_ids", "audio_reference_ids",
        "quality", "expected_price", "max_images", "text_recognition",
        "output_format", "wan_scenario",
        "omni_audio_asset_ids", "omni_character_asset_ids", "omni_seed",
        "file_reference_ids", "link_reference_ids",
        "background", "nsfw_checker",
    }
    if set(body) - allowed:
        raise ValueError("Unexpected web generation fields")
    model, prompt, key = body.get("model"), body.get("prompt"), body.get("request_key")
    if (not isinstance(model, str) or not isinstance(prompt, str)
            or not isinstance(key, str) or not _REQUEST_KEY.fullmatch(key)):
        raise ValueError("Invalid task payload or idempotency key")
    prompt = prompt.strip()
    if not 2 <= len(prompt) <= 2500:
        raise ValueError("Prompt length must be 2-2500 characters")
    if any(ord(char) < 32 and char not in "\\n\\t" for char in prompt):
        raise ValueError("Prompt contains unsupported control characters")
    media_type, meta = _model_meta(model)
    if model not in (_IMAGE_MODELS if media_type == "image" else _VIDEO_MODELS):
        raise ValueError("Provider adapter unavailable")
    ratios = meta.get("ratios") or []
    ratio = body.get("aspect_ratio") or (
        "1:1" if media_type == "image" and "1:1" in ratios else ratios[0]
    )
    if not isinstance(ratio, str) or ratio not in ratios:
        raise ValueError("Unsupported aspect ratio")
    durations = _web_durations(model, meta)
    duration = body.get("duration", 5 if 5 in durations else durations[0])
    if type(duration) is not int or duration not in durations:
        raise ValueError("Unsupported duration")
    references = body.get("reference_ids", [])
    max_refs = _web_max_image_refs(model, meta)
    if (not isinstance(references, list) or len(references) > max_refs
            or any(not isinstance(ref, str) for ref in references)):
        raise ValueError("Unsupported reference count")
    if meta.get("requires_reference") and not references:
        raise ValueError("Reference image is required")
    if (media_type == "video" and model in {"grok_imagine", "grok_imagine_v15"}
            and not references):
        raise ValueError("This video mode requires a starting image")
    if model == "v26_pro" and len(references) > 1:
        raise ValueError("Too many references for this video recipe")
    if model in ("wan_3", "wan_3_prime"):
        wan_scenario = body.get("wan_scenario", "text")
        if wan_scenario not in (
            "text", "first_frame", "first_last", "reference", "edit",
            "file", "link",
        ):
            raise ValueError("Unsupported independent Wan3 scenario")
        if ((wan_scenario == "text" and references)
                or (wan_scenario == "first_frame" and len(references) != 1)
                or (wan_scenario == "first_last" and len(references) != 2)):
            raise ValueError("Wan3 image count does not match scenario")
    else:
        if "wan_scenario" in body:
            raise ValueError("Wan scenario is not available for this model")
        wan_scenario = ""

    video_refs = body.get("video_reference_ids", [])
    audio_refs = body.get("audio_reference_ids", [])
    file_refs = body.get("file_reference_ids", [])
    link_refs = body.get("link_reference_ids", [])
    for values in (file_refs, link_refs):
        if (not isinstance(values, list) or len(values) > 1
                or any(not isinstance(ref, str)
                       or not re.fullmatch(r"wr_[a-f0-9]{32}", ref) for ref in values)):
            raise ValueError("Wan file/link references must use one verified ID")
    if model in ("wan_3", "wan_3_prime"):
        if ((wan_scenario == "file" and (
            len(file_refs) != 1 or link_refs or references or video_refs or audio_refs
        )) or (wan_scenario == "link" and (
            len(link_refs) != 1 or file_refs or references or video_refs or audio_refs
        )) or (wan_scenario not in ("file", "link") and (file_refs or link_refs))):
            raise ValueError("Wan3 file/link scenario expects exactly its owned input")
    elif file_refs or link_refs:
        raise ValueError("File/link mode is only supported by Wan3")
    max_multimedia = 5 if model in ("wan_3", "wan_3_prime") else 1
    for refs in (video_refs, audio_refs):
        if (not isinstance(refs, list) or len(refs) > max_multimedia
                or any(not isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs)):
            raise ValueError("Unsupported video/audio reference count")
    if model in ("wan_3", "wan_3_prime") and (
        (wan_scenario in ("text", "first_frame", "first_last")
         and (video_refs or audio_refs))
        or (wan_scenario == "edit" and not video_refs)
        or (wan_scenario == "reference"
            and not (references or video_refs or audio_refs))
    ):
        raise ValueError("Wan3 requires owned inputs matching its scenario")
    motion = model in ("motion_control_v26", "motion_control_v30")
    avatar = model in ("avatar_std", "avatar_pro")
    if motion:
        if len(references) != 1 or len(video_refs) != 1 or audio_refs:
            raise ValueError("Motion Control requires one image and one video")
    elif avatar:
        if len(references) != 1 or len(audio_refs) != 1 or video_refs:
            raise ValueError("Avatar requires one image and one audio reference")
    elif (video_refs or audio_refs) and model not in (
        "wan_3", "wan_3_prime", "gemini_omni",
    ):
        raise ValueError("Unexpected multimedia references for selected model")
    if model == "gemini_omni" and audio_refs:
        raise ValueError("Gemini Omni requires linked Audio IDs, not audio files")
    if model == "gemini_omni" and len(video_refs) > 1:
        raise ValueError("Gemini Omni supports one owned video reference")
    quality_raw = body.get("quality")
    if quality_raw is not None and not isinstance(quality_raw, str):
        raise ValueError("Invalid quality")
    quality = _quality_value(model, meta, quality_raw)
    if model == "seedream_55_layers":
        if (len(references) != 1 or len(prompt) > 2000
                or video_refs or audio_refs):
            raise ValueError("Layers need exactly one image reference and a short prompt")
        max_images = body.get("max_images", 30)
        if type(max_images) is not int or not 2 <= max_images <= 100:
            raise ValueError("Layers output count must be between 2 and 100")
        text_recognition = body.get("text_recognition", False)
        if type(text_recognition) is not bool:
            raise ValueError("Layers text recognition must be a boolean")
        output_format = body.get("output_format", "png")
        if output_format not in ("png", "jpeg"):
            raise ValueError("Unsupported layers output format")
    else:
        if any(name in body for name in ("max_images", "text_recognition")):
            raise ValueError("Layers options are not supported by this model")
        if model != "seedream_55" and "output_format" in body:
            raise ValueError("Output format is unsupported by this model")
        max_images, text_recognition = 30, False
        output_format = body.get("output_format", "png") if model == "seedream_55" else "png"
    if model in ("seedream_55", "seedream_55_layers"):
        if output_format not in ("png", "jpeg"):
            raise ValueError("Unsupported Seedream 5.5 output format")
        nsfw_checker = body.get("nsfw_checker", False)
        if type(nsfw_checker) is not bool:
            raise ValueError("Invalid Seedream 5.5 NSFW checker")
        if model == "seedream_55":
            background = body.get("background", "auto")
            if background not in ("auto", "transparent", "opaque"):
                raise ValueError("Invalid Seedream 5.5 background")
            if background == "transparent" and output_format != "png":
                raise ValueError("Transparent background requires PNG")
            if not references and ratio == "auto":
                raise ValueError("Seedream 5.5 text-only requires a concrete ratio")
        else:
            if "background" in body:
                raise ValueError("Layer decomposition doesn't support backgrounds")
            background = "auto"
    else:
        if any(key in body for key in ("background", "nsfw_checker")):
            raise ValueError("These controls are exclusive to Seedream 5.5")
        background, nsfw_checker = "auto", False
    if model == "gemini_omni":
        from bot.web_omni_assets import _ASSET_ID

        omni_audio_ids = body.get("omni_audio_asset_ids", [])
        omni_character_ids = body.get("omni_character_asset_ids", [])
        for values, maximum in ((omni_audio_ids, 1), (omni_character_ids, 3)):
            if (not isinstance(values, list) or len(values) > maximum
                    or len(set(values)) != len(values)
                    or any(not isinstance(asset, str) or not _ASSET_ID.fullmatch(asset)
                           for asset in values)):
                raise ValueError("Unsupported Omni asset references")
        omni_seed = body.get("omni_seed")
        if omni_seed is not None and (
            type(omni_seed) is not int or not 0 <= omni_seed <= 2147483647
        ):
            raise ValueError("Omni random seed is out of range")
        if len(references) + len(video_refs) * 2 + len(omni_character_ids) > 7:
            raise ValueError("Gemini Omni input slot limit exceeded")
    else:
        if any(key in body for key in (
            "omni_audio_asset_ids", "omni_character_asset_ids", "omni_seed",
        )):
            raise ValueError("Omni asset inputs are not available in this model")
        omni_audio_ids, omni_character_ids, omni_seed = [], [], None
    if model in ("wan_3", "wan_3_prime", "gemini_omni"):
        # A missing quality-specific admin tariff is NOT a purchasable model.
        # Guard both catalog and create/quote; display flags aren't security.
        _price(media_type, model, duration, quality, len(references))
    expected_price = body.get("expected_price")
    if expected_price is not None:
        if not isinstance(expected_price, str):
            raise ValueError("Expected price must be a string")
        try:
            expected_units = amount_units(Decimal(expected_price))
        except (ValueError, InvalidOperation, TypeError) as exc:
            raise ValueError("Invalid expected price") from exc
        if expected_units <= 0:
            raise ValueError("Expected price must be positive")
    return {
        "model": model, "media_type": media_type,
        "prompt": prompt, "aspect_ratio": ratio,
        "duration": duration, "request_key": key,
        "quality": quality, "reference_ids": references,
        "video_reference_ids": video_refs, "audio_reference_ids": audio_refs,
        "expected_price": expected_price,
        "max_images": max_images, "text_recognition": text_recognition,
        "output_format": output_format, "background": background,
        "nsfw_checker": nsfw_checker, "wan_scenario": wan_scenario,
        "file_reference_ids": file_refs, "link_reference_ids": link_refs,
        "omni_audio_asset_ids": omni_audio_ids,
        "omni_character_asset_ids": omni_character_ids,
        "omni_seed": omni_seed,
    }


def _hash_request(payload: dict) -> str:
    fields = {
        key: payload[key] for key in (
            "model", "media_type", "prompt", "aspect_ratio", "duration",
            "reference_ids", "video_reference_ids", "audio_reference_ids", "quality",
            "max_images", "text_recognition", "output_format", "wan_scenario",
            "background", "nsfw_checker",
            "omni_audio_asset_ids", "omni_character_asset_ids", "omni_seed",
            "file_reference_ids", "link_reference_ids",
        )
    }
    # Audio/character asset options and linked account-owned IDs are
    # immutable under the same task idempotency key.
    if "asset_payload" in payload:
        fields["asset_payload"] = payload["asset_payload"]
    return hashlib.sha256(json.dumps(
        fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def _public_record(row) -> dict:
    return {
        "task_id": row[0], "status": row[1], "model": row[2],
        "type": row[3], "price": row[4],
    }


async def model_catalog(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account

    if not await _session_account(request):
        return _json({"ok": False, "error": "session_required"}, 401)
    return _json({"ok": True, "models": _models(), "enabled": _enabled()
                  and bool(config.KIE_AI_API_KEY)})


async def quote_generation(request: web.Request) -> web.Response:
    """A server-authoritative quote for model, quality, duration and references."""
    from bot.web_auth import _json, _session_account, _valid_browser_origin
    from bot.web_references import owned_reference_urls

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if request.content_length and request.content_length > 12288:
        return _json({"ok": False, "error": "Request too large"}, 413)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise TypeError("Invalid quote")
        normalized = _normalize_request({
            **data,
            "request_key": "web-quote-validation-key-2026",
        })
        if normalized["model"] in ("wan_3", "wan_3_prime"):
            from bot.web_wan3 import prepare_owned_wan_media
            await prepare_owned_wan_media(account, normalized)
        if normalized["model"] == "gemini_omni":
            from bot.web_omni_assets import prepare_omni_video
            await prepare_omni_video(account, normalized)
        await owned_reference_urls(account, normalized["reference_ids"], kind="image")
        await owned_reference_urls(account, normalized["video_reference_ids"], kind="video")
        await owned_reference_urls(account, normalized["audio_reference_ids"], kind="audio")
        await owned_reference_urls(account, normalized["file_reference_ids"], kind="file")
        await owned_reference_urls(account, normalized["link_reference_ids"], kind="link")
        amount = _price_for_request(normalized)
        return _json({
            "ok": True, "model": normalized["model"],
            "price": amount,
            "type": normalized["media_type"],
            "reference_count": len(normalized["reference_ids"]),
            "duration": normalized["duration"],
            "quality": normalized["quality"],
        })
    except (ValueError, TypeError, KeyError):
        return _json({"ok": False, "error": "Недоступная модель или неверные параметры."}, 400)
    except PermissionError:
        return _json({"ok": False, "error": "Недоступные или чужие референсы."}, 403)


async def create_generation(request: web.Request) -> web.Response:
    from bot.web_auth import _json, _session_account, _valid_browser_origin

    if not _valid_browser_origin(request):
        return _json({"ok": False, "error": "origin_rejected"}, 403)
    account = await _session_account(request)
    if not account:
        return _json({"ok": False, "error": "session_required"}, 401)
    if not _enabled() or not config.KIE_AI_API_KEY:
        return _json({"ok": False, "error": "Web generation is not configured"}, 503)
    if request.content_length and request.content_length > 12288:
        return _json({"ok": False, "error": "Request too large"}, 413)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError("Invalid JSON object")
        normalized = _normalize_request(body)
        if normalized["model"] in ("wan_3", "wan_3_prime"):
            from bot.web_wan3 import prepare_owned_wan_media
            await prepare_owned_wan_media(account, normalized)
        if normalized["model"] == "gemini_omni":
            from bot.web_omni_assets import prepare_omni_video
            await prepare_omni_video(account, normalized)
        cost = _price_for_request(normalized)
        units = amount_units(cost)
    except PermissionError:
        return _json({"ok": False, "error": "Чужой Audio ID, Character ID или видео."}, 403)
    except (ValueError, TypeError, KeyError) as exc:
        logger.debug("web_task_input_rejected type=%s", type(exc).__name__)
        return _json({"ok": False, "error": "Проверьте модель, длительность и промпт."}, 400)

    # Verify all references belong to the signed account before any wallet
    # reservation. Client-supplied provider URLs are not accepted.
    from bot.web_references import owned_reference_urls

    try:
        normalized["reference_urls"] = await owned_reference_urls(
            account, normalized["reference_ids"], kind="image",
        )
        normalized["reference_video_urls"] = await owned_reference_urls(
            account, normalized["video_reference_ids"], kind="video",
        )
        normalized["reference_audio_urls"] = await owned_reference_urls(
            account, normalized["audio_reference_ids"], kind="audio",
        )
        normalized["reference_file_urls"] = await owned_reference_urls(
            account, normalized["file_reference_ids"], kind="file",
        )
        normalized["reference_link_urls"] = await owned_reference_urls(
            account, normalized["link_reference_ids"], kind="link",
        )
    except (ValueError, PermissionError):
        return _json({"ok": False, "error": "Недоступные или чужие референсы."}, 403)
    if (normalized["expected_price"] is not None
            and amount_units(normalized["expected_price"]) != units):
        return _json({
            "ok": False, "error": "Стоимость изменилась. Обновите расчёт.",
            "code": "price_changed", "current_price": cost,
        }, 409)
    if normalized["model"] in ("wan_3", "wan_3_prime"):
        rates = preset_manager.get_video_quality_costs(normalized["model"])
        value = next(
            (v for k, v in rates.items()
             if str(k).lower() == normalized["quality"].lower()), None,
        )
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            return _json({"ok": False, "error": "Нет тарифа для разрешения Wan3."}, 503)
        normalized["wan_rate_snapshot"] = str(Decimal(str(value)))
    if normalized["model"] == "seedream_55_layers":
        from bot.services.seedream55_pricing import QUALITY_PRICE_KEYS, price_cells

        cells = price_cells()
        chosen = normalized["quality"]
        output_unit = Decimal(str(cells[QUALITY_PRICE_KEYS.get(
            chosen, QUALITY_PRICE_KEYS["2K"],
        )]))
        input_unit = Decimal(str(cells["seedream_55_ref"]))
        if amount_units(input_unit + output_unit * normalized["max_images"]) != units:
            return _json({"ok": False, "error": "Стоимость изменилась. Обновите расчёт.",
                          "code": "price_changed"}, 409)
        normalized["layer_rate_snapshot"] = {
            "input_unit": str(input_unit), "output_unit": str(output_unit),
        }
    return await reserve_web_task(account, normalized, cost, units)


async def reserve_web_task(
    account: str, normalized: dict, cost: str, units: int,
) -> web.Response:
    """Unified atomic reservation for browser media and Omni asset jobs.

    Both share identical idempotency, pending limits, ownership and ledger
    semantics. No provider submission occurs inside the database transaction.
    """
    from bot.web_auth import _json

    await ensure_web_tasks_schema()
    wallet = WalletService("live")
    request_hash = _hash_request(normalized)
    try:
        async with wallet._transaction(account) as (db, balance, canonical):
            task_id = "web_" + hashlib.sha256(
                (canonical + ":" + normalized["request_key"]).encode()).hexdigest()[:32]
            reserve = "web:reserve:" + task_id
            row = await (await db.execute(
                """SELECT task_id,status,model,media_type,cost,request_hash
                   FROM web_generation_tasks WHERE task_id=?""", (task_id,),
            )).fetchone()
            if row:
                if row[5] != request_hash:
                    return _json({"ok": False, "error": "Ключ запроса уже занят."}, 409)
                return _json(_public_record(row), 200)

            max_running = _seconds("WEB_GENERATION_MAX_PENDING_TASKS", 5, 1, 50)
            pending = await (await db.execute(
                """SELECT COUNT(*) FROM web_generation_tasks
                   WHERE status='pending' AND account_id IN (
                       WITH RECURSIVE owned(id) AS (
                           SELECT ? UNION ALL SELECT a.id FROM shared_accounts a
                           JOIN owned o ON a.merged_into=o.id WHERE a.status='merged'
                       ) SELECT id FROM owned)""", (canonical,),
            )).fetchone()
            if int(pending[0]) >= max_running:
                return _json({"ok": False, "error": "Слишком много текущих задач."}, 429)
            if balance.available_units < units:
                return _json({"ok": False, "error": "Недостаточно средств на веб-балансе."}, 402)
            await db.execute(
                """INSERT INTO shared_wallet_reservations
                   (scope,reservation_key,account_id,amount_units)
                   VALUES ('live',?,?,?)""", (reserve, canonical, units),
            )
            await wallet._append(db, canonical, balance, reserve, "reserve",
                                 units, "", -units, units)
            stamp = int(time.time())
            deadline = stamp + _seconds(
                "WEB_GENERATION_TASK_DEADLINE_SECONDS",
                _PENDING_DEADLINE_SECONDS, 300, 86400,
            )
            await db.execute(
                """INSERT INTO web_generation_tasks
                   (task_id,account_id,media_type,model,status,request_key,
                    request_hash,request_json,cost,reservation_key,phase,
                    lease_until_epoch,deadline_epoch,asset_key,
                    created_at_epoch,updated_at_epoch)
                   VALUES (?,?,?,?,'pending',?,?,?,?,?,'queued',0,?,?,?,?)""",
                (task_id, canonical, normalized["media_type"], normalized["model"],
                 normalized["request_key"], request_hash,
                 json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
                 cost, reserve, deadline, uuid4().hex, stamp, stamp),
            )
            logger.info("web_task_reserved task=%s model=%s amount=%s", task_id, normalized["model"], cost)
            return _json({"ok": True, "task_id": task_id, "status": "pending",
                          "model": normalized["model"],
                          "type": normalized["media_type"], "price": cost}, 202)
    except InsufficientFunds:
        return _json({"ok": False, "error": "Недостаточно средств."}, 402)
    except WalletConflict:
        return _json({"ok": False, "error": "Параллельная операция, повторите запрос."}, 409)


def _callback_secret() -> bytes:
    # Secret is server-only; KIE sees only a signed task-specific verifier.
    key = os.getenv("WEB_GENERATION_CALLBACK_SECRET", "").strip() or config.BOT_TOKEN
    return hashlib.sha256(key.encode("utf-8")).digest()


def _callback_signature(task_id: str) -> str:
    return hmac.new(_callback_secret(), task_id.encode(), hashlib.sha256).hexdigest()


def _callback_url(task_id: str) -> str:
    from bot.web_auth import _public_origin

    origin = _public_origin()
    if not origin.startswith("https://"):
        return ""
    return (f"{origin}/mini-app/api/web-generation/callback"
            f"?task_id={task_id}&signature={_callback_signature(task_id)}")


async def provider_callback(request: web.Request) -> web.Response:
    """Provider push is only a hint; never trust unverified success/result data."""
    task_id = str(request.query.get("task_id") or "")
    signature = str(request.query.get("signature") or "")
    if (not _TASK_ID.fullmatch(task_id)
            or not hmac.compare_digest(signature, _callback_signature(task_id))):
        return web.Response(status=401)
    if request.content_length and request.content_length > 32768:
        return web.Response(status=413)
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        return web.Response(status=400)
    await ensure_web_tasks_schema()
    async with db_backend.connect() as db:
        # Callback cannot credit/capture or complete a task: the poller always
        # re-queries KIE with our own provider API key and checks IDs.
        await db.execute(
            """UPDATE web_generation_tasks SET lease_until_epoch=0
               WHERE task_id=? AND status='pending' AND phase='provider'
               AND provider_task_id IS NOT NULL""", (task_id,),
        )
        await db.commit()
    return web.Response(status=202)


def register_routes(app: web.Application, prefix: str) -> None:
    app.router.add_get(prefix + "/web-generation/models", model_catalog)
    app.router.add_post(prefix + "/web-generation/quote", quote_generation)
    app.router.add_post(prefix + "/web-generation/create", create_generation)
    app.router.add_post(prefix + "/web-generation/callback", provider_callback)
    from bot.web_references import register_routes as register_reference_routes

    register_reference_routes(app, prefix)
    from bot.web_omni_assets import register_routes as register_omni_routes
    register_omni_routes(app, prefix)


def _provider_result_url(value) -> str | None:
    if isinstance(value, str):
        if value.startswith("https://"):
            return value
        if value.startswith("{"):
            try:
                return _provider_result_url(json.loads(value))
            except (ValueError, TypeError):
                return None
    if isinstance(value, list):
        for item in value:
            url = _provider_result_url(item)
            if url:
                return url
    if isinstance(value, dict):
        for key in ("resultUrls", "result_urls", "url", "resultUrl", "videoUrl",
                    "imageUrl", "output", "videos", "images"):
            url = _provider_result_url(value.get(key))
            if url:
                return url
    return None


async def _submit_to_provider(task_id: str, payload: dict) -> tuple[str | None, bool]:
    """Returns (provider_task_id, explicit_rejection).

    The provider may time out *after* accepting payment. Without its taskId
    automatic resubmission would create a second paid provider call, so a
    temporary outage retains a submitting lease until safe reconciliation.
    """
    model, ratio, prompt, duration = (
        payload["model"], payload["aspect_ratio"],
        payload["prompt"], payload["duration"],
    )
    reference_urls = payload.get("reference_urls") or []
    reference_video_urls = payload.get("reference_video_urls") or []
    reference_audio_urls = payload.get("reference_audio_urls") or []
    reference_file_urls = payload.get("reference_file_urls") or []
    reference_link_urls = payload.get("reference_link_urls") or []
    callback = _callback_url(task_id)
    def identifier_from(result) -> tuple[str | None, bool]:
        if isinstance(result, str) and result.strip():
            return result, False
        if not isinstance(result, dict):
            return None, False
        identifier = result.get("task_id") or result.get("taskId")
        if identifier:
            return str(identifier), False
        # Only an explicitly validated *non-billable* input error is safe
        # to refund immediately. API/network failures may have accepted
        # provider work and are uncertain until reconciliation.
        error = str(result.get("error") or "")
        return None, error in {"invalid_input", "prompt_required", "unsupported_model"}

    try:
        quality = str(payload.get("quality") or "")
        if model == "banana_pro":
            from bot.services.nano_banana_pro_service import nano_banana_pro_service

            return identifier_from(await nano_banana_pro_service.create_task(
                prompt, image_input=reference_urls, aspect_ratio=ratio,
                resolution=quality or "2K", callback_url=callback or None,
            ))
        if model == "banana_2":
            from bot.services.nano_banana_2_service import nano_banana_2_service

            return identifier_from(await nano_banana_2_service.create_task(
                prompt, image_input=reference_urls, aspect_ratio=ratio,
                resolution=quality or "2K", callback_url=callback or None,
            ))
        if model == "seedream_55_layers":
            from bot.services.seedream55_service import seedream55_service

            return identifier_from(await seedream55_service.generate_layers(
                reference_urls[0], prompt=prompt,
                size=quality or "2K",
                output_format=str(payload.get("output_format") or "png"),
                max_images=int(payload["max_images"]),
                text_recognition=bool(payload["text_recognition"]),
                nsfw_checker=bool(payload.get("nsfw_checker", False)),
                callBackUrl=callback or None,
            ))
        if model == "seedream_55":
            from bot.services.seedream55_service import seedream55_service

            if reference_urls:
                return identifier_from(await seedream55_service.generate_image(
                    prompt, reference_urls, aspect_ratio=ratio,
                    size=quality or "2K",
                    output_format=str(payload.get("output_format") or "png"),
                    background=str(payload.get("background") or "auto"),
                    nsfw_checker=bool(payload.get("nsfw_checker", False)),
                    callBackUrl=callback or None,
                ))
            return identifier_from(await seedream55_service.generate_text_to_image(
                prompt, aspect_ratio=ratio, size=quality or "2K",
                output_format=str(payload.get("output_format") or "png"),
                background=str(payload.get("background") or "auto"),
                nsfw_checker=bool(payload.get("nsfw_checker", False)),
                callBackUrl=callback or None,
            ))
        if model == "seedream_5_pro":
            from bot.services.seedream_service import seedream_service

            if reference_urls:
                return identifier_from(await seedream_service.generate_image(
                    prompt, reference_urls, aspect_ratio=ratio,
                    quality=quality or "basic",
                    model="seedream/5-pro-image-to-image",
                    callBackUrl=callback or None,
                ))
            return identifier_from(await seedream_service.generate_text_to_image(
                prompt, aspect_ratio=ratio, quality=quality or "basic",
                model="seedream/5-pro-text-to-image",
                callBackUrl=callback or None,
            ))
        if model == "seedream_edit":
            from bot.services.seedream_service import seedream_service

            return identifier_from(await seedream_service.generate_image(
                prompt, reference_urls, aspect_ratio=ratio,
                quality="high" if quality == "4K" else "basic",
                model="seedream/4.5-edit", callBackUrl=callback or None,
            ))
        if model == "wan_27":
            from bot.services.wan27_service import wan27_service

            return identifier_from(await wan27_service.generate_image(
                prompt=prompt, input_urls=reference_urls,
                aspect_ratio=ratio, n=1, resolution="2K", pro=True,
                callBackUrl=callback or None,
            ))
        if model == "grok_imagine_i2i":
            from bot.services.grok_service import grok_service

            return identifier_from(await grok_service.generate_image_to_image(
                reference_urls, prompt=prompt, callBackUrl=callback or None,
            ))
        if model == "grok_imagine":
            from bot.services.grok_service import grok_service

            return identifier_from(await grok_service.generate_image_to_video(
                image_urls=reference_urls, prompt=prompt,
                mode="normal", duration=duration, aspect_ratio=ratio,
                callBackUrl=callback or None,
            ))
        if model == "grok_imagine_v15":
            from bot.services.grok_service import grok_service

            return identifier_from(await grok_service.generate_image_to_video_v15(
                image_urls=reference_urls[:1], prompt=prompt,
                duration=duration, aspect_ratio=ratio, resolution=quality or "480p",
                callBackUrl=callback or None,
            ))
        if model == "seedance_2":
            from bot.services.seedance_service import seedance_service

            return identifier_from(await seedance_service.generate_video(
                prompt=prompt, duration=duration, aspect_ratio=ratio,
                resolution="720p", reference_image_urls=reference_urls or None,
                generate_audio=True, callBackUrl=callback or None,
            ))
        if model == "veo3_fast":
            from bot.services.veo_service import veo_service

            return identifier_from(await veo_service.generate_video(
                prompt=prompt, model=model, duration=duration,
                image_urls=reference_urls or None, aspect_ratio=ratio,
                generation_type="FIRST_AND_LAST_FRAMES_2_VIDEO"
                if reference_urls else "TEXT_2_VIDEO",
                resolution=quality or "720p", callBackUrl=callback or None,
            ))
        if model in ("wan_3", "wan_3_prime"):
            from bot.services.wan3_models import wan3_service_for_model

            service = wan3_service_for_model(model)
            scenario = str(payload.get("wan_scenario") or "text")
            arguments = {
                "prompt": prompt, "scenario": scenario,
                "duration": duration, "aspect_ratio": ratio,
                "resolution": quality or "720P",
                "audio": True, "nsfw_checker": False,
            }
            if scenario == "first_frame":
                arguments["first_frame_url"] = reference_urls[0]
            elif scenario == "first_last":
                arguments["first_frame_url"] = reference_urls[0]
                arguments["last_frame_url"] = reference_urls[1]
            elif scenario in ("reference", "edit"):
                arguments["reference_image_urls"] = reference_urls
                arguments["reference_video_urls"] = reference_video_urls
                arguments["reference_audio_urls"] = reference_audio_urls
            elif scenario == "file":
                arguments["reference_file_urls"] = reference_file_urls
            elif scenario == "link":
                arguments["reference_link_urls"] = reference_link_urls
            prepared = await service.prepare_request(**arguments)
            return identifier_from(await service.submit_prepared(
                prepared, callback_url=callback or None,
            ))
        if model == "gemini_omni":
            from bot.services.gemini_omni_service import gemini_omni_service

            video_list = None
            if reference_video_urls:
                end = payload.get("omni_video_ends")
                if type(end) is not int or not 1 <= end <= 20:
                    raise ValueError("Unverified Gemini Omni video reference duration")
                video_list = [{"url": reference_video_urls[0], "start": 0, "ends": end}]
            args = {
                "prompt": prompt, "duration": duration,
                "aspect_ratio": ratio, "resolution": quality or "720p",
                "image_urls": reference_urls or None,
                "callBackUrl": callback or None,
            }
            if video_list:
                args["video_list"] = video_list
            if payload.get("omni_audio_provider_ids"):
                args["audio_ids"] = payload["omni_audio_provider_ids"]
            if payload.get("omni_character_provider_ids"):
                args["character_ids"] = payload["omni_character_provider_ids"]
            if payload.get("omni_seed") is not None:
                args["seed"] = payload["omni_seed"]
            return identifier_from(await gemini_omni_service.generate_video(**args))
        if model in ("motion_control_v26", "motion_control_v30"):
            provider = KlingService(kie_key=config.KIE_AI_API_KEY)
            return identifier_from(await provider.generate_motion_control(
                image_url=reference_urls[0],
                video_urls=reference_video_urls[:1],
                prompt=prompt,
                mode=quality or "720p",
                motion_model=model,
                webhook_url=callback or None,
            ))
        if model in ("avatar_std", "avatar_pro"):
            provider = KlingService(kie_key=config.KIE_AI_API_KEY)
            actual = "kling/ai-avatar-standard" if model == "avatar_std" else "kling/ai-avatar-pro"
            return identifier_from(await provider.generate_kling_ai_avatar(
                image_url=reference_urls[0],
                audio_url=reference_audio_urls[0],
                prompt=prompt,
                model=actual,
                webhook=callback or None,
            ))
        if model == "flux_pro":
            if reference_urls:
                result = await gpt_image_service.generate_image_to_image(
                    prompt, input_urls=reference_urls, aspect_ratio=ratio,
                    callBackUrl=callback or None,
                )
            else:
                result = await gpt_image_service.generate_image(
                    prompt, aspect_ratio=ratio, callBackUrl=callback or None,
                )
            return str(result.get("task_id")) if result and result.get("task_id") else None, (
                isinstance(result, dict) and result.get("error") in {
                    "api_error", "prompt_required", "missing_api_key", "invalid_response_type",
                }
            )
        if model == "nano-banana-2-lite":
            identifier = await kie_market_service.create_nano_banana_2_lite_task(
                prompt, image_urls=reference_urls,
                aspect_ratio=ratio, callback_url=callback or None,
            )
            return str(identifier) if identifier else None, False
        provider = KlingService(kie_key=config.KIE_AI_API_KEY)
        if model in ("v3_std", "v3_pro"):
            result = await provider.generate_kling_3_video(
                prompt, mode="std" if model == "v3_std" else "pro",
                duration=duration, aspect_ratio=ratio, sound=False,
                image_urls=reference_urls, webhook=callback or None,
            )
        elif model == "v26_pro":
            result = await provider.generate_kling_25_turbo_video(
                prompt, duration=duration, aspect_ratio=ratio,
                image_url=reference_urls[0] if reference_urls else None,
                webhook=callback or None,
            )
        else:
            return None, True
        return str(result.get("task_id")) if result and result.get("task_id") else None, (
            isinstance(result, dict) and result.get("error") in {
                "api_error", "prompt_required", "unsupported_model", "missing_api_key",
            }
        )
    except Exception:
        logger.exception("web_provider_submission_uncertain task=%s", task_id)
        return None, False


async def _provider_check(task_id: str, provider_task_id: str, model: str) -> tuple[str, str | list[str] | None]:
    if model == "seedream_55_layers":
        from bot.services.seedream55_results import extract_layers

        data = await kie_market_service.get_task_status(provider_task_id)
        if not isinstance(data, dict):
            return "pending", None
        observed = str(data.get("taskId") or data.get("task_id") or "")
        if observed and observed != provider_task_id:
            logger.error("web_layer_poll_task_binding_mismatch task=%s", task_id)
            return "pending", None
        state = str(data.get("state") or data.get("status") or "pending").lower()
        if state in ("success", "completed", "succeeded"):
            result_json = data.get("resultJson")
            if isinstance(result_json, str):
                result_json = json.loads(result_json)
            urls, _details = extract_layers(result_json)
            return state, urls
        return state, None
    if model == "veo3_fast":
        from bot.services.veo_service import veo_service

        result = await veo_service.get_video_details(provider_task_id)
        if not isinstance(result, dict):
            return "pending", None
        data = result.get("data")
        if not isinstance(data, dict):
            return "pending", None
        actual_id = str(data.get("taskId") or data.get("task_id") or "")
        if actual_id and actual_id != provider_task_id:
            logger.error("web_veo_poll_binding_mismatch task=%s", task_id)
            return "pending", None
        status = str(
            data.get("status") or data.get("state") or "pending"
        ).lower()
        urls = veo_service.extract_result_urls(result)
        return status, _provider_result_url(urls)
    if model == "nano-banana-2-lite":
        result = await kie_market_service.get_task_status(provider_task_id)
        if not isinstance(result, dict):
            return "pending", None
        return str(result.get("state") or result.get("status") or "pending").lower(), (
            _provider_result_url(kie_market_service.parse_result_urls(result))
        )
    provider = KlingService(kie_key=config.KIE_AI_API_KEY)
    result = await provider.get_task_status(provider_task_id)
    if not isinstance(result, dict):
        return "pending", None
    data = result.get("data")
    if not isinstance(data, dict) or data.get("task_id") != provider_task_id:
        return "pending", None
    return str(data.get("status") or "pending").lower(), _provider_result_url(data.get("output"))


async def _task_row(task_id: str):
    async with db_backend.connect() as db:
        return await (await db.execute(
            """SELECT task_id,account_id,media_type,model,status,phase,
                      provider_task_id,request_json,cost,reservation_key,deadline_epoch,
                      lease_until_epoch,asset_key,result_url,attempt_count,error_code,
                      outputs_json,bundle_url,output_count,settled_cost,
                      asset_id,asset_kind
               FROM web_generation_tasks WHERE task_id=?""",
            (task_id,),
        )).fetchone()


async def _task_update(task_id: str, phase: str, *, until: int,
                       error_code: str | None = None) -> None:
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_generation_tasks SET phase=?,lease_until_epoch=?,
               error_code=COALESCE(?,error_code),updated_at_epoch=?
               WHERE task_id=? AND status='pending'""",
            (phase, until, error_code, int(time.time()), task_id),
        )
        await db.commit()


async def _release_failed(row, error_code: str) -> None:
    task_id, account_id, *_ = row
    await _task_update(
        task_id, "releasing",
        until=int(time.time()) + _POLL_LEASE_SECONDS, error_code=error_code,
    )
    try:
        await WalletService("live").apply(
            str(account_id), "release", str(row[8]),
            "web:release:" + task_id, reference_key=str(row[9]),
        )
    except WalletConflict:
        # A parallel success may already have captured it; never issue a
        # new credit to bypass the reservation state machine.
        logger.error("web_release_conflict task=%s", task_id)
        raise
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_generation_tasks SET status='failed',phase='finished',
               error_code=?,lease_until_epoch=0,updated_at_epoch=?
               WHERE task_id=? AND status='pending'""",
            (error_code, int(time.time()), task_id),
        )
        await db.commit()
    logger.info("web_task_refunded task=%s reason=%s", task_id, error_code)


async def _capture_completed(row) -> None:
    task_id, account_id = str(row[0]), str(row[1])
    is_asset = len(row) > 21 and row[21] in ("audio", "character")
    if not row[13] and not is_asset:
        raise ValueError("Cannot capture without a durable result")
    if is_asset:
        if not row[20] or not str(row[20]).startswith("oa_"):
            raise ValueError("Missing persisted Omni asset")
        await ensure_web_tasks_schema()
        async with db_backend.connect() as db:
            owned = await (await db.execute(
                "SELECT asset_id FROM web_omni_assets "
                "WHERE asset_id=? AND source_task_id=? AND account_id=? AND kind=?",
                (row[20], task_id, account_id, row[21]),
            )).fetchone()
        if not owned:
            raise ValueError("Omni asset was not persisted under task owner")
    reserve_units = amount_units(str(row[8]))
    cost = str(row[19]) if len(row) > 19 and row[19] else str(row[8])
    captured_units = amount_units(cost)
    if captured_units <= 0 or captured_units > reserve_units:
        raise ValueError("Settled cost exceeds the original locked wallet reserve")
    if str(row[3]) == "seedream_55_layers" and (
        len(row) <= 19 or not row[19] or not row[17] or not row[18]
    ):
        raise ValueError("Layer bundle must be fully archived before capture")
    # The capture is idempotent even if the process crashes before the
    # unused reserve is released. On replay both operations keep their keys.
    wallet = WalletService("live")
    await wallet.apply(
        account_id, "capture", format_units(captured_units),
        "web:capture:" + task_id, reference_key=str(row[9]),
    )
    unused_units = reserve_units - captured_units
    if unused_units:
        await wallet.apply(
            account_id, "release", format_units(unused_units),
            "web:release:" + task_id, reference_key=str(row[9]),
        )
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_generation_tasks SET status='completed',phase='finished',
               lease_until_epoch=0,updated_at_epoch=?
               WHERE task_id=? AND status='pending'
                 AND (result_url IS NOT NULL OR asset_id IS NOT NULL)""",
            (int(time.time()), task_id),
        )
        await db.commit()
    logger.info("web_task_completed task=%s settled_cost=%s", task_id, cost)


async def _archive_and_settle_layers(row, sources: list[str]) -> None:
    """Durable bundle and exact charged count, based on the frozen quote.

    No result writes to the legacy Telegram task database. Every retry uses
    the original web task asset key and CAS lease. All media is S3-backed
    before *any* wallet capture is attempted.
    """
    task_id, reserved = str(row[0]), Decimal(str(row[8]))
    payload = json.loads(row[7])
    max_images = payload["max_images"]
    if (not isinstance(sources, list) or not 2 <= len(sources) <= max_images
            or len(set(sources)) != len(sources)):
        await _release_failed(row, "invalid_layers_result_count")
        return
    snapshot = payload.get("layer_rate_snapshot") or {}
    if set(snapshot) != {"input_unit", "output_unit"}:
        raise ValueError("Missing frozen layer price snapshot")
    input_unit = Decimal(str(snapshot["input_unit"]))
    output_unit = Decimal(str(snapshot["output_unit"]))
    actual = input_unit + output_unit * len(sources)
    if (not actual.is_finite() or actual <= 0 or actual > reserved
            or amount_units(actual) > amount_units(reserved)):
        raise ValueError("Invalid layer settlement would exceed locked funds")
    from bot.web_layers import archive_web_layers

    durable_urls, bundle_url = await archive_web_layers(
        task_id, str(row[12]), sources,
    )
    if (len(durable_urls) != len(sources) or not bundle_url
            or any(not isinstance(url, str) or not url.startswith("https://")
                   for url in durable_urls)):
        raise OSError("Layer bundle did not persist all outputs")
    async with db_backend.connect() as db:
        await db.execute(
            """UPDATE web_generation_tasks SET result_url=?,outputs_json=?,
               bundle_url=?,output_count=?,settled_cost=?,phase='settling',
               lease_until_epoch=0,updated_at_epoch=?
               WHERE task_id=? AND status='pending' AND phase IN ('checking','provider')""",
            (durable_urls[0],
             json.dumps(durable_urls, separators=(",", ":")),
             bundle_url, len(durable_urls), format_units(amount_units(actual)),
             int(time.time()), task_id),
        )
        await db.commit()
    await _capture_completed(await _task_row(task_id))


async def _process_task(row, *, claimed_from: str) -> None:
    task_id = str(row[0])
    now = int(time.time())
    phase = str(row[5])
    if phase == "releasing":
        await _release_failed(row, str(row[15] or "provider_failed"))
        return
    if phase == "settling":
        await _capture_completed(row)
        return
    if now > int(row[10] or now + 1):
        await _release_failed(row, "deadline_exceeded")
        return
    if phase == "submitting" and claimed_from != "queued":
        # Provider POST outcome cannot be known after a crashed process.
        # Never submit twice without a provider idempotency contract.
        await _release_failed(row, "provider_submission_unconfirmed")
        return
    if phase == "submitting" and claimed_from == "queued":
        payload = json.loads(row[7])
        if str(row[3]) in ("gemini_omni_audio", "gemini_omni_character"):
            from bot.web_omni_assets import persist_omni_asset, submit_omni_asset

            identifier, asset_id, rejected = await submit_omni_asset(task_id, payload)
            if asset_id:
                await persist_omni_asset(row, asset_id)
                return
            if rejected:
                await _release_failed(row, "omni_provider_rejected")
                return
            if not identifier:
                logger.warning("web_omni_asset_provider_unconfirmed task=%s", task_id)
                return
            async with db_backend.connect() as db:
                await db.execute(
                    """UPDATE web_generation_tasks SET provider_task_id=?,
                       phase='provider',lease_until_epoch=?,updated_at_epoch=?
                       WHERE task_id=? AND status='pending' AND phase='submitting'""",
                    (identifier, int(time.time()) + _POLL_INTERVAL_SECONDS,
                     int(time.time()), task_id),
                )
                await db.commit()
            return
        identifier, explicit_rejection = await _submit_to_provider(task_id, payload)
        if identifier:
            async with db_backend.connect() as db:
                await db.execute(
                    """UPDATE web_generation_tasks SET provider_task_id=?,
                       phase='provider',lease_until_epoch=?,updated_at_epoch=?
                       WHERE task_id=? AND status='pending' AND phase='submitting'""",
                    (identifier, int(time.time()) + _POLL_INTERVAL_SECONDS,
                     int(time.time()), task_id),
                )
                await db.commit()
            logger.info("web_provider_accepted task=%s provider_task_id=%s", task_id, identifier)
        elif explicit_rejection:
            await _release_failed(row, "provider_rejected")
        else:
            # The current lease remains in effect and expires after timeout.
            logger.warning("web_provider_submission_waiting task=%s", task_id)
        return
    if phase not in ("provider", "checking"):
        return
    if not row[6]:
        await _release_failed(row, "missing_provider_task_id")
        return
    if str(row[3]) in ("gemini_omni_audio", "gemini_omni_character"):
        from bot.web_omni_assets import persist_omni_asset, poll_omni_asset

        kind = "audio" if row[3] == "gemini_omni_audio" else "character"
        try:
            asset_state, asset_id = await poll_omni_asset(str(row[6]), kind)
        except Exception:
            logger.exception("web_omni_asset_poll_failed task=%s", task_id)
            asset_state, asset_id = "pending", None
        if asset_state in ("fail", "failed", "error", "rejected", "cancelled"):
            await _release_failed(row, "omni_asset_provider_failed")
            return
        if asset_state in ("success", "completed", "succeeded") and asset_id:
            await persist_omni_asset(row, asset_id)
            return
        await _task_update(task_id, "provider", until=now + _POLL_INTERVAL_SECONDS)
        return
    try:
        status, result_url = await _provider_check(task_id, str(row[6]), str(row[3]))
    except Exception:
        logger.exception("web_provider_poll_unavailable task=%s", task_id)
        status, result_url = "pending", None
    if status in ("fail", "failed", "failure", "error", "rejected", "cancelled"):
        await _release_failed(row, "provider_failed")
        return
    if status in ("success", "completed", "succeeded") and result_url:
        if str(row[3]) == "seedream_55_layers":
            try:
                await _archive_and_settle_layers(row, result_url)
            except Exception:
                logger.exception("web_layer_persistence_retry task=%s", task_id)
                await _task_update(task_id, "provider", until=now + _seconds(
                    "WEB_GENERATION_RETRY_SECONDS", 30, 5, 3600,
                ))
            return
        from bot.web_media_delivery import archive_web_result

        try:
            durable_url = await archive_web_result(
                result_url, task_id, str(row[12]), str(row[2]),
            )
        except Exception:
            logger.exception("web_result_delivery_retry task=%s", task_id)
            await _task_update(task_id, "provider", until=now + _seconds(
                "WEB_GENERATION_RETRY_SECONDS", 30, 5, 3600,
            ))
            return
        settled_cost = None
        result_seconds = None
        if str(row[3]) in ("wan_3", "wan_3_prime"):
            from bot.web_wan3 import inspect_web_wan_output, settled_wan_cost

            try:
                result_seconds = await inspect_web_wan_output(
                    task_id, str(row[12]), durable_url,
                )
                payload = json.loads(row[7])
                settled_cost = settled_wan_cost(
                    payload, result_seconds, str(row[8]),
                )
            except Exception:
                logger.exception("web_wan3_settlement_retry task=%s", task_id)
                await _task_update(task_id, "provider", until=now + _seconds(
                    "WEB_GENERATION_RETRY_SECONDS", 30, 5, 3600,
                ))
                return
        async with db_backend.connect() as db:
            await db.execute(
                """UPDATE web_generation_tasks SET result_url=?,phase='settling',
                   settled_cost=?,result_seconds=?,
                   lease_until_epoch=0,updated_at_epoch=? WHERE task_id=?
                   AND status='pending'""",
                (durable_url, settled_cost,
                 str(result_seconds) if result_seconds is not None else None,
                 int(time.time()), task_id),
            )
            await db.commit()
        await _capture_completed(await _task_row(task_id))
        return
    await _task_update(task_id, "provider", until=int(time.time()) + _POLL_INTERVAL_SECONDS)


async def run_worker_tick() -> list[str]:
    if not _enabled() or not config.KIE_AI_API_KEY:
        return []
    await ensure_web_tasks_schema()
    now = int(time.time())
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            """SELECT task_id,phase FROM web_generation_tasks
               WHERE status='pending' AND lease_until_epoch<=?
               ORDER BY created_at_epoch ASC LIMIT ?""",
            (now, _TASK_BATCH),
        )).fetchall()
    processed = []
    for task_id, phase in rows:
        next_phase = "submitting" if phase == "queued" else (
            "checking" if phase in ("provider", "checking") else str(phase)
        )
        lease = now + (
            _seconds("WEB_GENERATION_PROVIDER_SUBMIT_TIMEOUT_SECONDS",
                     _SUBMIT_TIMEOUT_SECONDS, 120, 3600)
            if next_phase == "submitting" else _POLL_LEASE_SECONDS
        )
        async with db_backend.connect() as db:
            cursor = await db.execute(
                """UPDATE web_generation_tasks SET phase=?,lease_until_epoch=?,
                   attempt_count=attempt_count+1,updated_at_epoch=?
                   WHERE task_id=? AND phase=? AND status='pending'
                   AND lease_until_epoch<=?""",
                (next_phase, lease, now, task_id, phase, now),
            )
            await db.commit()
            claimed = cursor.rowcount
        if not claimed:
            continue
        row = await _task_row(task_id)
        try:
            await _process_task(row, claimed_from=str(phase))
        except Exception:
            logger.exception("web_task_worker_error task=%s phase=%s", task_id, next_phase)
            # Lease expiry makes this record recoverable without duplicate provider submission.
        processed.append(task_id)
    return processed


async def run_generation_worker() -> None:
    """One loop per worker process; SQL compare-and-swap supports many replicas."""
    await asyncio.sleep(2)
    while True:
        try:
            await run_worker_tick()
        except Exception:
            logger.exception("web_generation_tick_failed")
        await asyncio.sleep(_seconds("WEB_GENERATION_WORKER_INTERVAL_SECONDS", 8, 3, 60))
