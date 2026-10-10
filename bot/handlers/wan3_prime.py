"""Telegram FSM for Wan 3.0 Video Prime.

The handler owns conversational state, ordered media slots and option editing.
Lifecycle, billing, owned media storage, import validation and delivery are
delegated to the lazy `bot.wan3_prime_api` facade.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.wan3_prime_service import Wan3PrimeService

logger = logging.getLogger(__name__)
router = Router(name="wan3_prime")

TELEGRAM_DIRECT_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_REFS = 10
MAX_VIDEO_REFS = 5
MAX_AUDIO_REFS = 5
MAX_FILE_REFS = 1
MAX_LINK_REFS = 1

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov"}
AUDIO_EXTS = {".wav", ".mp3", ".oga", ".ogg", ".m4a"}
FILE_EXTS = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".pdf", ".txt", ".key", ".pages", ".numbers", ".md"}

WAN3_MODE_LABELS = {
    "text": "Текст",
    "first_frame": "Первый кадр",
    "first_last": "Первый + последний кадр",
    "reference": "Референсы",
    "edit": "Правка видео",
    "file": "Файл",
    "link": "Ссылка",
}
RESOLUTIONS = ("480P", "720P", "1080P")
RATIOS = ("adaptive", "16:9", "4:3", "1:1", "3:4", "9:16")
DURATIONS = (-1,) + tuple(range(2, 31))

_ACTOR_LOCKS: dict[int, asyncio.Lock] = {}


class Wan3PrimeStates(StatesGroup):
    dashboard = State()
    choosing_mode = State()
    waiting_prompt = State()
    waiting_repeat_input = State()
    waiting_first_frame = State()
    waiting_last_frame = State()
    waiting_source_video = State()
    waiting_image_reference = State()
    waiting_video_reference = State()
    waiting_audio_reference = State()
    waiting_file_reference = State()
    waiting_link_reference = State()
    waiting_seed = State()
    waiting_duration = State()
    reviewing = State()


@dataclass
class Wan3PrimeDraft:
    scenario: str = "text"
    prompt: str = ""
    first_frame_url: str | None = None
    last_frame_url: str | None = None
    reference_image_urls: list[str] = field(default_factory=list)
    reference_video_urls: list[str] = field(default_factory=list)
    reference_audio_urls: list[str] = field(default_factory=list)
    reference_file_urls: list[str] = field(default_factory=list)
    reference_link_urls: list[str] = field(default_factory=list)
    resolution: str = "1080P"
    aspect_ratio: str = "adaptive"
    duration: int = 5
    audio: bool = True
    seed: int | None = None
    nsfw_checker: bool = False
    client_request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    quote_hash: str | None = None
    mode_drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_quote: dict[str, Any] | None = None
    source_feed_gen_id: int | None = None
    trend_id: int | None = None
    repeat_plan_hash: str | None = None
    repeat_replacements: dict[str, str] = field(default_factory=dict)
    repeat_slots: list[dict[str, Any]] = field(default_factory=list)


def _new_ids(draft: Wan3PrimeDraft) -> None:
    draft.client_request_id = str(uuid.uuid4())
    draft.idempotency_key = str(uuid.uuid4())
    draft.quote_hash = None
    draft.last_quote = None


def invalidate_quote(draft: Wan3PrimeDraft) -> None:
    draft.quote_hash = None
    draft.last_quote = None


def draft_from_state(data: dict[str, Any] | None) -> Wan3PrimeDraft:
    source = dict(data or {}).get("wan3_prime") if isinstance(data, dict) else None
    if not isinstance(source, dict):
        return Wan3PrimeDraft()
    allowed = set(Wan3PrimeDraft.__dataclass_fields__)  # type: ignore[attr-defined]
    payload = {key: deepcopy(value) for key, value in source.items() if key in allowed}
    draft = Wan3PrimeDraft()
    for key, value in payload.items():
        setattr(draft, key, value)
    if not draft.client_request_id:
        draft.client_request_id = str(uuid.uuid4())
    if not draft.idempotency_key:
        draft.idempotency_key = str(uuid.uuid4())
    return draft


def draft_to_state(draft: Wan3PrimeDraft) -> dict[str, Any]:
    return {"wan3_prime": asdict(draft)}


def _snapshot_mode(draft: Wan3PrimeDraft) -> dict[str, Any]:
    data = asdict(draft)
    data.pop("mode_drafts", None)
    return data


def _restore_mode(base: Wan3PrimeDraft, scenario: str) -> Wan3PrimeDraft | None:
    saved = base.mode_drafts.get(scenario)
    if not isinstance(saved, dict):
        return None
    restored = Wan3PrimeDraft(**{key: deepcopy(value) for key, value in saved.items() if key in Wan3PrimeDraft.__dataclass_fields__})  # type: ignore[attr-defined]
    restored.mode_drafts = deepcopy(base.mode_drafts)
    restored.client_request_id = base.client_request_id
    restored.idempotency_key = base.idempotency_key
    restored.quote_hash = None
    restored.last_quote = None
    return restored


def apply_wan3_mode(draft: Wan3PrimeDraft, scenario: str) -> Wan3PrimeDraft:
    if draft.source_feed_gen_id or draft.trend_id:
        raise ValueError("Режим повтора сохранён из публикации. Для другого режима создайте новую задачу.")
    if scenario not in Wan3PrimeService.SCENARIOS:
        raise ValueError("Неизвестный режим Wan 3.0")
    draft.mode_drafts[draft.scenario] = _snapshot_mode(draft)
    restored = _restore_mode(draft, scenario)
    if restored:
        return restored
    next_draft = Wan3PrimeDraft(**{key: deepcopy(getattr(draft, key)) for key in Wan3PrimeDraft.__dataclass_fields__ if key != "mode_drafts"})  # type: ignore[attr-defined]
    next_draft.mode_drafts = deepcopy(draft.mode_drafts)
    next_draft.scenario = scenario
    invalidate_quote(next_draft)
    if scenario in {"text", "first_frame", "first_last"}:
        next_draft.reference_image_urls = []
        next_draft.reference_video_urls = []
        next_draft.reference_audio_urls = []
        next_draft.reference_file_urls = []
        next_draft.reference_link_urls = []
    if scenario not in {"first_frame", "first_last"}:
        next_draft.first_frame_url = None
        next_draft.last_frame_url = None
    if scenario != "first_last":
        next_draft.last_frame_url = None
    return next_draft


def append_ordered_slot(values: list[str], url: str, *, limit: int, label: str) -> list[str]:
    cleaned = str(url or "").strip()
    if not cleaned:
        raise ValueError(f"Пустой слот {label}")
    if len(values) >= limit:
        raise ValueError(f"Wan 3.0 принимает максимум {limit}: {label}")
    return [*values, cleaned]


def remove_ordered_slot(values: list[str], index: int, *, label: str) -> list[str]:
    if index < 0 or index >= len(values):
        raise ValueError(f"Нет слота {label}{index + 1}")
    return [value for pos, value in enumerate(values) if pos != index]


def build_wan3_payload(draft: Wan3PrimeDraft) -> dict[str, Any]:
    return {
        "model": "wan_3_prime",
        **({**({"trend_id": draft.trend_id} if draft.trend_id else {"source_feed_gen_id": draft.source_feed_gen_id}),
            "repeat_plan_hash": draft.repeat_plan_hash, "repeat_replacements": dict(draft.repeat_replacements)}
           if draft.source_feed_gen_id or draft.trend_id else {}),
        "scenario": draft.scenario,
        "prompt": draft.prompt,
        "resolution": draft.resolution,
        "aspect_ratio": draft.aspect_ratio,
        "duration": draft.duration,
        "audio": draft.audio,
        "seed": draft.seed,
        "nsfw_checker": draft.nsfw_checker,
        "first_frame_url": draft.first_frame_url,
        "last_frame_url": draft.last_frame_url,
        "reference_image_urls": list(draft.reference_image_urls),
        "reference_video_urls": list(draft.reference_video_urls),
        "reference_audio_urls": list(draft.reference_audio_urls),
        "reference_file_urls": list(draft.reference_file_urls),
        "reference_link_urls": list(draft.reference_link_urls),
    }


def validate_wan3_draft(draft: Wan3PrimeDraft) -> None:
    if draft.source_feed_gen_id or draft.trend_id:
        required = {slot["key"] for slot in draft.repeat_slots if slot["binding"] == "upload"}
        if not draft.repeat_plan_hash or set(draft.repeat_replacements) != required or any(not value for value in draft.repeat_replacements.values()):
            raise ValueError("Загрузите свои материалы для каждого заменяемого места")
        if draft.duration not in DURATIONS or (draft.seed is not None and not 0 <= int(draft.seed) <= Wan3PrimeService.MAX_SEED):
            raise ValueError("Проверьте длительность и Seed")
        return
    if draft.scenario == "edit" and (not draft.reference_video_urls or not draft.reference_video_urls[0]):
        raise ValueError("Добавьте исходное видео Video1 перед расчётом")
    Wan3PrimeService._validate_scenario(
        scenario=draft.scenario,
        first_frame_url=draft.first_frame_url,
        last_frame_url=draft.last_frame_url,
        reference_image_urls=draft.reference_image_urls,
        reference_video_urls=draft.reference_video_urls,
        reference_audio_urls=draft.reference_audio_urls,
        reference_file_urls=draft.reference_file_urls,
        reference_link_urls=draft.reference_link_urls,
    )
    prompt = str(draft.prompt or "").strip()
    if draft.scenario == "text" and not prompt:
        raise ValueError("Введите промпт")
    if draft.scenario == "edit" and not prompt:
        raise ValueError("Введите инструкции правки")
    if draft.duration not in DURATIONS:
        raise ValueError("Длительность Wan 3.0: Auto или 2-30 секунд")
    if draft.seed is not None and not 0 <= int(draft.seed) <= Wan3PrimeService.MAX_SEED:
        raise ValueError("Seed Wan 3.0 должен быть 0-2147483647")


async def _runtime():
    from bot import wan3_prime_api

    return wan3_prime_api


def _actor_lock(actor_id: int) -> asyncio.Lock:
    lock = _ACTOR_LOCKS.get(actor_id)
    if lock is None:
        lock = asyncio.Lock()
        _ACTOR_LOCKS[actor_id] = lock
    return lock


def _keyboard(rows: list[list[tuple[str, str]]]) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def _mode_keyboard() -> types.InlineKeyboardMarkup:
    return _keyboard([
        [("Текст", "wan3_mode:text"), ("Первый кадр", "wan3_mode:first_frame")],
        [("Первый+последний", "wan3_mode:first_last"), ("Референсы", "wan3_mode:reference")],
        [("Правка видео", "wan3_mode:edit"), ("Файл", "wan3_mode:file"), ("Ссылка", "wan3_mode:link")],
        [("🔙 Дашборд", "wan3_dashboard")],
    ])


def dashboard_keyboard(draft: Wan3PrimeDraft) -> types.InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = [
        [("Режим", "wan3_modes"), ("Новая задача", "wan3_new")],
        [("Промпт/инструкции", "wan3_prompt")],
    ]
    if not (draft.source_feed_gen_id or draft.trend_id) and draft.scenario in {"first_frame", "first_last"}:
        rows.append([("Первый кадр", "wan3_media:first"), ("Последний кадр", "wan3_media:last")])
    if not (draft.source_feed_gen_id or draft.trend_id) and draft.scenario == "edit":
        rows.append([("Video1 источник", "wan3_media:source_video"), ("Видео 2-5", "wan3_media:video")])
    if not (draft.source_feed_gen_id or draft.trend_id) and draft.scenario in {"reference", "edit", "file", "link"}:
        rows.append([("Image 1-10", "wan3_media:image"), ("Video refs", "wan3_media:video"), ("Audio 1-5", "wan3_media:audio")])
        rows.append([("Файл 1", "wan3_media:file"), ("Webpage 1", "wan3_media:link")])
    if draft.source_feed_gen_id or draft.trend_id:
        rows[0] = [("Новая задача", "wan3_new")]
        for slot in draft.repeat_slots:
            if slot["binding"] == "upload":
                label = _repeat_slot_label(slot)
                prefix = "✅ " if draft.repeat_replacements.get(slot["key"]) else "➕ "
                rows.append([(prefix + label, "wan3_repeat_slot:" + slot["key"])])
    rows.extend([
        [("480P", "wan3_set:resolution:480P"), ("720P", "wan3_set:resolution:720P"), ("1080P", "wan3_set:resolution:1080P")],
        [("adaptive", "wan3_set:ratio:adaptive"), ("16:9", "wan3_set:ratio:16:9"), ("9:16", "wan3_set:ratio:9:16")],
        [("4:3", "wan3_set:ratio:4:3"), ("1:1", "wan3_set:ratio:1:1"), ("3:4", "wan3_set:ratio:3:4")],
        [("Auto duration", "wan3_set:duration:-1"), ("Длительность числом", "wan3_duration")],
        [("Seed", "wan3_seed"), ("Seed Auto", "wan3_set:seed:auto")],
        [("Аудио вкл/выкл", "wan3_toggle:audio"), ("NSFW check", "wan3_toggle:nsfw")],
        [("Проверить стоимость", "wan3_quote")],
        [("🔙 К моделям", "video_change_model")],
    ])
    return _keyboard(rows)


def remove_keyboard(draft: Wan3PrimeDraft) -> types.InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    for kind, values in (
        ("image", draft.reference_image_urls),
        ("video", draft.reference_video_urls),
        ("audio", draft.reference_audio_urls),
        ("file", draft.reference_file_urls),
        ("link", draft.reference_link_urls),
    ):
        row: list[tuple[str, str]] = []
        for index, _ in enumerate(values):
            row.append((f"Удалить {kind}{index + 1}", f"wan3_remove:{kind}:{index}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    rows.append([("Дашборд", "wan3_dashboard")])
    return _keyboard(rows)


def build_review_text(draft: Wan3PrimeDraft, quote: dict[str, Any] | None = None) -> str:
    duration = "Auto" if draft.duration == -1 else f"{draft.duration}с"
    lines = [
        "Wan 3.0 Video Prime",
        f"Режим: {WAN3_MODE_LABELS.get(draft.scenario, draft.scenario)}",
        f"Качество: {draft.resolution}; формат: {draft.aspect_ratio}; длительность: {duration}",
        f"Image {len(draft.reference_image_urls)}, Video {len(draft.reference_video_urls)}, Audio {len(draft.reference_audio_urls)}, File {len(draft.reference_file_urls)}, Link {len(draft.reference_link_urls)}",
        f"Первый кадр: {'есть' if draft.first_frame_url else 'нет'}; последний: {'есть' if draft.last_frame_url else 'нет'}",
        f"Seed: {draft.seed if draft.seed is not None else 'Auto'}; аудио: {'да' if draft.audio else 'нет'}; NSFW: {'да' if draft.nsfw_checker else 'нет'}",
        f"Client ID: {draft.client_request_id}",
    ]
    if draft.source_feed_gen_id or draft.trend_id:
        lines.append("Повтор публикации " + str(draft.trend_id or draft.source_feed_gen_id))
        for slot in draft.repeat_slots:
            state = "материал автора" if slot["binding"] == "fixed" else "загружено" if draft.repeat_replacements.get(slot["key"]) else "нужен ваш файл"
            lines.append(_repeat_slot_label(slot) + ": " + state)
    if quote:
        if quote.get("tariff_missing"):
            lines.append("Стоимость: тариф для качества не настроен.")
        elif quote.get("admin_free"):
            lines.append("Стоимость: админский бесплатный запуск.")
        else:
            lines.append(f"Резерв: {quote.get('reserve_cost')}🍌")
        lines.append(f"Секунды: source {quote.get('source_video_duration_seconds', 0)} + billing {quote.get('billing_duration_seconds', '?')}")
        if quote.get("settlement_notice") or quote.get("auto_duration"):
            lines.append(str(quote.get("settlement_notice") or "Auto: резерв максимальный, после результата возможен возврат разницы."))
    return "\n".join(lines)


def dashboard_text(draft: Wan3PrimeDraft) -> str:
    return build_review_text(draft, draft.last_quote) + "\n\nВыберите, что настроить."


async def _show_dashboard(target: Any, state: FSMContext, draft: Wan3PrimeDraft) -> None:
    await state.set_state(Wan3PrimeStates.dashboard)
    await state.update_data(**draft_to_state(draft), v_model="wan_3_prime")
    text = dashboard_text(draft)
    from aiogram.exceptions import TelegramBadRequest

    editable = (hasattr(target, "edit_text") and getattr(getattr(target, "from_user", None), "is_bot", True)
                and not any(getattr(target, kind, None) for kind in ("photo", "video", "document", "audio")))
    if editable:
        try:
            await target.edit_text(text, reply_markup=dashboard_keyboard(draft), parse_mode=None)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
    await target.answer(text, reply_markup=dashboard_keyboard(draft), parse_mode=None)


def _message_file(message: types.Message) -> tuple[str, str, int, str] | None:
    photos = getattr(message, "photo", None) or []
    if photos:
        photo = photos[-1]
        return photo.file_id, "image", getattr(photo, "file_size", 0) or 0, "photo.jpg"
    for attr, kind, default_name in (
        ("video", "video", "video.mp4"),
        ("audio", "audio", "audio.mp3"),
        ("voice", "audio", "voice.ogg"),
        ("document", "file", "document"),
    ):
        item = getattr(message, attr, None)
        if item:
            return item.file_id, kind, getattr(item, "file_size", 0) or 0, getattr(item, "file_name", None) or default_name
    return None


def _looks_url(text: str) -> bool:
    return bool(re.fullmatch(r"https?://\S+", text.strip(), flags=re.IGNORECASE))


def _has_ext(filename: str, allowed: set[str]) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in allowed)


def _media_state_for_kind(kind: str) -> State:
    return {
        "first": Wan3PrimeStates.waiting_first_frame,
        "last": Wan3PrimeStates.waiting_last_frame,
        "source_video": Wan3PrimeStates.waiting_source_video,
        "image": Wan3PrimeStates.waiting_image_reference,
        "video": Wan3PrimeStates.waiting_video_reference,
        "audio": Wan3PrimeStates.waiting_audio_reference,
        "file": Wan3PrimeStates.waiting_file_reference,
        "link": Wan3PrimeStates.waiting_link_reference,
    }[kind]


def _entry_kind_from_state(state_name: str | None) -> str:
    mapping = {
        Wan3PrimeStates.waiting_first_frame.state: "first",
        Wan3PrimeStates.waiting_last_frame.state: "last",
        Wan3PrimeStates.waiting_source_video.state: "source_video",
        Wan3PrimeStates.waiting_image_reference.state: "image",
        Wan3PrimeStates.waiting_video_reference.state: "video",
        Wan3PrimeStates.waiting_audio_reference.state: "audio",
        Wan3PrimeStates.waiting_file_reference.state: "file",
        Wan3PrimeStates.waiting_link_reference.state: "link",
    }
    return mapping.get(state_name or "", "")


def _validate_media_allowed(draft: Wan3PrimeDraft, kind: str) -> None:
    if draft.source_feed_gen_id or draft.trend_id:
        raise ValueError("Используйте пронумерованные места повтора")
    if kind in {"image", "video", "audio", "file", "link", "source_video"} and draft.scenario in {"text", "first_frame", "first_last"}:
        raise ValueError("В режиме кадров нельзя добавлять reference_* без смены режима.")
    if kind in {"first", "last"} and draft.scenario not in {"first_frame", "first_last"}:
        raise ValueError("Кадры доступны только в режимах первого/последнего кадра.")
    if kind == "last" and draft.scenario != "first_last":
        raise ValueError("Последний кадр доступен только в режиме Первый+последний.")
    if kind == "file" and draft.reference_link_urls:
        raise ValueError("Файл и ссылка взаимоисключают друг друга.")
    if kind == "link" and draft.reference_file_urls:
        raise ValueError("Файл и ссылка взаимоисключают друг друга.")


def _assign_url(draft: Wan3PrimeDraft, kind: str, url: str) -> None:
    _validate_media_allowed(draft, kind)
    if kind == "first":
        draft.first_frame_url = url
    elif kind == "last":
        draft.last_frame_url = url
    elif kind == "source_video":
        draft.reference_video_urls = [url, *draft.reference_video_urls[1:]]
    elif kind == "image":
        draft.reference_image_urls = append_ordered_slot(draft.reference_image_urls, url, limit=MAX_IMAGE_REFS, label="Image")
    elif kind == "video":
        start = 1 if draft.scenario == "edit" and draft.reference_video_urls else 0
        if len(draft.reference_video_urls) >= MAX_VIDEO_REFS:
            raise ValueError("Wan 3.0 принимает максимум 5 Video")
        values = list(draft.reference_video_urls)
        values.insert(len(values), url)
        if draft.scenario == "edit" and start == 0:
            raise ValueError("Сначала добавьте Video1 источник.")
        draft.reference_video_urls = values
    elif kind == "audio":
        draft.reference_audio_urls = append_ordered_slot(draft.reference_audio_urls, url, limit=MAX_AUDIO_REFS, label="Audio")
    elif kind == "file":
        if draft.reference_link_urls:
            raise ValueError("Файл и ссылка взаимоисключают друг друга.")
        draft.reference_file_urls = append_ordered_slot([], url, limit=MAX_FILE_REFS, label="File")
    elif kind == "link":
        if draft.reference_file_urls:
            raise ValueError("Файл и ссылка взаимоисключают друг друга.")
        draft.reference_link_urls = append_ordered_slot([], url, limit=MAX_LINK_REFS, label="Link")
    else:
        raise ValueError("Неизвестный тип медиа.")
    invalidate_quote(draft)


async def _store_or_import_media(message: types.Message, draft: Wan3PrimeDraft, kind: str) -> str:
    runtime = await _runtime()
    text = str(getattr(message, "text", "") or "").strip()
    actor_id = message.from_user.id
    if text and _looks_url(text):
        import_kind = {"first": "image", "last": "image", "source_video": "video"}.get(kind, kind)
        imported = await runtime.import_telegram_wan3_prime_reference(telegram_id=actor_id, kind=import_kind, url=text)
        return str(imported["url"])
    file_info = _message_file(message)
    if not file_info:
        raise ValueError("Пришлите файл Telegram или публичный https URL.")
    file_id, detected_kind, size, filename = file_info
    if size and size > TELEGRAM_DIRECT_DOWNLOAD_BYTES:
        raise ValueError("Telegram-файл больше 20 MB. Откройте Mini App для крупной загрузки; уже добавленные референсы сохранены.")
    expected = {"first": "image", "last": "image", "source_video": "video"}.get(kind, kind)
    if expected == "file":
        if detected_kind != "file" or not _has_ext(filename, FILE_EXTS):
            raise ValueError("Файл: docx/doc/xlsx/xls/pptx/ppt/pdf/txt/key/pages/numbers/md.")
    elif expected == "image":
        if detected_kind not in {"image", "file"} or (detected_kind == "file" and not _has_ext(filename, IMAGE_EXTS)):
            raise ValueError("Изображение: JPEG/PNG/BMP/WEBP.")
    elif expected == "video":
        if detected_kind not in {"video", "file"} or (detected_kind == "file" and not _has_ext(filename, VIDEO_EXTS)):
            raise ValueError("Видео: mp4/mov.")
    elif expected == "audio" and (detected_kind not in {"audio", "file"} or (detected_kind == "file" and not _has_ext(filename, AUDIO_EXTS))):
        raise ValueError("Аудио: wav/mp3; voice принимается как аудио и валидируется на сервере.")
    stored = await runtime.store_telegram_wan3_prime_media(
        telegram_id=actor_id,
        bot=message.bot,
        file_id=file_id,
        filename=filename,
        kind=expected,
        declared_size=size,
    )
    return str(stored["url"])


@router.callback_query(F.data.in_({"wan3_open", "v_model_wan_3_prime", "wan3_dashboard"}))
async def open_wan3_prime(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    await _show_dashboard(callback.message, state, draft)
    await callback.answer()


@router.callback_query(F.data == "wan3_new")
async def new_wan3_prime(callback: types.CallbackQuery, state: FSMContext):
    draft = Wan3PrimeDraft()
    _new_ids(draft)
    await _show_dashboard(callback.message, state, draft)
    await callback.answer("Новая Wan-задача")


@router.callback_query(F.data == "wan3_modes")
async def wan3_modes(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Wan3PrimeStates.choosing_mode)
    await callback.message.edit_text("Выберите режим Wan 3.0. Несовместимые поля сохраняются в черновике режима и не будут отправлены.", reply_markup=_mode_keyboard(), parse_mode=None)
    await callback.answer()


@router.callback_query(F.data.startswith("wan3_mode:"))
async def choose_wan3_mode(callback: types.CallbackQuery, state: FSMContext):
    scenario = str(callback.data).split(":", 1)[1]
    try:
        draft = apply_wan3_mode(draft_from_state(await state.get_data()), scenario)
    except ValueError as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    await _show_dashboard(callback.message, state, draft)
    await callback.answer()


@router.callback_query(F.data == "wan3_prompt")
async def ask_wan3_prompt(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Wan3PrimeStates.waiting_prompt)
    await callback.message.edit_text("Отправьте промпт или инструкции. Для любого режима кроме text/edit можно отправить '-' и оставить пусто.", reply_markup=_keyboard([[("Дашборд", "wan3_dashboard")]]), parse_mode=None)
    await callback.answer()


@router.message(Wan3PrimeStates.waiting_prompt)
async def wan3_prompt(message: types.Message, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    text = str(getattr(message, "text", "") or "").strip()
    draft.prompt = "" if text == "-" and (draft.source_feed_gen_id or draft.trend_id or draft.scenario not in {"text", "edit"}) else text
    invalidate_quote(draft)
    await _show_dashboard(message, state, draft)


@router.callback_query(F.data.startswith("wan3_media:"))
async def ask_wan3_media(callback: types.CallbackQuery, state: FSMContext):
    kind = str(callback.data).split(":", 1)[1]
    draft = draft_from_state(await state.get_data())
    try:
        _validate_media_allowed(draft, kind)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.set_state(_media_state_for_kind(kind))
    instructions = {
        "first": "Пришлите первый кадр: фото или JPEG/PNG/BMP/WEBP документ, либо https URL.",
        "last": "Пришлите последний кадр: фото или JPEG/PNG/BMP/WEBP документ, либо https URL.",
        "source_video": "Пришлите SOURCE Video1: mp4/mov до Telegram-лимита или https URL.",
        "image": "Пришлите Image референс: JPEG/PNG/BMP/WEBP или https URL.",
        "video": "Пришлите Video референс: mp4/mov или https URL. В edit сначала нужен Video1 источник.",
        "audio": "Пришлите Audio референс: wav/mp3, voice/audio или https URL.",
        "file": "Пришлите документ docx/doc/xlsx/xls/pptx/ppt/pdf/txt/key/pages/numbers/md или https URL.",
        "link": "Пришлите публичную ссылку на страницу.",
    }[kind]
    await callback.message.edit_text(instructions, reply_markup=remove_keyboard(draft), parse_mode=None)
    await callback.answer()


@router.message(
    Wan3PrimeStates.waiting_first_frame,
    Wan3PrimeStates.waiting_last_frame,
    Wan3PrimeStates.waiting_source_video,
    Wan3PrimeStates.waiting_image_reference,
    Wan3PrimeStates.waiting_video_reference,
    Wan3PrimeStates.waiting_audio_reference,
    Wan3PrimeStates.waiting_file_reference,
    Wan3PrimeStates.waiting_link_reference,
)
async def receive_wan3_media(message: types.Message, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    kind = _entry_kind_from_state(await state.get_state())
    try:
        _validate_media_allowed(draft, kind)
        url = await _store_or_import_media(message, draft, kind)
        _assign_url(draft, kind, url)
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=remove_keyboard(draft), parse_mode=None)
        return
    except Exception:  # noqa: BLE001 - FSM boundary preserves draft and reports safe failure
        await message.answer("Не удалось сохранить медиа. Черновик и ключ запуска сохранены; повторите загрузку.", reply_markup=remove_keyboard(draft), parse_mode=None)
        return
    await _show_dashboard(message, state, draft)


@router.callback_query(F.data.startswith("wan3_remove:"))
async def remove_wan3_media(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    _, kind, raw_index = str(callback.data).split(":", 2)
    try:
        index = int(raw_index)
        if kind == "image":
            draft.reference_image_urls = remove_ordered_slot(draft.reference_image_urls, index, label="Image")
        elif kind == "video":
            if draft.scenario == "edit" and index == 0 and draft.reference_video_urls:
                draft.reference_video_urls = ["", *draft.reference_video_urls[1:]]
            else:
                draft.reference_video_urls = remove_ordered_slot(draft.reference_video_urls, index, label="Video")
        elif kind == "audio":
            draft.reference_audio_urls = remove_ordered_slot(draft.reference_audio_urls, index, label="Audio")
        elif kind == "file":
            draft.reference_file_urls = remove_ordered_slot(draft.reference_file_urls, index, label="File")
        elif kind == "link":
            draft.reference_link_urls = remove_ordered_slot(draft.reference_link_urls, index, label="Link")
        else:
            raise ValueError("Неизвестный тип")
        invalidate_quote(draft)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await _show_dashboard(callback.message, state, draft)
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("wan3_set:"))
async def set_wan3_option(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    _, field, value = str(callback.data).split(":", 2)
    try:
        if field == "resolution":
            if value not in RESOLUTIONS:
                raise ValueError("Недоступное качество")
            draft.resolution = value
        elif field == "ratio":
            if value not in RATIOS:
                raise ValueError("Недоступный формат")
            draft.aspect_ratio = value
        elif field == "duration":
            duration = int(value)
            if duration not in DURATIONS:
                raise ValueError("Auto или 2-30 секунд")
            draft.duration = duration
        elif field == "seed" and value == "auto":
            draft.seed = None
        else:
            raise ValueError("Неизвестная настройка")
        invalidate_quote(draft)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await _show_dashboard(callback.message, state, draft)
    await callback.answer()


@router.callback_query(F.data.startswith("wan3_toggle:"))
async def toggle_wan3_option(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    field = str(callback.data).split(":", 1)[1]
    if field == "audio":
        draft.audio = not draft.audio
    elif field == "nsfw":
        draft.nsfw_checker = not draft.nsfw_checker
    else:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
    invalidate_quote(draft)
    await _show_dashboard(callback.message, state, draft)
    await callback.answer()


@router.callback_query(F.data == "wan3_seed")
async def ask_wan3_seed(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Wan3PrimeStates.waiting_seed)
    await callback.message.edit_text("Введите seed целым числом 0..2147483647 или '-' для Auto.", reply_markup=_keyboard([[("Дашборд", "wan3_dashboard")]]), parse_mode=None)
    await callback.answer()


@router.message(Wan3PrimeStates.waiting_seed)
async def receive_wan3_seed(message: types.Message, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    text = str(getattr(message, "text", "") or "").strip()
    try:
        if text == "-":
            draft.seed = None
        elif not re.fullmatch(r"\d+", text):
            raise ValueError("Seed должен быть целым числом 0..2147483647.")
        else:
            value = int(text)
            if not 0 <= value <= Wan3PrimeService.MAX_SEED:
                raise ValueError("Seed должен быть 0..2147483647.")
            draft.seed = value
        invalidate_quote(draft)
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)
        return
    await _show_dashboard(message, state, draft)


@router.callback_query(F.data == "wan3_duration")
async def ask_wan3_duration(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Wan3PrimeStates.waiting_duration)
    await callback.message.edit_text("Введите длительность: -1 для Auto или целое 2..30.", reply_markup=_keyboard([[("Дашборд", "wan3_dashboard")]]), parse_mode=None)
    await callback.answer()


@router.message(Wan3PrimeStates.waiting_duration)
async def receive_wan3_duration(message: types.Message, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    text = str(getattr(message, "text", "") or "").strip()
    try:
        if not re.fullmatch(r"-?\d+", text):
            raise ValueError("Длительность должна быть целым числом.")
        value = int(text)
        if value not in DURATIONS:
            raise ValueError("Длительность: -1 Auto или 2..30 секунд.")
        draft.duration = value
        invalidate_quote(draft)
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)
        return
    await _show_dashboard(message, state, draft)


@router.callback_query(F.data == "wan3_quote")
async def quote_wan3_prime(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    try:
        validate_wan3_draft(draft)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    runtime = await _runtime()
    try:
        quote = await runtime.quote_telegram_wan3_prime(
            telegram_id=callback.from_user.id,
            client_request_id=draft.client_request_id,
            recipe=build_wan3_payload(draft),
        )
    except (ValueError, RuntimeError) as exc:
        await callback.message.answer(str(exc)[:1000], parse_mode=None)
        await callback.answer("Проверьте материалы и настройки", show_alert=True)
        return
    except Exception as exc:  # noqa: BLE001 - user boundary retains the draft on infrastructure errors
        logger.warning("Wan3 Telegram quote deferred: telegram_id=%s error_type=%s", callback.from_user.id, type(exc).__name__)
        await callback.answer("Не удалось получить расчёт. Черновик сохранён.", show_alert=True)
        return
    draft.quote_hash = str(quote.get("quote_hash") or "") or None
    draft.last_quote = dict(quote)
    await state.set_state(Wan3PrimeStates.reviewing)
    await state.update_data(**draft_to_state(draft))
    await callback.message.edit_text(
        build_review_text(draft, quote),
        reply_markup=_keyboard([[("▶️ Подтвердить запуск", "wan3_confirm")], [("Дашборд", "wan3_dashboard")]]),
        parse_mode=None,
    )
    await callback.answer("Проверьте расчёт")


@router.callback_query(F.data == "wan3_confirm")
async def confirm_wan3_prime(callback: types.CallbackQuery, state: FSMContext):
    actor_id = callback.from_user.id
    draft = draft_from_state(await state.get_data())
    if not draft.quote_hash:
        await callback.answer("Сначала обновите расчёт стоимости.", show_alert=True)
        return
    lock = _actor_lock(actor_id)
    if lock.locked():
        await callback.answer("Запуск уже отправляется. Повтор использует тот же ключ.", show_alert=True)
        return
    async with lock:
        runtime = await _runtime()
        try:
            result = await runtime.launch_telegram_wan3_prime(
                telegram_id=actor_id,
                client_request_id=draft.client_request_id,
                idempotency_key=draft.idempotency_key,
                quote_hash=draft.quote_hash,
                recipe=build_wan3_payload(draft),
            )
        except Exception:  # noqa: BLE001 - FSM boundary preserves draft and reports safe failure
            await callback.answer("Сеть оборвалась. Ключ запуска сохранён; повторите подтверждение.", show_alert=True)
            return
    status = str(result.get("status") or "unknown")
    internal_task_id = result.get("internal_task_id") or "неизвестен"
    status_text = {
        "queued": "Поставлено в очередь",
        "accepted": "Принято провайдером",
        "unknown": "Статус отправки неизвестен; восстановление продолжится по ID",
        "done": "Уже готово",
        "failed": "Провайдер отклонил или задача упала",
    }.get(status, f"Статус: {status}")
    await callback.message.edit_text(
        f"Wan 3.0\n{status_text}\nTask ID: {internal_task_id}\nClient ID: {draft.client_request_id}",
        reply_markup=_keyboard([[("Проверить этот запуск", "wan3_confirm")]] if status == "unknown"
            else [[("Новая задача", "wan3_new")], [("Дашборд", "wan3_dashboard")]]),
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wan3_recipe:"))
async def restore_wan3_owner_recipe(callback: types.CallbackQuery, state: FSMContext):
    task_id = str(callback.data).split(":", 1)[1]
    runtime = await _runtime()
    try:
        response = await runtime.owner_telegram_wan3_prime_recipe(telegram_id=callback.from_user.id, task_id=task_id)
        if not isinstance(response, dict):
            raise TypeError("Invalid owner recipe")
        recipe = response.get("recipe", response)
        if not isinstance(recipe, dict) or not recipe.get("scenario"):
            raise ValueError("Incomplete owner recipe")
    except Exception:  # noqa: BLE001 - FSM boundary preserves draft and reports safe failure
        await callback.answer("Не удалось восстановить рецепт.", show_alert=True)
        return
    if recipe.get("source_feed_gen_id") or recipe.get("trend_id"):
        try:
            if recipe.get("trend_id"):
                plan = await runtime.trend_plan_telegram_wan3_prime(telegram_id=callback.from_user.id, trend_id=recipe["trend_id"])
            else:
                plan = await runtime.repeat_plan_telegram_wan3_prime(telegram_id=callback.from_user.id, source_id=recipe["source_feed_gen_id"])
            draft = _draft_from_repeat_plan(plan, recipe)
            await _show_dashboard(callback.message, state, draft)
            await callback.answer()
        except (ValueError, RuntimeError):
            await callback.answer("Публикация или разрешение на повтор больше недоступны.", show_alert=True)
        return
    draft = Wan3PrimeDraft(
        scenario=str(recipe.get("scenario") or "text"),
        prompt=str(recipe.get("prompt") or ""),
        first_frame_url=recipe.get("first_frame_url"),
        last_frame_url=recipe.get("last_frame_url"),
        reference_image_urls=list(recipe.get("reference_image_urls") or []),
        reference_video_urls=list(recipe.get("reference_video_urls") or []),
        reference_audio_urls=list(recipe.get("reference_audio_urls") or []),
        reference_file_urls=list(recipe.get("reference_file_urls") or []),
        reference_link_urls=list(recipe.get("reference_link_urls") or []),
        resolution=str(recipe.get("resolution") or "1080P"),
        aspect_ratio=str(recipe.get("aspect_ratio") or "adaptive"),
        duration=int(recipe.get("duration") or 5),
        audio=bool(recipe.get("audio", True)),
        seed=recipe.get("seed"),
        nsfw_checker=bool(recipe.get("nsfw_checker", False)),
    )
    await _show_dashboard(callback.message, state, draft)
    await callback.answer("Рецепт восстановлен")


__all__ = [
    "Wan3PrimeDraft",
    "Wan3PrimeStates",
    "append_ordered_slot",
    "apply_wan3_mode",
    "build_review_text",
    "build_wan3_payload",
    "confirm_wan3_prime",
    "draft_from_state",
    "draft_to_state",
    "open_wan3_prime",
    "quote_wan3_prime",
    "receive_wan3_media",
    "receive_wan3_seed",
    "remove_ordered_slot",
    "router",
    "validate_wan3_draft",
]


def _repeat_slot_label(slot: dict[str, Any]) -> str:
    if slot["role"] == "first_frame":
        return "Первый кадр"
    if slot["role"] == "last_frame":
        return "Последний кадр"
    prefix = {"image": "Image", "video": "Video", "audio": "Audio", "file": "Документ ", "link": "Страница "}[slot["kind"]]
    return prefix + str(slot["index"] + 1) + (" (исходник)" if slot["role"] == "source_video" else "")


def _draft_from_repeat_plan(plan: dict, own_request: dict | None = None) -> Wan3PrimeDraft:
    allowed = {"scenario", "prompt", "resolution", "aspect_ratio", "duration", "audio", "nsfw_checker", "seed"}
    recipe = {key: value for key, value in plan["recipe"].items() if key in allowed}
    if own_request:
        recipe.update({key: value for key, value in own_request.items() if key in allowed and key != "scenario"})
    draft = Wan3PrimeDraft(**recipe)
    draft.source_feed_gen_id = plan.get("source_feed_gen_id")
    draft.trend_id = plan.get("trend_id")
    draft.repeat_plan_hash = plan["repeat_plan_hash"]
    draft.repeat_slots = plan["slots"]
    draft.repeat_replacements = dict((own_request or {}).get("repeat_replacements") or {})
    return draft


@router.callback_query(F.data.startswith("wan3_repeat:"))
async def open_wan3_shared_repeat(callback: types.CallbackQuery, state: FSMContext):
    runtime = await _runtime()
    try:
        plan = await runtime.repeat_plan_telegram_wan3_prime(telegram_id=callback.from_user.id, source_id=int(str(callback.data).split(":", 1)[1]))
        await _show_dashboard(callback.message, state, _draft_from_repeat_plan(plan))
        await callback.answer()
    except (ValueError, RuntimeError):
        await callback.answer("Повтор больше недоступен", show_alert=True)


@router.callback_query(F.data.startswith("wan3_repeat_slot:"))
async def ask_wan3_repeat_slot(callback: types.CallbackQuery, state: FSMContext):
    draft = draft_from_state(await state.get_data())
    key = str(callback.data).split(":", 1)[1]
    slot = next((item for item in draft.repeat_slots if item["key"] == key and item["binding"] == "upload"), None)
    if not slot:
        await callback.answer("Это место нельзя заменить", show_alert=True)
        return
    await state.update_data(wan3_repeat_slot_key=key)
    await state.set_state(Wan3PrimeStates.waiting_repeat_input)
    await callback.message.edit_text("Пришлите ваш материал для " + _repeat_slot_label(slot) + ". Новый файл заменит предыдущий в этом месте.",
        reply_markup=_keyboard([[("Назад", "wan3_dashboard")]]), parse_mode=None)
    await callback.answer()


@router.message(Wan3PrimeStates.waiting_repeat_input)
async def receive_wan3_repeat_slot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    draft = draft_from_state(data)
    slot = next((item for item in draft.repeat_slots if item["key"] == data.get("wan3_repeat_slot_key") and item["binding"] == "upload"), None)
    if not slot:
        await _show_dashboard(message, state, draft)
        return
    try:
        url = await _store_or_import_media(message, draft, slot["kind"])
    except (ValueError, RuntimeError) as exc:
        await message.answer(str(exc), parse_mode=None)
        return
    draft.repeat_replacements[slot["key"]] = url
    invalidate_quote(draft)
    await _show_dashboard(message, state, draft)


@router.callback_query(F.data.startswith("wan3_trend:"))
async def open_wan3_curated_trend(callback: types.CallbackQuery, state: FSMContext):
    runtime = await _runtime()
    try:
        plan = await runtime.trend_plan_telegram_wan3_prime(telegram_id=callback.from_user.id, trend_id=int(str(callback.data).split(":", 1)[1]))
        await _show_dashboard(callback.message, state, _draft_from_repeat_plan(plan))
        await callback.answer()
    except (ValueError, RuntimeError):
        await callback.answer("Тренд больше недоступен", show_alert=True)
