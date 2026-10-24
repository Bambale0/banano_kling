"""Pure Telegram presentation for the Kling 4 editor.

This module intentionally has no aiogram, lifecycle, database or provider
imports. The handler supplies the validated price text and converts the button
specification into Telegram objects.
"""

from __future__ import annotations

import html
from collections.abc import Iterable

Button = tuple[str, str]
ButtonRows = list[list[Button]]


def mode_label(recipe: dict) -> str:
    return "По референсам" if recipe["mode"] == "reference" else "По кадрам"


def ratio_label(value: str) -> str:
    return "Авто" if value == "auto" else value


def reference_labels(recipe: dict) -> str:
    data = recipe["input"]
    if recipe["mode"] == "reference":
        groups = [
            ("Фото", [f"image_{i}" for i in range(1, len(data.get("image_urls") or []) + 1)]),
            ("Видео", [f"video_{i}" for i in range(1, len(data.get("video_urls") or []) + 1)]),
            ("Материалы", [item["name"] for item in data.get("elements") or []]),
            ("Голоса", [item["name"] for item in data.get("voices") or []]),
        ]
    else:
        frames = ["first_frame"] if data.get("first_frame_url") else []
        frames += [
            f"keyframe_{i}"
            for i in range(1, len(data.get("keyframe_urls") or []) + 1)
        ]
        frames += ["last_frame"] if data.get("last_frame_url") else []
        groups = [("Кадры", frames)]
    return "; ".join(
        label + ": " + html.escape(", ".join("@" + name for name in names))
        for label, names in groups
        if names
    )


def render_editor_card(recipe: dict, price_text: str) -> str:
    data = recipe["input"]
    images = len(data.get("image_urls") or [])
    videos = len(data.get("video_urls") or [])
    elements = len(data.get("elements") or [])
    voices = len(data.get("voices") or [])
    if recipe["mode"] == "keyframe":
        first = "✅" if data.get("first_frame_url") else "—"
        middle = len(data.get("keyframe_urls") or [])
        last = "✅" if data.get("last_frame_url") else "—"
        media_hint = (
            "Загрузите первый, промежуточные или последний кадр прямо сюда. "
            f"Сейчас: первый {first}, промежуточных <code>{middle}</code>, "
            f"последний {last}.\nФормат видео задаёт первый загруженный кадр."
        )
    else:
        media_hint = (
            "Можно присылать фото / видео / аудио прямо сюда. "
            f"Сейчас: фото <code>{images}/10</code>, видео <code>{videos}/5</code>, "
            f"материалы <code>{elements}/7</code>, голоса <code>{voices}/3</code>."
        )
    audio_label = (
        "исходный звук включён"
        if videos and data.get("keep_original_sound")
        else "исходный звук выключен"
        if videos
        else "создаёт модель"
    )
    labels = reference_labels(recipe)
    prompt = html.escape(data.get("prompt") or "").strip()
    return (
        "🎬 <b>Kling 4</b>\n\n"
        f"Сценарий: <b>{mode_label(recipe)}</b>\n"
        f"Качество: <code>{data['resolution']}</code> · "
        f"Формат кадра: <code>{ratio_label(data.get('aspect_ratio', 'auto'))}</code> · "
        f"Длительность: <code>{data['duration']}с</code>\n"
        f"Аудио: <code>{audio_label}</code>\n\n"
        f"{media_hint}"
        + (f"\nМетки: {labels}" if labels else "")
        + f"\n\n{price_text}\n\n"
        "После настройки отправьте промпт до 8000 символов — генерация запустится сразу."
        + (f"\n\nТекущий промпт: {prompt}" if prompt else "")
    )


def keyboard_rows(recipe: dict, ratios: Iterable[str]) -> ButtonRows:
    data = recipe["input"]
    ratio_values = tuple(ratios)
    selected_ratio = data.get("aspect_ratio", "auto")
    rows: ButtonRows = [
        [
            (
                ("✅ " if recipe["mode"] == value else "") + label,
                "k4:mode:" + value,
            )
            for value, label in (
                ("reference", "🧩 По референсам"),
                ("keyframe", "🎞 По кадрам"),
            )
        ],
        [
            (
                ("✅ " if data["resolution"] == value else "") + value,
                "k4:resolution:" + value,
            )
            for value in ("720p", "1080p")
        ],
        [
            (
                ("✅ " if selected_ratio == value else "") + ratio_label(value),
                "k4:ratio:" + value,
            )
            for value in ("auto", *ratio_values[1:3])
        ],
        [
            (
                ("✅ " if selected_ratio == value else "") + ratio_label(value),
                "k4:ratio:" + value,
            )
            for value in ratio_values[3:]
        ],
        [
            ("− 1с", "k4:duration:-1"),
            (f"⏱ {data['duration']}с", "k4:duration:0"),
            ("+ 1с", "k4:duration:1"),
        ],
    ]
    if recipe["mode"] == "keyframe":
        rows.append(
            [
                ("Первый кадр", "k4:media:first_frame_url"),
                ("Средние", "k4:media:keyframe_urls"),
                ("Последний", "k4:media:last_frame_url"),
            ]
        )
    else:
        materials = len(data.get("elements") or [])
        voices = len(data.get("voices") or [])
        sound = (
            "🔊 Исходный звук: "
            + ("вкл" if data.get("keep_original_sound") else "выкл")
            if data.get("video_urls")
            else "🔊 Звук: авто"
        )
        rows.append(
            [
                (
                    f"🧩 Материалы ({materials}) · 🎙 Голоса ({voices})",
                    "k4:materials",
                ),
                (sound, "k4:sound"),
            ]
        )
    rows.extend(
        [
            [("🧹 Очистить медиа", "k4:clear")],
            [("← Модели Kling", "video_models:kling:0")],
        ]
    )
    return rows
