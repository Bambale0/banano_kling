"""Validated, immutable promo payloads and resumable Telegram delivery.

The same frozen Bot API parts are used for administrator tests and campaigns.
Telegram has no send idempotency key: an in-flight part without a receipt is
uncertain and must never be replayed automatically.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, ClassVar

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramServerError,
)

from bot.miniapp_links import prompt_link

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 60
SaveProgress = Callable[[list[dict[str, Any]]], Awaitable[None]]


class PromoMessageValidationError(ValueError):
    pass


class DeliveryPartError(Exception):
    def __init__(self, kind: str, error_code: str, retry_after: int | None = None):
        self.kind = kind
        self.error_code = error_code
        self.retry_after = retry_after
        super().__init__(f"{kind}: {error_code}")


class DeliveryLeaseLost(Exception):
    """Ownership changed or expired; no further network call is safe."""


@dataclass(frozen=True)
class SendResult:
    message_id: int
    message_ids: list[int]


class _TelegramHTML(HTMLParser):
    TAGS: ClassVar[set[str]] = {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "span",
        "tg-spoiler",
        "a",
        "code",
        "pre",
        "blockquote",
        "tg-emoji",
    }

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.visible: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.TAGS:
            raise PromoMessageValidationError("message.text contains unsupported HTML")
        allowed = {
            "a": {"href"},
            "span": {"class"},
            "code": {"class"},
            "blockquote": {"expandable"},
            "tg-emoji": {"emoji-id"},
        }.get(tag, set())
        if any(key not in allowed for key, _ in attrs):
            raise PromoMessageValidationError(
                "message.text contains unsupported HTML attributes"
            )
        if tag == "span" and dict(attrs).get("class") != "tg-spoiler":
            raise PromoMessageValidationError("HTML span must be a tg-spoiler")
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise PromoMessageValidationError(
                "message.text contains duplicate HTML attributes"
            )
        if tag == "a" and not attributes.get("href"):
            raise PromoMessageValidationError("HTML links require href")
        if tag == "tg-emoji" and not str(attributes.get("emoji-id", "")).isdigit():
            raise PromoMessageValidationError("HTML custom emoji requires emoji-id")
        if (
            tag == "code"
            and attributes.get("class")
            and (not self.stack or self.stack[-1] != "pre")
        ):
            raise PromoMessageValidationError("HTML code language requires pre")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise PromoMessageValidationError("message.text has unbalanced HTML")

    def handle_startendtag(self, tag, attrs):
        raise PromoMessageValidationError(
            "message.text contains unsupported self-closing HTML"
        )

    def handle_data(self, data):
        if any(character in data for character in "<>&"):
            raise PromoMessageValidationError("HTML text must escape <, > and &")
        self.visible.append(data)

    def handle_entityref(self, name):
        entities = {"lt": "<", "gt": ">", "amp": "&", "quot": '"'}
        if name not in entities:
            raise PromoMessageValidationError(
                "message.text contains unsupported HTML entity"
            )
        self.visible.append(entities[name])

    def handle_charref(self, name):
        try:
            value = int(name[1:], 16) if name.lower().startswith("x") else int(name)
            if value <= 0 or 0xD800 <= value <= 0xDFFF:
                raise ValueError("invalid character")
            self.visible.append(chr(value))
        except (ValueError, OverflowError) as exc:
            raise PromoMessageValidationError(
                "message.text contains invalid HTML entity"
            ) from exc

    def handle_pi(self, data):
        raise PromoMessageValidationError(
            "message.text contains unsupported HTML instruction"
        )

    def handle_comment(self, data):
        raise PromoMessageValidationError(
            "message.text contains unsupported HTML comments"
        )

    def handle_decl(self, decl):
        raise PromoMessageValidationError(
            "message.text contains unsupported HTML declarations"
        )


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise PromoMessageValidationError(f"{field} must be a positive integer")
    return value


def normalize_message(value: Any, *, allow_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromoMessageValidationError("message must be an object")
    allowed = {
        "schema_version",
        "text",
        "parse_mode",
        "media",
        "buttons",
        "disable_web_page_preview",
    }
    if set(value) - allowed:
        raise PromoMessageValidationError("message contains unsupported fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 2:
        raise PromoMessageValidationError("message.schema_version must be 2")
    text = value.get("text", "")
    if not isinstance(text, str):
        raise PromoMessageValidationError("message.text must be a string")
    parse_mode = value.get("parse_mode")
    if parse_mode not in (None, "HTML"):
        raise PromoMessageValidationError("message.parse_mode must be null or HTML")
    preview = value.get("disable_web_page_preview", True)
    if type(preview) is not bool:
        raise PromoMessageValidationError("disable_web_page_preview must be boolean")
    raw_media = value.get("media", [])
    if not isinstance(raw_media, list) or len(raw_media) > 10:
        raise PromoMessageValidationError("message.media supports at most 10 items")
    media = []
    for item in raw_media:
        if not isinstance(item, Mapping) or set(item) != {"type", "file_id"}:
            raise PromoMessageValidationError(
                "media items require only type and file_id"
            )
        if item["type"] not in ("photo", "video"):
            raise PromoMessageValidationError("media type must be photo or video")
        file_id = item["file_id"]
        if not isinstance(file_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,1024}", file_id
        ):
            raise PromoMessageValidationError(
                "media.file_id must be a Telegram file ID"
            )
        media.append({"type": item["type"], "file_id": file_id})
    raw_buttons = value.get("buttons", [])
    if not isinstance(raw_buttons, list) or len(raw_buttons) > 2:
        raise PromoMessageValidationError("message.buttons supports at most 2 buttons")
    buttons = []
    for item in raw_buttons:
        if not isinstance(item, Mapping) or set(item) != {
            "position",
            "text",
            "action",
            "trend_id",
        }:
            raise PromoMessageValidationError(
                "buttons require position, text, action and trend_id"
            )
        position = _positive_int(item["position"], "button.position")
        trend_id = _positive_int(item["trend_id"], "button.trend_id")
        label = item["text"]
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 64:
            raise PromoMessageValidationError(
                "button.text must contain 1 to 64 characters"
            )
        if item["action"] != "trend":
            raise PromoMessageValidationError("button.action must be trend")
        buttons.append(
            {
                "position": position,
                "text": label.strip(),
                "action": "trend",
                "trend_id": trend_id,
            }
        )
    buttons.sort(key=lambda item: item["position"])
    if [item["position"] for item in buttons] != list(range(1, len(buttons) + 1)):
        raise PromoMessageValidationError(
            "button positions must be unique and consecutive from 1"
        )
    if not allow_empty and not text.strip() and len(media) != 1:
        raise PromoMessageValidationError(
            "message.text is required for text and album promos"
        )
    visible = text
    if parse_mode == "HTML":
        if re.search(r"&(?!lt;|gt;|amp;|quot;|#[0-9]+;|#[xX][0-9A-Fa-f]+;)", text):
            raise PromoMessageValidationError(
                "message.text contains invalid HTML entity"
            )
        parser = _TelegramHTML()
        parser.feed(text)
        parser.close()
        if parser.stack:
            raise PromoMessageValidationError("message.text has unbalanced HTML")
        visible = "".join(parser.visible)
        if text and not visible.strip():
            raise PromoMessageValidationError("message.text must contain visible text")
    maximum = 1024 if len(media) == 1 else 4096
    if len(visible.encode("utf-16-le")) // 2 > maximum:
        raise PromoMessageValidationError(
            f"message text exceeds Telegram limit of {maximum}"
        )
    return {
        "schema_version": 2,
        "text": text,
        "parse_mode": parse_mode,
        "media": media,
        "buttons": buttons,
        "disable_web_page_preview": preview,
    }


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_message_snapshot(
    message: Mapping[str, Any], bot_username: str | None
) -> dict[str, Any]:
    normalized = normalize_message(message)
    username = str(bot_username or "").strip().lstrip("@")
    if normalized["buttons"] and not re.fullmatch(r"[A-Za-z0-9_]+", username):
        raise PromoMessageValidationError(
            "a verified bot username is required for trend buttons"
        )
    keyboard = None
    if normalized["buttons"]:
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": button["text"],
                        "url": prompt_link(username, button["trend_id"]),
                    }
                ]
                for button in normalized["buttons"]
            ]
        }
    media = normalized["media"]
    text = normalized["text"]
    parse_mode = normalized["parse_mode"]
    parts = []
    if len(media) >= 2:
        parts.append(
            {
                "method": "send_media_group",
                "kwargs": {
                    "media": [
                        {
                            "type": item["type"],
                            "media": item["file_id"],
                            "parse_mode": None,
                        }
                        for item in media
                    ]
                },
            }
        )
    if len(media) == 1:
        item = media[0]
        parts.append(
            {
                "method": f"send_{item['type']}",
                "kwargs": {
                    item["type"]: item["file_id"],
                    "caption": text or None,
                    "parse_mode": parse_mode if text else None,
                    "reply_markup": keyboard,
                },
            }
        )
    else:
        parts.append(
            {
                "method": "send_message",
                "kwargs": {
                    "text": text,
                    "parse_mode": parse_mode,
                    "reply_markup": keyboard,
                    "disable_web_page_preview": normalized["disable_web_page_preview"],
                },
            }
        )
    body = {"schema_version": 2, "message": normalized, "parts": parts}
    return {**body, "bot_username": username, "content_hash": _hash(body)}


def validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise PromoMessageValidationError("message snapshot must be an object")
    expected = build_message_snapshot(
        snapshot.get("message", {}), snapshot.get("bot_username")
    )
    if snapshot != expected:
        raise PromoMessageValidationError(
            "message snapshot does not match its content hash"
        )
    return copy.deepcopy(expected)


async def send_snapshot_part(
    bot: Any, telegram_id: int, part: Mapping[str, Any]
) -> list[int]:
    """Use exactly the frozen payload, adding only the recipient."""
    method = part["method"]
    if method not in {"send_message", "send_photo", "send_video", "send_media_group"}:
        raise PromoMessageValidationError("unsupported snapshot method")
    started = time.monotonic()
    result = await asyncio.wait_for(
        getattr(bot, method)(chat_id=telegram_id, **copy.deepcopy(part["kwargs"])),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    results = result if isinstance(result, list) else [result]
    expected = len(part["kwargs"]["media"]) if method == "send_media_group" else 1
    if len(results) != expected:
        raise DeliveryPartError("uncertain", "invalid_receipt_count")
    try:
        ids = [
            _positive_int(result.message_id, "telegram_message_id")
            for result in results
        ]
    except (AttributeError, ValueError) as exc:
        raise DeliveryPartError("uncertain", "invalid_receipt") from exc
    logger.info(
        "Notification Telegram part sent; telegram_id=%s method=%s duration_ms=%.1f "
        "message_count=%s telegram_message_ids=%s",
        telegram_id,
        method,
        (time.monotonic() - started) * 1000,
        len(ids),
        ids,
    )
    return ids


def classify_delivery_error(error: Exception) -> DeliveryPartError:
    if isinstance(error, DeliveryPartError):
        return error
    # Store codes only: exception descriptions can include URLs or credentials.
    code = type(error).__name__
    if isinstance(error, TelegramRetryAfter):
        return DeliveryPartError("retryable", code, max(1, int(error.retry_after)))
    if isinstance(error, TelegramForbiddenError):
        return DeliveryPartError("blocked", code)
    if isinstance(error, TelegramBadRequest):
        if any(
            marker in str(error).lower()
            for marker in ("chat not found", "user is deactivated", "bot was blocked")
        ):
            return DeliveryPartError("blocked", code)
        return DeliveryPartError("terminal", code)
    if isinstance(error, TelegramServerError):
        # Telegram does not guarantee that an HTTP 5xx means send was rejected.
        # Without an idempotency key, replay could duplicate an accepted album.
        return DeliveryPartError("uncertain", code)
    # Timeouts, connection loss, unknown failures: Telegram may have accepted it.
    return DeliveryPartError("uncertain", code)


async def deliver_message_snapshot(
    bot: Any,
    telegram_id: int,
    snapshot: Mapping[str, Any],
    *,
    delivery_parts: list[dict[str, Any]],
    save_progress: SaveProgress,
) -> SendResult:
    frozen = validate_snapshot(snapshot)
    descriptors = frozen["parts"]
    if not isinstance(delivery_parts, list):
        raise DeliveryPartError("uncertain", "invalid_progress")
    progress = copy.deepcopy(delivery_parts)
    if progress and len(progress) != len(descriptors):
        raise DeliveryPartError("uncertain", "progress_snapshot_mismatch")
    if not progress:
        progress = [
            {
                "index": index,
                "part_hash": _hash(part),
                "status": "pending",
                "message_ids": [],
                "attempts": 0,
            }
            for index, part in enumerate(descriptors)
        ]
    # Validate all progress atomically before the first side effect.
    for index, (state, part) in enumerate(zip(progress, descriptors)):
        if (
            not isinstance(state, dict)
            or state.get("index") != index
            or state.get("part_hash") != _hash(part)
        ):
            raise DeliveryPartError("uncertain", "progress_snapshot_mismatch")
        status = state.get("status")
        if status in {"sending", "uncertain"}:
            raise DeliveryPartError("uncertain", "unconfirmed_previous_attempt")
        if status in {"blocked", "terminal"}:
            raise DeliveryPartError(
                status, state.get("error_code", "terminal_previous_attempt")
            )
        if status not in {"sent", "pending", "retryable"}:
            raise DeliveryPartError("uncertain", "invalid_part_status")
        ids = state.get("message_ids")
        expected = (
            len(part["kwargs"]["media"]) if part["method"] == "send_media_group" else 1
        )
        if status == "sent" and (
            not isinstance(ids, list)
            or len(ids) != expected
            or any(type(item) is not int or item <= 0 for item in ids)
        ):
            raise DeliveryPartError("uncertain", "missing_confirmed_receipt")
        if type(state.get("attempts")) is not int or state["attempts"] < 0:
            raise DeliveryPartError("uncertain", "invalid_part_attempts")
    for state, part in zip(progress, descriptors):
        if state["status"] == "sent":
            continue
        state.update(status="sending", attempts=state["attempts"] + 1, message_ids=[])
        state.pop("error_code", None)
        state.pop("retry_after", None)
        await save_progress(copy.deepcopy(progress))  # Must commit before the API call.
        try:
            ids = await send_snapshot_part(bot, telegram_id, part)
        except asyncio.CancelledError:
            # Persisted "sending" deliberately remains uncertain after restart.
            raise
        except Exception as exc:
            error = classify_delivery_error(exc)
            state.update(status=error.kind, error_code=error.error_code)
            if error.retry_after is not None:
                state["retry_after"] = error.retry_after
            await save_progress(copy.deepcopy(progress))
            raise error from exc
        state.update(status="sent", message_ids=ids)
        # Failure saving a receipt must never trigger an automatic network replay.
        await save_progress(copy.deepcopy(progress))
    ids = [message_id for state in progress for message_id in state["message_ids"]]
    return SendResult(message_id=ids[-1], message_ids=ids)
