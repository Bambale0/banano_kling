"""Full-stack Seedance 2.5 runtime for the experimental feature branch.

This layer intentionally avoids changing the established generic Mini App and
Kie webhook flows. It patches only the Seedance 2.5 seams:

* admin-only Mini App bootstrap metadata and generation launch;
* dedicated Kie callback capable of video + returned last frame and MOV;
* polling reconciliation if the callback is delayed/lost;
* real ffprobe validation for Telegram video/audio references;
* support for advanced ``asset://`` inputs for admin testing.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, FSInputFile
from PIL import Image

from bot import db as db_backend
from bot.config import config
from bot.services.kie_market_service import kie_market_service
from bot.services.kie_webhook_verification import serialize_kie_callback
from bot.services.delivery_state import (
    TERMINAL_TASK_DELIVERY_STATUSES,
    is_terminal_telegram_delivery_error,
    terminal_telegram_delivery_reason,
)
from bot.services.media_input_utils import resolve_local_upload_path
from bot.services.preset_manager import preset_manager
from bot.services.seedance_25_service import (
    get_seedance25_callback_url,
    seedance_25_service,
)

from . import generation as generation_module
from . import seedance_25_preview as preview_module

logger = logging.getLogger(__name__)
router = Router(name="seedance_25_fullstack")

MODEL_KEY = "seedance_2_5"
MODEL_LABEL = "Seedance 2.5"

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif"}
VIDEO_EXTS = {"mp4", "mov"}
AUDIO_EXTS = {"wav", "mp3"}

MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MIN_SIDE = 300
MAX_SIDE = 6000
MIN_RATIO = 0.4
MAX_RATIO = 2.5
MIN_VIDEO_PIXELS = 640 * 640
MAX_VIDEO_PIXELS = 834 * 1112
MIN_MEDIA_DURATION = 2.0
MAX_MEDIA_DURATION = 30.0
MAX_TOTAL_VIDEO_DURATION = 30.0
MIN_FPS = 24.0
MAX_FPS = 60.0

SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS = max(
    1, int(os.getenv("SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS", "2"))
)
SEEDANCE25_RESULT_DOWNLOAD_TIMEOUT_SECONDS = max(
    30, int(os.getenv("SEEDANCE25_RESULT_DOWNLOAD_TIMEOUT_SECONDS", "120"))
)
SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS = max(
    0.0, float(os.getenv("SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS", "1"))
)
SEEDANCE25_DELIVERY_TIMEOUT_SECONDS = max(30, int(os.getenv("SEEDANCE25_DELIVERY_TIMEOUT_SECONDS", "360")))
SEEDANCE25_DELIVERY_RETRY_DAYS = max(1, min(30, int(os.getenv("SEEDANCE25_DELIVERY_RETRY_DAYS", "7"))))
SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS = max(
    30, int(os.getenv("SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS", "300"))
)


_RECONCILE_TASK_KEY = "seedance25_reconcile_task"


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and config.is_admin(int(user_id)))


def _clean_urls(values: Iterable[Any] | None, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    if limit is not None and len(result) > limit:
        raise ValueError(f"Слишком много референсов: максимум {limit}")
    return result


def _is_provider_source(value: str) -> bool:
    candidate = str(value or "").strip()
    return candidate.startswith("asset://") or candidate.startswith(("https://", "http://"))


def _validate_provider_sources(values: Iterable[str]) -> None:
    for value in values:
        if not _is_provider_source(value):
            raise ValueError(f"Некорректный URL/asset: {value[:120]}")


def _extension_from_url(value: str) -> str:
    path = urlsplit(str(value or "")).path
    return Path(path).suffix.lower().lstrip(".")


def _float_fraction(value: Any) -> float:
    text = str(value or "0").strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0


async def _ffprobe(path: str) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name,size:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration",
        "-of",
        "json",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError(
            "Не удалось прочитать медиа через ffprobe: "
            + stderr.decode("utf-8", errors="ignore")[:300]
        )
    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe вернул некорректные метаданные") from exc


def _probe_duration(meta: dict[str, Any], kind: str) -> float:
    streams = meta.get("streams") or []
    for stream in streams:
        if str(stream.get("codec_type") or "") == kind:
            try:
                duration = float(stream.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
    try:
        return float((meta.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _probe_video_stream(meta: dict[str, Any]) -> dict[str, Any]:
    for stream in meta.get("streams") or []:
        if str(stream.get("codec_type") or "") == "video":
            return stream
    raise ValueError("Видео-поток не найден")


def _validate_dimensions(width: int, height: int, *, video: bool) -> None:
    if width < MIN_SIDE or height < MIN_SIDE or width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError("Размеры должны быть 300–6000 px по каждой стороне")
    ratio = width / height
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        raise ValueError("Соотношение сторон должно быть в диапазоне 0.4–2.5")
    if video:
        pixels = width * height
        if not MIN_VIDEO_PIXELS <= pixels <= MAX_VIDEO_PIXELS:
            raise ValueError(
                f"Видео содержит {pixels} пикселей на кадр; допустимо {MIN_VIDEO_PIXELS}–{MAX_VIDEO_PIXELS}"
            )


def _validate_image_path(path: str) -> None:
    size = os.path.getsize(path)
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Изображение должно быть меньше 30 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext and ext not in IMAGE_EXTS:
        raise ValueError("Формат изображения: jpeg/png/webp/bmp/tiff/gif")
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:
        raise ValueError("Не удалось прочитать изображение") from exc
    _validate_dimensions(int(width), int(height), video=False)


async def _validate_video_path(path: str) -> float:
    if os.path.getsize(path) > MAX_VIDEO_BYTES:
        raise ValueError("Видео-референс не должен превышать 200 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in VIDEO_EXTS:
        raise ValueError("Видео-референс должен быть MP4 или MOV")

    meta = await _ffprobe(path)
    stream = _probe_video_stream(meta)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    _validate_dimensions(width, height, video=True)

    fps = _float_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if not MIN_FPS <= fps <= MAX_FPS:
        raise ValueError(f"FPS видео должен быть 24–60; получено {fps:g}")

    duration = _probe_duration(meta, "video")
    if not MIN_MEDIA_DURATION <= duration <= MAX_MEDIA_DURATION:
        raise ValueError(f"Длительность видео должна быть 2–30 секунд; получено {duration:.2f}")
    return duration


async def _validate_audio_path(path: str) -> float:
    if os.path.getsize(path) > MAX_AUDIO_BYTES:
        raise ValueError("Аудио-референс не должен превышать 15 MB")
    ext = Path(path).suffix.lower().lstrip(".")
    if ext not in AUDIO_EXTS:
        raise ValueError("Аудио-референс должен быть WAV или MP3")
    meta = await _ffprobe(path)
    duration = _probe_duration(meta, "audio")
    if not MIN_MEDIA_DURATION <= duration <= MAX_MEDIA_DURATION:
        raise ValueError(f"Длительность аудио должна быть 2–30 секунд; получено {duration:.2f}")
    return duration


async def _validate_local_source(source: str, kind: str) -> float | None:
    path = resolve_local_upload_path(source)
    if not path:
        return None
    if kind == "image":
        _validate_image_path(path)
        return None
    if kind == "video":
        return await _validate_video_path(path)
    if kind == "audio":
        return await _validate_audio_path(path)
    raise ValueError(f"Unknown media kind: {kind}")


async def _validate_seedance_sources(
    *,
    first_frame_url: str | None,
    last_frame_url: str | None,
    image_urls: list[str],
    video_urls: list[str],
    audio_urls: list[str],
) -> None:
    all_sources = [
        *([first_frame_url] if first_frame_url else []),
        *([last_frame_url] if last_frame_url else []),
        *image_urls,
        *video_urls,
        *audio_urls,
    ]
    _validate_provider_sources(all_sources)

    if first_frame_url:
        await _validate_local_source(first_frame_url, "image")
    if last_frame_url:
        await _validate_local_source(last_frame_url, "image")
    for source in image_urls:
        await _validate_local_source(source, "image")

    local_video_duration = 0.0
    for source in video_urls:
        duration = await _validate_local_source(source, "video")
        if duration:
            local_video_duration += duration
    if local_video_duration > MAX_TOTAL_VIDEO_DURATION + 0.01:
        raise ValueError(
            f"Суммарная длительность видео-референсов — максимум 30 секунд; получено {local_video_duration:.2f}"
        )

    for source in audio_urls:
        await _validate_local_source(source, "audio")


def _seedance25_model_meta() -> dict[str, Any]:
    durations = [-1, *range(4, 31)]
    quality_costs = preset_manager.get_video_quality_costs(MODEL_KEY)
    return {
        "id": MODEL_KEY,
        "label": "🧪 Seedance 2.5 (admin)",
        "description": "Полный admin-preview Bytedance: first/last frame, мультимодальные фото/видео/аудио референсы, audio generation и web search",
        "durations": durations,
        "ratios": ["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
        "supports": ["text", "imgtxt", "video"],
        "costs": {
            str(duration): preset_manager.get_video_cost_with_quality(
                MODEL_KEY,
                5 if duration == -1 else duration,
                "720p",
            )
            for duration in durations
        },
        "quality_costs": quality_costs,
        "seedance25_resolutions": ["480p", "720p"],
        "seedance25_output_formats": ["mp4", "mov"],
        "seedance25_scenarios": ["text", "first_frame", "first_last", "multimodal"],
        "supports_generate_audio": True,
        "supports_return_last_frame": True,
        "supports_web_search": True,
        "supports_nsfw_checker": True,
        "supports_auto_duration": True,
        "camera_control_via_prompt": True,
        "max_image_references": 30,
        "max_video_references": 10,
        "max_audio_references": 10,
        "admin_only": True,
    }


def _json_response_payload(response: web.StreamResponse) -> dict[str, Any] | None:
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None


async def _miniapp_seedance25_generate(request: web.Request, body: dict[str, Any]) -> web.Response:
    miniapp_module = __import__("bot.miniapp", fromlist=["*"])
    telegram_id, ctx = await miniapp_module._get_user_context(
        request.app,
        str(body.get("init_data") or ""),
        body.get("start_param_fallback"),
    )
    if not _is_admin(telegram_id):
        return web.json_response(
            {"ok": False, "error": "Seedance 2.5 сейчас доступна только администраторам"},
            status=403,
        )

    user = ctx["user"]
    video_editing = body.get("seedance25_video_editing", False)
    if not isinstance(video_editing, bool):
        return web.json_response({"ok": False, "error": "Некорректный режим редактирования видео"}, status=400)
    if video_editing and not config.is_admin(telegram_id):
        # Public installation rewrites _is_admin into a feature-access check.
        # Editing privileges must still use the real administrator check.
        return web.json_response({"ok": False, "error": "Редактирование видео пока доступно только администратору"}, status=400)
    prompt = str(body.get("prompt") or "").strip()
    scenario = str(body.get("seedance25_scenario") or "text").strip().lower()
    if scenario not in {"text", "first_frame", "first_last", "multimodal"}:
        return web.json_response({"ok": False, "error": "Некорректный сценарий Seedance 2.5"}, status=400)

    try:
        duration = int(body.get("v_duration", 5))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Некорректная длительность"}, status=400)

    ratio = str(body.get("v_ratio") or "adaptive").strip().lower()
    resolution = str(body.get("seedance25_resolution") or "720p").strip().lower()
    output_format = str(body.get("seedance25_output_format") or "mp4").strip().lower()
    generate_audio = bool(body.get("seedance25_generate_audio", True))
    return_last_frame = bool(body.get("seedance25_return_last_frame", False))
    web_search = bool(body.get("seedance25_web_search", False))
    nsfw_checker = bool(body.get("seedance25_nsfw_checker", False))

    first_frame = str(body.get("seedance25_first_frame_url") or "").strip() or None
    last_frame = str(body.get("seedance25_last_frame_url") or "").strip() or None
    try:
        image_urls = _clean_urls(body.get("reference_images") or [], 30)
        video_urls = _clean_urls(body.get("v_reference_videos") or [], 10)
        audio_urls = _clean_urls(body.get("seedance25_reference_audio_urls") or [], 10)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    # Scenario itself is the authoritative source of media routing.
    if scenario == "text":
        first_frame = last_frame = None
        image_urls = []
        video_urls = []
        audio_urls = []
        if not prompt:
            return web.json_response({"ok": False, "error": "Для Text-to-Video нужен промпт"}, status=400)
    elif scenario == "first_frame":
        last_frame = None
        image_urls = []
        video_urls = []
        audio_urls = []
        if not first_frame:
            return web.json_response({"ok": False, "error": "Загрузите первый кадр"}, status=400)
    elif scenario == "first_last":
        image_urls = []
        video_urls = []
        audio_urls = []
        if not first_frame or not last_frame:
            return web.json_response({"ok": False, "error": "Загрузите первый и последний кадры"}, status=400)
    else:
        first_frame = last_frame = None
        if not (image_urls or video_urls or audio_urls):
            return web.json_response({"ok": False, "error": "Добавьте хотя бы один мультимодальный референс"}, status=400)

    try:
        if video_editing:
            # Editing entitlement is checked above and by the public wrapper.
            if scenario != "multimodal" or len(video_urls) != 1:
                raise ValueError("Для редактирования выберите режим по референсам и одно исходное видео 4–30 секунд")
            source_duration = await _validate_local_source(video_urls[0], "video")
            if source_duration is not None and not 4 <= source_duration <= 30:
                raise ValueError("Для редактирования исходное видео должно быть 4–30 секунд")
            duration = -1
            ratio = "adaptive"
        await _validate_seedance_sources(
            first_frame_url=first_frame,
            last_frame_url=last_frame,
            image_urls=image_urls,
            video_urls=video_urls,
            audio_urls=audio_urls,
        )
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    # Keep saved-reference freshness consistent with the established Mini App.
    try:
        if first_frame:
            await miniapp_module.touch_saved_references(telegram_id, [first_frame], kind="image")
        if last_frame:
            await miniapp_module.touch_saved_references(telegram_id, [last_frame], kind="image")
        if image_urls:
            await miniapp_module.touch_saved_references(telegram_id, image_urls, kind="image")
        if video_urls:
            await miniapp_module.touch_saved_references(telegram_id, video_urls, kind="video")
        if audio_urls:
            await miniapp_module.touch_saved_references(telegram_id, audio_urls, kind="audio")
    except Exception:
        logger.exception("Seedance 2.5: failed to touch saved references")

    pricing_duration = 5 if duration == -1 else duration
    quote = preset_manager.get_video_cost_with_quality(
        MODEL_KEY,
        pricing_duration,
        resolution,
    )

    result = await seedance_25_service.generate_video(
        prompt=prompt,
        duration=duration,
        aspect_ratio=ratio,
        resolution=resolution,
        first_frame_url=first_frame,
        last_frame_url=last_frame,
        reference_image_urls=image_urls or None,
        reference_video_urls=video_urls or None,
        reference_audio_urls=audio_urls or None,
        return_last_frame=return_last_frame,
        generate_audio=generate_audio,
        output_format=output_format,
        web_search=web_search,
        nsfw_checker=nsfw_checker,
        callBackUrl=get_seedance25_callback_url(),
        **({"video_editing": True} if video_editing else {}),
    )
    if not result or not result.get("task_id"):
        error = result.get("error") if isinstance(result, dict) else "provider response has no task_id"
        return web.json_response({"ok": False, "error": str(error)}, status=502)

    task_id = str(result["task_id"])
    await generation_module.add_generation_task(
        user.id,
        telegram_id,
        task_id,
        "video",
        "no_preset_video",
        model=MODEL_KEY,
        duration=duration,
        aspect_ratio=ratio,
        prompt=prompt,
        cost=0.0,
        request_data={
            "source": "miniapp",
            "preview": "seedance_2_5_admin",
            "v_model": MODEL_KEY,
            "v_type": "text" if scenario == "text" else "imgtxt" if scenario in {"first_frame", "first_last"} else "video",
            "seedance25_scenario": scenario,
            "seedance25_video_editing": video_editing,
            "duration": duration,
            "aspect_ratio": ratio,
            "first_frame_url": first_frame,
            "last_frame_url": last_frame,
            "reference_images": image_urls,
            "v_reference_videos": video_urls,
            "reference_audios": audio_urls,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
            "output_format": output_format,
            "web_search": web_search,
            "nsfw_checker": nsfw_checker,
            "price_quote": float(quote),
            "admin_price_quote": float(quote),
            "charged": False,
            "charged_cost": 0.0,
            "admin_free": True,
            "refund_on_failure": False,
            "refund_claimed": False,
            "provider_model": seedance_25_service.MODEL_NAME,
            "callback_url": get_seedance25_callback_url(),
        },
    )

    return web.json_response(
        {
            "ok": True,
            "status": "queued",
            "task_id": task_id,
            "credits": user.credits,
            "cost": quote,
            "model_label": MODEL_LABEL,
            "admin_free": True,
            "resolution": resolution,
            "duration": duration,
            "aspect_ratio": ratio,
            "scenario": scenario,
        }
    )


def _extract_result_urls(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    result_json = data.get("resultJson") if isinstance(data, dict) else None
    parsed: Any = result_json
    if isinstance(result_json, str):
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError:
            parsed = None

    urls: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, str):
            candidate = value.strip()
            if candidate.startswith(("https://", "http://")) and candidate not in urls:
                urls.append(candidate)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key)
            return
        if isinstance(value, dict):
            preferred = (
                "resultUrls",
                "result_urls",
                "videoUrl",
                "video_url",
                "url",
                "lastFrameUrl",
                "last_frame_url",
                "lastFrame",
            )
            for name in preferred:
                if name in value:
                    visit(value.get(name), name)
            for name, item in value.items():
                if name not in preferred:
                    visit(item, name)

    if parsed is not None:
        visit(parsed)
    if isinstance(data, dict):
        for key in ("resultUrls", "result_urls", "videoUrl", "video_url", "lastFrameUrl", "last_frame_url"):
            visit(data.get(key), key)
    return urls


def _classify_results(urls: list[str], request_data: dict[str, Any]) -> tuple[str | None, str | None]:
    if not urls:
        return None, None
    output_format = str(request_data.get("output_format") or "mp4").lower()
    return_last = bool(request_data.get("return_last_frame"))

    video_url = next((u for u in urls if _extension_from_url(u) in {output_format, *VIDEO_EXTS}), None)
    image_url = next((u for u in urls if _extension_from_url(u) in IMAGE_EXTS), None)
    if video_url is None:
        video_url = urls[0]
    if return_last and image_url is None and len(urls) > 1:
        image_url = next((u for u in urls if u != video_url), urls[1])
    return video_url, image_url


async def _download_to_temp(url: str, suffix: str, max_bytes: int = 50 * 1024 * 1024) -> str | None:
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}

    for attempt in range(1, SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS + 1):
        tmp_path: str | None = None
        try:
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
            ) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(
                        total=SEEDANCE25_RESULT_DOWNLOAD_TIMEOUT_SECONDS
                    ),
                ) as resp:
                    if resp.status != 200:
                        if (
                            resp.status in retryable_statuses
                            and attempt < SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS
                        ):
                            logger.warning(
                                "Seedance 2.5 result download HTTP %s; retrying attempt=%s/%s",
                                resp.status,
                                attempt + 1,
                                SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS,
                            )
                            if SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS:
                                await asyncio.sleep(
                                    SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS
                                    * attempt
                                )
                            continue
                        return None
                    if resp.content_length and resp.content_length > max_bytes:
                        return None

                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp_path = tmp.name
                    downloaded = 0
                    try:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                raise ValueError("result too large")
                            tmp.write(chunk)
                    finally:
                        tmp.close()
            return tmp_path
        except asyncio.CancelledError:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            if attempt < SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS:
                logger.warning(
                    "Seedance 2.5 result download transient failure; retrying attempt=%s/%s",
                    attempt + 1,
                    SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS,
                    exc_info=True,
                )
                if SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS:
                    await asyncio.sleep(
                        SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS * attempt
                    )
                continue
            logger.exception(
                "Seedance 2.5 result download failed after %s attempts: %s",
                attempt,
                url,
            )
            return None
        except Exception:
            logger.exception("Seedance 2.5 result download failed: %s", url)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return None

    return None


async def _send_seedance25_results(
    app: web.Application,
    telegram_id: int,
    task_id: str,
    video_url: str,
    last_frame_url: str | None,
    request_data: dict[str, Any],
) -> bool:
    bot = app["bot"]
    output_format = str(request_data.get("output_format") or _extension_from_url(video_url) or "mp4").lower()
    resolution = str(request_data.get("resolution") or "720p")
    duration = request_data.get("duration") or request_data.get("v_duration")
    scenario = str(request_data.get("seedance25_scenario") or "text")
    caption = (
        "✅ <b>Seedance 2.5 готово</b>\n"
        f"• ID задачи: <code>{task_id}</code>\n"
        f"• Сценарий: <code>{scenario}</code>\n"
        f"• Качество: <code>{resolution}</code>\n"
        f"• Формат: <code>{output_format.upper()}</code>"
    )
    if duration is not None:
        caption += f"\n• Длительность: <code>{'Auto' if int(duration) == -1 else str(duration) + 'с'}</code>"
    caption += "\n• Admin preview: <code>без списания</code>"
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
            await bot.send_video(
                telegram_id,
                video=video_url,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                reply_markup=result_markup,
            )
            delivered = True
        except Exception as exc:
            if is_terminal_telegram_delivery_error(exc):
                raise
            logger.info("Seedance 2.5 URL video delivery failed; trying file upload")

    if not delivered:
        tmp_path = await _download_to_temp(video_url, suffix=suffix)
        if tmp_path:
            try:
                if output_format == "mp4":
                    await bot.send_video(
                        telegram_id,
                        video=FSInputFile(tmp_path),
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        reply_markup=result_markup,
                    )
                else:
                    await bot.send_document(
                        telegram_id,
                        document=FSInputFile(tmp_path, filename=f"seedance25-{task_id}.mov"),
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=result_markup,
                    )
                delivered = True
            except Exception as exc:
                if is_terminal_telegram_delivery_error(exc):
                    raise
                logger.exception("Seedance 2.5 file delivery failed for task %s", task_id)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if not delivered and not request_data.get("delivery_link_sent"):
        try:
            await bot.send_message(
                telegram_id,
                caption + f"\n\n🔗 Оригинал:\n{video_url}",
                parse_mode="HTML",
                disable_web_page_preview=False,
                reply_markup=result_markup,
            )
            await _mark_seedance25_delivery(task_id, "link_sent")
        except Exception as exc:
            if is_terminal_telegram_delivery_error(exc):
                raise
            logger.exception("Seedance 2.5 result notification failed")

    if last_frame_url:
        frame_caption = f"🖼 <b>Последний кадр Seedance 2.5</b>\nID: <code>{task_id}</code>"
        try:
            await bot.send_photo(
                telegram_id,
                photo=last_frame_url,
                caption=frame_caption,
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
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(last_frame_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            raw = await resp.read()
                            await bot.send_photo(
                                telegram_id,
                                photo=BufferedInputFile(raw, filename=f"seedance25-{task_id}-last-frame.png"),
                                caption=frame_caption,
                                parse_mode="HTML",
                            )
                            return delivered
                await bot.send_message(telegram_id, frame_caption + f"\n{last_frame_url}", parse_mode="HTML")
            except Exception as exc:
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
                    logger.exception("Seedance 2.5 last-frame delivery failed")

    return delivered


def _is_seedance25_copyright_failure(code: int | str | None, fail_msg: str | None) -> bool:
    text = str(fail_msg or "").strip().lower()
    if not text:
        return False
    markers = (
        "copyright",
        "intellectual property",
        "copyright restrictions",
        "copyright restriction",
    )
    return any(marker in text for marker in markers)


def _is_seedance25_editing_parameter_failure(fail_msg: str | None) -> bool:
    text = str(fail_msg or "").strip().lower()
    return (
        "video editing" in text
        and "duration" in text
        and "must be -1" in text
    )


def _seedance25_task_aliases(request_data: dict[str, Any], *task_ids: str) -> list[str]:
    raw_aliases = request_data.get("task_id_aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    aliases: list[str] = []
    for value in [*raw_aliases, *task_ids]:
        normalized = str(value or "").strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def _seedance25_request_urls(request_data: dict[str, Any], key: str) -> list[str]:
    raw = request_data.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return _clean_urls(raw)


async def _release_seedance25_edit_retry_claim(
    task_id: str,
    claimed_json: str,
    claimed_data: dict[str, Any],
    *,
    error: str,
    orphan_task_id: str | None = None,
) -> None:
    failed_data = dict(claimed_data)
    failed_data["seedance25_edit_auto_retry_state"] = "create_failed"
    failed_data["seedance25_edit_auto_retry_error"] = str(error or "provider retry failed")[:300]
    if orphan_task_id:
        failed_data["seedance25_edit_auto_retry_orphan_task_id"] = orphan_task_id
    failed_json = json.dumps(failed_data, ensure_ascii=False, separators=(",", ":"))
    async with db_backend.connect() as db:
        await db.execute(
            """
            UPDATE generation_tasks
            SET request_data = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'pending' AND request_data = ?
            """,
            (failed_json, task_id, claimed_json),
        )
        await db.commit()


async def _auto_retry_seedance25_video_editing(
    task_id: str,
    fail_msg: str | None,
) -> bool:
    """Retry one provider-reclassified edit before failure/refund processing.

    Returns ``True`` when the failure is already handled by a queued or active
    retry. ``False`` lets the normal failure and refund path continue.
    """
    if not _is_seedance25_editing_parameter_failure(fail_msg):
        return False

    row = await _load_task_row(task_id)
    if not row:
        return False
    row_data = dict(row)
    if str(row_data.get("status") or "").lower() != "pending":
        return False
    if str(row_data.get("model") or "").strip() != MODEL_KEY:
        return False
    if str(row_data.get("type") or "").strip().lower() != "video":
        return False

    old_json = str(row_data.get("request_data") or "{}")
    try:
        request_data = json.loads(old_json)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(request_data, dict):
        return False
    # Public editing remains disabled because its output duration follows the
    # source video while retail pricing is quoted from the selected duration.
    # Do not silently change a paid user's contract or create an unpriced task.
    if request_data.get("seedance25_identity_transfer") is True:
        return False
    if request_data.get("admin_free") is not True:
        return False

    retry_state = str(request_data.get("seedance25_edit_auto_retry_state") or "").lower()
    if retry_state == "creating":
        try:
            claim_age = time.time() - float(
                request_data.get("seedance25_edit_auto_retry_claimed_at") or 0
            )
        except (TypeError, ValueError):
            claim_age = SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS + 1
        if 0 <= claim_age <= SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS:
            logger.info(
                "Seedance 2.5 edit fallback already in progress: task_id=%s",
                task_id,
            )
            return True
        logger.error(
            "Seedance 2.5 edit fallback claim expired: task_id=%s age=%.1fs",
            task_id,
            claim_age,
        )
        return False

    editing_flag = request_data.get("seedance25_video_editing")
    if editing_flag is not None and editing_flag is not False:
        return False
    try:
        retry_attempt = int(request_data.get("seedance25_edit_auto_retry_attempt") or 0)
    except (TypeError, ValueError):
        retry_attempt = 1
    if retry_attempt >= 1:
        return False
    scenario = str(
        request_data.get("seedance25_scenario")
        or request_data.get("scenario")
        or ""
    ).lower()
    if scenario != "multimodal":
        return False

    video_urls = _seedance25_request_urls(request_data, "v_reference_videos")
    if not video_urls:
        video_urls = _seedance25_request_urls(request_data, "reference_videos")
    if len(video_urls) != 1:
        return False
    try:
        source_duration = await _validate_local_source(video_urls[0], "video")
    except ValueError as exc:
        logger.warning(
            "Seedance 2.5 edit fallback rejected invalid source: task_id=%s reason=%s",
            task_id,
            exc,
        )
        return False
    if source_duration is not None and not 4 <= source_duration <= 30:
        logger.warning(
            "Seedance 2.5 edit fallback rejected source duration: "
            "task_id=%s duration=%.3f",
            task_id,
            source_duration,
        )
        return False
    image_urls = _seedance25_request_urls(request_data, "reference_images")
    audio_urls = _seedance25_request_urls(request_data, "reference_audios")
    prompt = str(row_data.get("prompt") or request_data.get("prompt") or "").strip()
    if not prompt:
        return False

    claimed_data = dict(request_data)
    claimed_data.update(
        seedance25_edit_auto_retry_attempt=1,
        seedance25_edit_auto_retry_state="creating",
        seedance25_edit_auto_retry_claimed_at=time.time(),
        seedance25_edit_auto_retry_from_task_id=task_id,
        seedance25_edit_auto_retry_trigger="provider_video_editing_parameters",
    )
    if source_duration is not None:
        claimed_data["seedance25_edit_source_duration"] = round(source_duration, 3)
    claimed_json = json.dumps(claimed_data, ensure_ascii=False, separators=(",", ":"))
    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET request_data = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'pending' AND request_data = ?
            """,
            (claimed_json, task_id, old_json),
        )
        await db.commit()
    if int(getattr(cursor, "rowcount", 0) or 0) != 1:
        refreshed = await _load_task_row(task_id)
        if refreshed:
            try:
                current_data = json.loads(refreshed["request_data"] or "{}")
            except (TypeError, json.JSONDecodeError):
                current_data = {}
            if str(current_data.get("seedance25_edit_auto_retry_state") or "").lower() == "creating":
                return True
        from bot.database import get_task_by_id

        current = await get_task_by_id(task_id)
        return bool(
            current
            and current.task_id != task_id
            and current.status in {"pending", "processing"}
        )

    try:
        result = await seedance_25_service.generate_video(
            prompt=prompt,
            duration=-1,
            aspect_ratio="adaptive",
            resolution=str(request_data.get("resolution") or "720p"),
            first_frame_url=(
                str(request_data.get("first_frame_url") or "").strip() or None
            ),
            last_frame_url=(
                str(request_data.get("last_frame_url") or "").strip() or None
            ),
            reference_image_urls=image_urls or None,
            reference_video_urls=video_urls,
            reference_audio_urls=audio_urls or None,
            video_editing=True,
            return_last_frame=bool(request_data.get("return_last_frame")),
            generate_audio=bool(request_data.get("generate_audio", True)),
            output_format=str(request_data.get("output_format") or "mp4"),
            web_search=bool(request_data.get("web_search")),
            nsfw_checker=bool(request_data.get("nsfw_checker")),
            callBackUrl=(
                str(request_data.get("callback_url") or "").strip()
                or get_seedance25_callback_url()
            ),
        )
    except Exception as exc:
        logger.exception(
            "Seedance 2.5 edit fallback provider launch crashed: task_id=%s",
            task_id,
        )
        await _release_seedance25_edit_retry_claim(
            task_id,
            claimed_json,
            claimed_data,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False

    new_task_id = str((result or {}).get("task_id") or "").strip() if isinstance(result, dict) else ""
    if not new_task_id or new_task_id == task_id:
        error = (result or {}).get("error") if isinstance(result, dict) else "provider response has no task_id"
        await _release_seedance25_edit_retry_claim(
            task_id,
            claimed_json,
            claimed_data,
            error=str(error or "provider response has no new task_id"),
        )
        return False

    retry_data = dict(claimed_data)
    retry_data.update(
        seedance25_video_editing=True,
        seedance25_edit_auto_retry_state="queued",
        seedance25_edit_auto_retry_provider_task_id=new_task_id,
        requested_duration_before_auto_retry=(
            request_data.get("duration")
            if request_data.get("duration") is not None
            else row_data.get("duration")
        ),
        requested_aspect_ratio_before_auto_retry=(
            request_data.get("aspect_ratio")
            or row_data.get("aspect_ratio")
        ),
        duration=-1,
        aspect_ratio="adaptive",
        v_duration=-1,
        v_ratio="adaptive",
        provider_task_id=new_task_id,
        last_auto_retry_from_task_id=task_id,
    )
    retry_data["task_id_aliases"] = _seedance25_task_aliases(
        request_data,
        task_id,
        new_task_id,
    )
    retry_json = json.dumps(retry_data, ensure_ascii=False, separators=(",", ":"))

    async with db_backend.connect() as db:
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET task_id = ?,
                duration = -1,
                aspect_ratio = 'adaptive',
                request_data = ?,
                status = 'pending',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'pending' AND request_data = ?
            """,
            (new_task_id, retry_json, task_id, claimed_json),
        )
        await db.commit()
    if int(getattr(cursor, "rowcount", 0) or 0) != 1:
        logger.critical(
            "Seedance 2.5 edit fallback could not attach provider task: "
            "old_task_id=%s new_task_id=%s",
            task_id,
            new_task_id,
        )
        await _release_seedance25_edit_retry_claim(
            task_id,
            claimed_json,
            claimed_data,
            error="database compare-and-swap failed after provider task creation",
            orphan_task_id=new_task_id,
        )
        return False

    logger.warning(
        "Seedance 2.5 auto-retried provider-classified edit: "
        "old_task_id=%s new_task_id=%s duration=-1 ratio=adaptive",
        task_id,
        new_task_id,
    )
    return True


def _seedance25_failure_text(
    task_id: str,
    *,
    code: int | str | None,
    fail_msg: str,
    request_data: dict[str, Any],
) -> str:
    if _is_seedance25_copyright_failure(code, fail_msg):
        reason = (
            "KIE/ByteDance отклонил один из исходных материалов из-за "
            "ограничений авторских прав. Попробуйте другой референс или исходник."
        )
    else:
        reason = str(fail_msg or "ошибка провайдера").strip()[:600]

    error_text = str(fail_msg or "").lower()
    editing_hint = ""
    if all(part in error_text for part in ("video editing", "duration", "must be -1")):
        editing_hint = (
            "\n\nПровайдер определил задачу как редактирование видео. "
            "Выберите режим «Редактировать видео» и одно исходное видео 4–30 секунд; "
            "длительность и формат кадра сохраняются из исходника. "
            "Этот режим пока доступен администратору."
        )

    if request_data.get("admin_free"):
        billing = "Списаний не было."
    elif request_data.get("refund_claimed"):
        billing = "🍌 Списание возвращено автоматически."
    else:
        billing = "🍌 Если списание прошло, возврат будет выполнен автоматически."

    return (
        "❌ <b>Seedance 2.5 не завершилась</b>\n"
        f"ID: <code>{html.escape(task_id)}</code>\n"
        f"Причина: {html.escape(reason)}{editing_hint}\n\n"
        f"{billing}"
    )


async def _load_task_row(task_id: str):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            SELECT gt.*, u.telegram_id
            FROM generation_tasks gt
            JOIN users u ON u.id = gt.user_id
            WHERE gt.task_id = ?
            LIMIT 1
            """,
            (task_id,),
        )
        return await cursor.fetchone()


