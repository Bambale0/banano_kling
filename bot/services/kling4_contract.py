"""Strict Kling4 contract and measured provider-cost quotes. No network I/O."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from bot.services.wan3_prime_media import MediaInfo, Wan3PrimeValidationError

MODELS = {
    "reference": "kling-4.0/reference-to-video",
    "keyframe": "kling-4.0/keyframe-to-video",
}
RATIOS = ("auto", "16:9", "9:16", "1:1", "21:9")
DEFAULT_SETTINGS = {
    "rates": {
        "keyframe": {"720p": "28.5", "1080p": "42.5"},
        "reference": {"720p": "28.5", "1080p": "42.5"},
        "video": {"720p": "17", "1080p": "25.5"},
    },
    "max_active": 3,
    "poll_seconds": 30,
    "result_max_bytes": 250 * 1024**2,
    "result_timeout_seconds": 180,
    "retention_days": 30,
}


class Kling4Error(Wan3PrimeValidationError):
    pass


def require_admin(actor) -> None:
    # Always check the trusted actor, never a client-provided is_admin flag.
    if not actor.is_admin:
        raise Kling4Error("Kling 4 доступен только администратору.", status=403)


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_settings(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
        raise Kling4Error("Неверные поля настроек Kling 4.")
    rates = value["rates"]
    if not isinstance(rates, dict) or set(rates) != {"keyframe", "reference", "video"}:
        raise Kling4Error("Нужны все шесть тарифов.")
    for category in rates.values():
        if not isinstance(category, dict) or set(category) != {"720p", "1080p"}:
            raise Kling4Error("Нужны тарифы 720p и 1080p.")
        for rate in category.values():
            try:
                number = Decimal(str(rate))
                if (
                    isinstance(rate, bool)
                    or not number.is_finite()
                    or not 0 < number <= 10000
                ):
                    raise ValueError
            except Exception as exc:
                raise Kling4Error("Тариф должен быть положительным числом.") from exc
    bounds = {
        "max_active": (1, 20),
        "poll_seconds": (5, 300),
        "result_max_bytes": (1024, 1024**3),
        "result_timeout_seconds": (10, 600),
        "retention_days": (1, 365),
    }
    for key, (low, high) in bounds.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise Kling4Error(f"Недопустимое значение {key}.")
    return json.loads(canonical(value))


@dataclass(frozen=True)
class Kling4Recipe:
    mode: str
    input: dict
    media: tuple[MediaInfo, ...]
    video_seconds: Decimal

    @property
    def model(self) -> str:
        return MODELS[self.mode]

    def snapshot(self) -> dict:
        return {
            "mode": self.mode,
            "input": self.input,
            "media": [asdict(m) for m in self.media],
            "video_seconds": str(self.video_seconds),
            "provider_model": self.model,
        }

    def quote(self, settings: dict, revision: int) -> dict:
        ordinary = self.input.get("video_urls", [])
        category = "video" if ordinary else self.mode
        durations = {
            m.url: Decimal(str(m.duration_seconds))
            for m in self.media
            if m.kind == "video"
        }
        measured = sum((durations[url] for url in ordinary), Decimal(0))
        billed_input = measured.to_integral_value(rounding=ROUND_CEILING)
        rate = Decimal(str(settings["rates"][category][self.input["resolution"]]))
        output = Decimal(self.input["duration"])
        seconds = output + max(output, billed_input) if ordinary else output
        payload = {
            "recipe_hash": digest(self.snapshot()),
            "settings_revision": revision,
            "tariff": category,
            "resolution": self.input["resolution"],
            "rate": str(rate),
            "input_video_seconds": str(measured),
            "quota_video_seconds": str(self.video_seconds),
            "billing_policy": "ordinary_videos_ceil_aggregate",
            "billed_seconds": str(seconds),
            "provider_credits": str(rate * seconds),
            "admin_free": True,
        }
        return {**payload, "quote_hash": digest(payload)}


async def validate_recipe(body: dict, probe) -> Kling4Recipe:
    if not isinstance(body, dict) or set(body) - {"mode", "input"}:
        raise Kling4Error("Ожидаются mode и input.")
    mode, raw = body.get("mode"), body.get("input")
    if mode not in MODELS or not isinstance(raw, dict):
        raise Kling4Error("Выберите Reference или Keyframe.")
    allowed = {"prompt", "duration", "resolution", "aspect_ratio"} | (
        {"image_urls", "video_urls", "elements", "voices", "keep_original_sound"}
        if mode == "reference"
        else {"first_frame_url", "last_frame_url", "keyframe_urls"}
    )
    if set(raw) - allowed:
        raise Kling4Error(
            "Неподдерживаемые поля Kling 4: " + ", ".join(sorted(set(raw) - allowed))
        )
    data = {k: v for k, v in raw.items() if v is not None}
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        raise Kling4Error("Промпт: от 1 до 8000 символов.")
    duration = data.setdefault("duration", 5)
    if type(duration) is not int or not 3 <= duration <= 30:
        raise Kling4Error("Длительность: целое число от 3 до 30 секунд.")
    if data.setdefault("resolution", "720p") not in {"720p", "1080p"}:
        raise Kling4Error("Разрешение: 720p или 1080p.")
    if "aspect_ratio" in data and data["aspect_ratio"] not in RATIOS:
        raise Kling4Error("Неверные пропорции кадра.")
    media: list[MediaInfo] = []
    video_seconds = Decimal(0)
    tags: set[str] = set()

    def array(value, maximum: int, label: str) -> list:
        if not isinstance(value, list) or len(value) > maximum:
            raise Kling4Error(f"{label}: максимум {maximum}.")
        return value

    async def asset(url, kind: str, *, element=False):
        nonlocal video_seconds
        if not isinstance(url, str) or len(url) > 2048:
            raise Kling4Error("Некорректный адрес материала.")
        info = await probe.probe_url(
            url, kind=kind
        )  # owner-scoped, measured stored bytes only
        if not info.sha256 or not info.size_bytes:
            raise Kling4Error("Загрузите материал перед расчётом.")
        if kind == "image":
            if info.extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise Kling4Error("Изображения: JPEG, PNG, WEBP.")
            width, height = info.width or 0, info.height or 0
            if (
                min(width, height) < 300
                or width * height > 40_000_000
                or not 0.4 <= width / height <= 2.5
            ):
                raise Kling4Error(
                    "Кадр: минимум 300px, до 40MP, пропорции от 0.4 до 2.5."
                )
        else:
            seconds = info.duration_seconds
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (float, int))
                or not math.isfinite(seconds)
                or seconds <= 0
            ):
                raise Kling4Error("Не удалось измерить длительность материала.")
            if kind == "video":
                if info.extension != ".mp4" or not (3 if element else 2) <= seconds <= (
                    8 if element else 30
                ):
                    raise Kling4Error(
                        "Видео: MP4, 3–8с для персонажа, 2–30с для референса."
                    )
                if element and min(info.width or 0, info.height or 0) < 700:
                    raise Kling4Error(
                        "Видео персонажа: короткая сторона минимум 700px."
                    )
                video_seconds += Decimal(str(seconds))
            elif info.extension not in {".wav", ".mp3"} or seconds > 30:
                raise Kling4Error("Голос: MP3/WAV с речью, до 30 секунд.")
        media.append(info)

    def name(value):
        if not isinstance(value, str) or not re.fullmatch(
            r"[\u4E00-\u9FA5A-Za-z0-9_]{1,20}", value
        ):
            raise Kling4Error("Имя: 1–20 латинских/китайских букв, цифр или _.")
        folded = value.casefold()
        if any(t.casefold() == folded for t in tags) or re.fullmatch(
            r"(?:image|video|keyframe|object|audio)_\d+|first_frame|last_frame", folded
        ):
            raise Kling4Error(
                "Имена должны быть уникальными и не совпадать со служебными тегами."
            )
        tags.add(value)

    if mode == "keyframe":
        count = 0
        for key in ("first_frame_url", "last_frame_url"):
            if key in data:
                await asset(data[key], "image")
                tags.add(key.removesuffix("_url"))
                count += 1
        for index, url in enumerate(
            array(data.get("keyframe_urls", []), 8, "Промежуточные кадры"), 1
        ):
            await asset(url, "image")
            tags.add(f"keyframe_{index}")
            count += 1
        if count > min(10, duration + 1):
            raise Kling4Error(
                f"Для {duration}с допустимо {min(10, duration + 1)} кадров. Удалите лишние или увеличьте длительность."
            )
    else:
        images = array(data.get("image_urls", []), 10, "Фото")
        videos = array(data.get("video_urls", []), 5, "Видео")
        elements = array(data.get("elements", []), 7, "Персонажи/объекты")
        voices = array(data.get("voices", []), 3, "Голоса")
        if len(images) + len(videos) + len(elements) + len(voices) > 15:
            raise Kling4Error("Всего допустимо 15 материалов.")
        if "keep_original_sound" in data and (
            type(data["keep_original_sound"]) is not bool or not videos
        ):
            raise Kling4Error("Исходный звук доступен только с видеореференсом.")
        for kind, urls in (("image", images), ("video", videos)):
            for i, url in enumerate(urls, 1):
                await asset(url, kind)
                tags.add(f"{kind}_{i}")
        video_elements = 0
        for element in elements:
            if not isinstance(element, dict) or set(element) - {
                "name",
                "image_urls",
                "video_url",
                "tag",
                "description",
                "voice_url",
            }:
                raise Kling4Error("Неверные поля персонажа/объекта.")
            name(element.get("name"))
            if ("image_urls" in element) == ("video_url" in element):
                raise Kling4Error("Для элемента нужны либо 2–4 фото, либо одно видео.")
            tag = element.get("tag")
            if tag is not None and tag not in {
                "character",
                "animal",
                "prop",
                "costume",
                "scene",
                "effect",
                "others",
            }:
                raise Kling4Error("Неверный тип элемента.")
            description = element.get("description", "")
            if not isinstance(description, str) or len(description) > 100:
                raise Kling4Error("Описание элемента: до 100 символов.")
            if "video_url" in element:
                if tag not in {None, "character"}:
                    raise Kling4Error("Видеоэлемент может быть только персонажем.")
                await asset(element["video_url"], "video", element=True)
                video_elements += 1
            else:
                photos = array(element["image_urls"], 4, "Фото элемента")
                if len(photos) < 2:
                    raise Kling4Error("Элементу нужны минимум два фото.")
                for url in photos:
                    await asset(url, "image")
            if "voice_url" in element:
                if tag not in {None, "character"}:
                    raise Kling4Error("Голос можно привязать только персонажу.")
                await asset(element["voice_url"], "audio")
        if video_elements > 3 or video_elements + len(videos) > 5:
            raise Kling4Error("Максимум 3 видеоперсонажа и 5 видео суммарно.")
        for voice in voices:
            if not isinstance(voice, dict) or set(voice) != {"name", "audio_url"}:
                raise Kling4Error("Голосу нужны name и audio_url.")
            name(voice["name"])
            await asset(voice["audio_url"], "audio")
        if video_seconds > 30:
            raise Kling4Error("Суммарно входные видео не должны превышать 30 секунд.")

    declared_names = {tag.casefold(): tag for tag in tags}

    def mention(match):
        token = match.group(1)
        # Exact declared names win: a subject named Image1 is a distinct asset.
        if token in tags:
            return match.group(0)
        alias = re.fullmatch(r"(image|video)_?([1-9]\d*)", token, re.IGNORECASE)
        if alias:
            target = alias[1].lower() + "_" + alias[2]
            if (
                target in tags
                and declared_names.get(token.casefold(), target) == target
            ):
                return "@" + target
        raise Kling4Error(f"Тег @{token} не соответствует загруженному материалу.")

    data["prompt"] = re.sub(r"@([\w\u4E00-\u9FA5]+)", mention, prompt)
    if len(data["prompt"]) > 8000:
        raise Kling4Error("Промпт: от 1 до 8000 символов.")
    return Kling4Recipe(mode, json.loads(canonical(data)), tuple(media), video_seconds)