async def _persist_seedance25_ephemeral_results(
    video_url: str | None,
    urls: list[str],
) -> tuple[str | None, list[str]]:
    """Localize known short-lived Seedance result URLs before completion."""
    if not video_url:
        return video_url, urls

    candidates: list[str] = []
    for value in [video_url, *urls]:
        candidate = str(value or "").strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return video_url, urls

    from bot.database import FEED_EPHEMERAL_RESULT_HOSTS

    def is_ephemeral(value: str) -> bool:
        host = (urlsplit(value).hostname or "").strip().lower().lstrip(".")
        return any(
            host == expected or host.endswith(f".{expected}")
            for expected in FEED_EPHEMERAL_RESULT_HOSTS
        )

    if not any(is_ephemeral(value) for value in candidates):
        return video_url, urls

    from bot.services.feed_persist import persist_feed_result_urls

    persisted = await persist_feed_result_urls(candidates, require_local=True)
    if len(persisted) != len(candidates):
        raise RuntimeError("durable Seedance 2.5 result persistence failed")
    mapped = dict(zip(candidates, persisted))
    return mapped.get(video_url, video_url), [mapped.get(value, value) for value in urls]


async def _store_task_result(task_id: str, video_url: str | None, urls: list[str], *, success: bool) -> None:
    if success:
        video_url, urls = await _persist_seedance25_ephemeral_results(video_url, urls)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        cursor = await db.execute(
            """
            UPDATE generation_tasks
            SET result_url = ?,
                result_urls = ?,
                status = ?,
                completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status IN ('pending', 'processing')
            RETURNING request_data
            """,
            (
                video_url,
                json.dumps(urls, ensure_ascii=False),
                "completed" if success else "failed",
                "completed" if success else "failed",
                task_id,
            ),
        )
        claimed = await cursor.fetchone()
        if claimed and success:
            # The result and recovery marker commit together while the row is
            # locked. Legacy completed rows without markers are not replayed.
            try:
                metadata = json.loads(claimed["request_data"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            delivery_status = str(metadata.get("delivery_status") or "").lower()
            if delivery_status not in TERMINAL_TASK_DELIVERY_STATUSES:
                metadata["delivery_status"] = "result_ready"
            await db.execute(
                "UPDATE generation_tasks SET request_data = ? WHERE task_id = ?",
                (json.dumps(metadata, ensure_ascii=False), task_id),
            )
        await db.commit()


async def _mark_seedance25_delivery(
    task_id: str,
    status: str,
    *,
    error: str | None = None,
) -> None:
    from bot.database import mark_task_delivery_status

    await mark_task_delivery_status(task_id, status, error=error)


def _stored_result_urls(row) -> list[str]:
    raw = dict(row).get("result_urls")
    if isinstance(raw, list):
        urls = [str(item).strip() for item in raw if str(item).strip()]
    else:
        try:
            parsed = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            parsed = []
        urls = [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []
    result_url = str(row["result_url"] or "").strip()
    if result_url and result_url not in urls:
        urls.insert(0, result_url)
    return urls


async def _claim_seedance25_delivery(task_id: str) -> bool:
    from bot.database import claim_task_delivery

    return await claim_task_delivery(task_id, lease_seconds=SEEDANCE25_DELIVERY_TIMEOUT_SECONDS + 60)


async def _can_attempt_seedance25_result_delivery(
    app: web.Application,
    telegram_id: int,
) -> bool:
    from bot.database import can_attempt_telegram_delivery

    bot_instance = app.get("bot")
    probe = getattr(bot_instance, "get_chat", None)
    if probe is None:
        return await can_attempt_telegram_delivery(telegram_id)
    return await can_attempt_telegram_delivery(telegram_id, probe=probe)


async def _retry_seedance25_delivery(
    app: web.Application,
    row,
    request_data: dict[str, Any],
) -> bool:
    task_id = str(row["task_id"] or "").strip()
    telegram_id = int(row["telegram_id"])
    if not await _can_attempt_seedance25_result_delivery(app, telegram_id):
        await _mark_seedance25_delivery(
            task_id,
            "unavailable",
            error="chat_not_started",
        )
        return True
    if not await _claim_seedance25_delivery(task_id):
        return False

    urls = _stored_result_urls(row)
    video_url, last_frame_url = _classify_results(urls, request_data)
    if not video_url:
        await _mark_seedance25_delivery(
            task_id,
            "pending",
            error="completed Seedance 2.5 task has no stored video URL",
        )
        return False

    try:
        delivered = await asyncio.wait_for(_send_seedance25_results(
            app,
            telegram_id,
            task_id,
            video_url,
            last_frame_url if request_data.get("return_last_frame") else None,
            request_data,
        ), timeout=SEEDANCE25_DELIVERY_TIMEOUT_SECONDS)
    except Exception as exc:
        reason = terminal_telegram_delivery_reason(exc)
        if reason:
            logger.info(
                "Telegram delivery unavailable: event=seedance25_result reason=%s task_id=%s telegram_id=%s",
                reason,
                task_id,
                telegram_id,
            )
            await _mark_seedance25_delivery(
                task_id,
                "unavailable",
                error=reason,
            )
            return True
        logger.exception("Seedance 2.5 delivery attempt crashed for task %s", task_id)
        await _mark_seedance25_delivery(task_id, "pending", error=str(exc))
        return False

    if delivered:
        await _mark_seedance25_delivery(task_id, "delivered")
        return True

    await _mark_seedance25_delivery(
        task_id,
        "pending",
        error="Telegram/CDN delivery failed; reconciliation scheduled",
    )
    return False


async def _process_seedance25_payload(app: web.Application, payload: dict[str, Any]) -> bool:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    task_id = str((data or {}).get("taskId") or payload.get("taskId") or "").strip()
    if not task_id:
        return False

    row = await _load_task_row(task_id)
    if not row or str(row["model"] or "") != MODEL_KEY:
        return False

    try:
        request_data = json.loads(row["request_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        request_data = {}
    request_data.setdefault("duration", row["duration"])

    row_status = str(row["status"] or "").lower()
    if row_status == "failed":
        return True
    if row_status == "completed":
        delivery_status = str(request_data.get("delivery_status") or "").lower()
        if not delivery_status or delivery_status in TERMINAL_TASK_DELIVERY_STATUSES:
            return True
        await _retry_seedance25_delivery(app, row, request_data)
        return True

    state = str((data or {}).get("state") or payload.get("state") or "").lower()
    try:
        code = int(payload.get("code") or (data or {}).get("failCode") or 200)
    except (TypeError, ValueError):
        code = 200
    fail_code = (data or {}).get("failCode") or code
    fail_msg = str((data or {}).get("failMsg") or payload.get("msg") or "")
    telegram_id = int(row["telegram_id"])

    failure_codes = {"400", "501", "500", "422", "402", "429", "455", "505"}
    if (
        state in {"fail", "failed", "error"}
        or str(code) in failure_codes
        or str(fail_code) in failure_codes
    ):
        if not payload.get("_seedance25_edit_retry_checked"):
            try:
                if await _auto_retry_seedance25_video_editing(task_id, fail_msg):
                    return True
            except Exception:
                logger.exception(
                    "Seedance 2.5 edit fallback preflight failed: task_id=%s",
                    task_id,
                )
                return False
        await _store_task_result(task_id, None, [], success=False)
        from bot.database import can_attempt_telegram_delivery

        if not await can_attempt_telegram_delivery(telegram_id):
            await _mark_seedance25_delivery(
                task_id,
                "unavailable",
                error="chat_not_started",
            )
            logger.info(
                "Telegram delivery skipped: event=seedance25_failure reason=chat_not_started task_id=%s telegram_id=%s",
                task_id,
                telegram_id,
            )
            return True
        try:
            await app["bot"].send_message(
                telegram_id,
                _seedance25_failure_text(
                    task_id,
                    code=fail_code,
                    fail_msg=fail_msg,
                    request_data=request_data,
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            reason = terminal_telegram_delivery_reason(exc)
            if reason:
                logger.info(
                    "Telegram delivery unavailable: event=seedance25_failure reason=%s task_id=%s telegram_id=%s",
                    reason,
                    task_id,
                    telegram_id,
                )
                await _mark_seedance25_delivery(
                    task_id,
                    "unavailable",
                    error=reason,
                )
            else:
                logger.exception("Seedance 2.5 failure notification failed")
        return True

    if state not in {"success", "completed", "succeeded", "finished"}:
        return False

    urls = _extract_result_urls(payload)
    if not urls:
        return False
    video_url, _last_frame_url = _classify_results(urls, request_data)
    if not video_url:
        return False

    await _store_task_result(task_id, video_url, urls, success=True)

    if not await _can_attempt_seedance25_result_delivery(app, telegram_id):
        await _mark_seedance25_delivery(
            task_id,
            "unavailable",
            error="chat_not_started",
        )
        logger.info(
            "Seedance 2.5 result retained without Telegram delivery: task=%s telegram_id=%s",
            task_id,
            telegram_id,
        )
        return True
    refreshed = await _load_task_row(task_id)
    if not refreshed:
        return False
    try:
        refreshed_request = json.loads(refreshed["request_data"] or "{}")
    except (TypeError, json.JSONDecodeError):
        refreshed_request = dict(request_data)
    refreshed_request.setdefault("duration", refreshed["duration"])
    await _retry_seedance25_delivery(app, refreshed, refreshed_request)
    return True


@serialize_kie_callback
async def seedance25_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=200)

    from bot.services.kie_webhook_verification import canonical_kie_callback

    payload, verification_status = await canonical_kie_callback(payload)
    if payload is None:
        return web.Response(status=verification_status)

    try:
        await _process_seedance25_payload(request.app, payload)
    except Exception:
        logger.exception("Seedance 2.5 dedicated webhook failed")
        return web.Response(status=503)
    return web.Response(status=200)


async def _seedance25_reconcile_loop(app: web.Application) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            if db_backend.is_postgres():
                recent_completed_expr = (
                    f"COALESCE(completed_at, created_at) >= CURRENT_TIMESTAMP - INTERVAL '{SEEDANCE25_DELIVERY_RETRY_DAYS} days'"
                )
                delivery_state_expr = (
                    "CASE WHEN json_valid(request_data) "
                    "THEN request_data::jsonb ->> 'delivery_status' ELSE NULL END"
                )
            else:
                recent_completed_expr = (
                    f"COALESCE(completed_at, created_at) >= datetime(CURRENT_TIMESTAMP, '-{SEEDANCE25_DELIVERY_RETRY_DAYS} days')"
                )
                delivery_state_expr = (
                    "CASE WHEN json_valid(request_data) "
                    "THEN json_extract(request_data, '$.delivery_status') ELSE NULL END"
                )
            async with db_backend.connect() as db:
                db.row_factory = db_backend.Row
                cursor = await db.execute(
                    f"""
                    SELECT task_id, status, request_data
                    FROM generation_tasks
                    WHERE model = ?
                      AND (
                            status = 'pending'
                            OR (
                                status = 'completed'
                                AND result_url IS NOT NULL
                                AND {recent_completed_expr}
                                AND {delivery_state_expr}
                                    IN ('result_ready', 'pending', 'delivering', 'link_sent')
                            )
                      )
                    ORDER BY COALESCE(updated_at, created_at) ASC, id ASC
                    LIMIT 50
                    """,
                    (MODEL_KEY,),
                )
                rows = await cursor.fetchall()
            for row in rows:
                task_id = str(row["task_id"] or "")
                if not task_id:
                    continue
                status = str(row["status"] or "").lower()
                if status == "completed":
                    try:
                        request_data = json.loads(row["request_data"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        request_data = {}
                    if str(request_data.get("delivery_status") or "").lower() not in {
                        "result_ready",
                        "pending",
                        "delivering",
                        "link_sent",
                    }:
                        continue
                    await _process_seedance25_payload(
                        app,
                        {"code": 200, "data": {"taskId": task_id}},
                    )
                    continue

                task_data = await kie_market_service.get_task_status(task_id)
                if not task_data:
                    continue
                await _process_seedance25_payload(app, {"code": 200, "data": task_data})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Seedance 2.5 reconcile iteration failed")
        await asyncio.sleep(60)


async def _seedance25_startup(app: web.Application) -> None:
    if app.get(_RECONCILE_TASK_KEY):
        return
    app[_RECONCILE_TASK_KEY] = asyncio.create_task(_seedance25_reconcile_loop(app))


async def _seedance25_cleanup(app: web.Application) -> None:
    task = app.get(_RECONCILE_TASK_KEY)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def install_seedance_25_fullstack() -> None:
    """Patch Mini App setup/handlers before ``main`` imports the setup function."""
    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_seedance25_fullstack_installed", False):
        return

    original_bootstrap = miniapp_module.miniapp_bootstrap
    original_generate_video = miniapp_module.miniapp_generate_video
    original_setup = miniapp_module.setup_miniapp_routes

    async def bootstrap_with_seedance25(request: web.Request) -> web.Response:
        response = await original_bootstrap(request)
        if response.status != 200:
            return response
        payload = _json_response_payload(response)
        if not payload or not payload.get("is_admin"):
            return response
        models = list(payload.get("video_models") or [])
        if not any(str(item.get("id")) == MODEL_KEY for item in models if isinstance(item, dict)):
            models.append(_seedance25_model_meta())
        payload["video_models"] = models
        return web.json_response(payload)

    async def generate_video_with_seedance25(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return await original_generate_video(request)
        model = str(body.get("v_model") or "")
        if model != MODEL_KEY:
            return await original_generate_video(request)
        try:
            return await _miniapp_seedance25_generate(request, body)
        except Exception as exc:
            logger.exception("Mini App Seedance 2.5 generation failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    def setup_with_seedance25(app: web.Application):
        result = original_setup(app)
        app.router.add_post("/webhook/kie_seedance25", seedance25_webhook)
        app.on_startup.append(_seedance25_startup)
        app.on_cleanup.append(_seedance25_cleanup)
        return result

    miniapp_module.miniapp_bootstrap = bootstrap_with_seedance25
    miniapp_module.miniapp_generate_video = generate_video_with_seedance25
    miniapp_module.setup_miniapp_routes = setup_with_seedance25
    miniapp_module._seedance25_fullstack_installed = True


async def _download_telegram_bytes(message: types.Message, media) -> bytes:
    tg_file = await message.bot.get_file(media.file_id)
    downloaded = await message.bot.download_file(tg_file.file_path)
    return downloaded.read()


async def _validate_temp_bytes(raw: bytes, suffix: str, kind: str) -> float | None:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = tmp.name
    try:
        tmp.write(raw)
        tmp.close()
        if kind == "video":
            return await _validate_video_path(path)
        if kind == "audio":
            return await _validate_audio_path(path)
        _validate_image_path(path)
        return None
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


async def _store_video_reference(message: types.Message, state: FSMContext, media, ext: str, mime: str) -> None:
    data = await state.get_data()
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Видео-референсы доступны только в мультимодальном режиме Seedance 2.5.")
        return
    urls = _clean_urls(data.get("v_reference_videos") or [])
    if data.get("seedance25_identity_transfer") is True and urls:
        await message.answer("Для замены персонажа нужно одно исходное видео. Очистите референсы для нового набора.")
        return
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 видео-референсов.")
        return
    raw = await _download_telegram_bytes(message, media)
    try:
        duration = float(await _validate_temp_bytes(raw, f".{ext}", "video") or 0)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    durations = [float(item or 0) for item in data.get("seedance25_reference_video_durations") or []]
    if sum(durations) + duration > MAX_TOTAL_VIDEO_DURATION + 0.01:
        await message.answer("❌ Суммарная длительность видео-референсов — максимум 30 секунд.")
        return
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="video",
        original_filename=f"seedance25_{media.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить видео.")
        return
    urls.append(url)
    durations.append(duration)
    await state.update_data(v_reference_videos=urls, seedance25_reference_video_durations=durations)
    await message.answer(f"✅ Видео добавлено: {duration:.2f}с, проверены FPS/размеры/формат.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)


async def _store_audio_reference(message: types.Message, state: FSMContext, media, ext: str, mime: str) -> None:
    data = await state.get_data()
    if data.get("seedance25_identity_transfer") is True:
        await message.answer("В замене персонажа отдельное аудио не используется. Выберите обычные референсы для аудио.")
        return
    if data.get("seedance25_scenario") != "multimodal":
        await message.answer("Аудио-референсы доступны только в мультимодальном режиме Seedance 2.5.")
        return
    urls = _clean_urls(data.get("seedance25_reference_audio_urls") or [])
    if len(urls) >= 10:
        await message.answer("❌ Максимум 10 аудио-референсов.")
        return
    raw = await _download_telegram_bytes(message, media)
    try:
        duration = float(await _validate_temp_bytes(raw, f".{ext}", "audio") or 0)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    url = await generation_module._persist_reusable_media_reference(
        message.from_user.id,
        raw,
        ext,
        kind="audio",
        original_filename=f"seedance25_{media.file_id}.{ext}",
        content_type=mime,
    )
    if not url:
        await message.answer("❌ Не удалось сохранить аудио.")
        return
    urls.append(url)
    await state.update_data(seedance25_reference_audio_urls=urls)
    await message.answer(f"✅ Аудио добавлено: {duration:.2f}с, формат проверен.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.video)
async def seedance25_full_video(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    media = message.video
    mime = str(media.mime_type or "video/mp4").lower()
    ext = "mov" if "quicktime" in mime else "mp4"
    await _store_video_reference(message, state, media, ext, mime)


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.audio)
async def seedance25_full_audio(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    media = message.audio
    name = str(media.file_name or "").lower()
    mime = str(media.mime_type or "").lower()
    ext = "wav" if name.endswith(".wav") or "wav" in mime else "mp3"
    await _store_audio_reference(message, state, media, ext, mime or f"audio/{ext}")


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.voice)
async def seedance25_full_voice(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    await message.answer("❌ Telegram Voice = OGG. По Seedance 2.5 spec используйте WAV или MP3 файлом.")


@router.message(generation_module.GenerationStates.waiting_for_video_prompt, F.document)
async def seedance25_full_document(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    document = message.document
    name = str(document.file_name or "").lower()
    ext = Path(name).suffix.lower().lstrip(".")
    mime = str(document.mime_type or "application/octet-stream").lower()
    if ext in VIDEO_EXTS:
        await _store_video_reference(message, state, document, ext, "video/quicktime" if ext == "mov" else "video/mp4")
        return
    if ext in AUDIO_EXTS:
        await _store_audio_reference(message, state, document, ext, "audio/wav" if ext == "wav" else "audio/mpeg")
        return
    # Image documents are handled by the existing preview router.
    raise SkipHandler


@router.message(
    generation_module.GenerationStates.waiting_for_video_prompt,
    F.text.regexp(r"(?i)^asset:(first|last|image|video|audio|clear)\b"),
)
async def seedance25_asset_command(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("v_model") != MODEL_KEY or not _is_admin(message.from_user.id):
        raise SkipHandler
    text = str(message.text or "").strip()
    head, _, raw_value = text.partition(" ")
    kind = head.split(":", 1)[1].lower()
    value = raw_value.strip()
    if kind == "clear":
        await state.update_data(
            seedance25_first_frame_url=None,
            seedance25_last_frame_url=None,
            reference_images=[],
            v_reference_videos=[],
            seedance25_reference_audio_urls=[],
            seedance25_reference_video_durations=[],
        )
        await message.answer("✅ Seedance asset inputs очищены.")
        await preview_module._show_seedance_25_screen(message, state, edit=False)
        return
    if not value.startswith("asset://"):
        await message.answer("❌ Формат: <code>asset:image asset://asset-id</code>", parse_mode="HTML")
        return

    scenario = str(data.get("seedance25_scenario") or "text")
    if kind in {"first", "last"}:
        if scenario not in {"first_frame", "first_last"}:
            await message.answer("Сначала выберите сценарий 1-й кадр или 1-й + последний.")
            return
        if kind == "first":
            await state.update_data(seedance25_first_frame_url=value)
        else:
            if scenario != "first_last":
                await message.answer("Последний кадр доступен только в режиме 1-й + последний.")
                return
            await state.update_data(seedance25_last_frame_url=value)
    else:
        if scenario != "multimodal":
            await message.answer("asset:image/video/audio доступны только в мультимодальном сценарии.")
            return
        mapping = {
            "image": ("reference_images", 30),
            "video": ("v_reference_videos", 10),
            "audio": ("seedance25_reference_audio_urls", 10),
        }
        state_key, limit = mapping[kind]
        values = _clean_urls([*(data.get(state_key) or []), value], limit)
        await state.update_data(**{state_key: values})
    await message.answer(f"✅ {kind}: asset добавлен.")
    await preview_module._show_seedance_25_screen(message, state, edit=False)
