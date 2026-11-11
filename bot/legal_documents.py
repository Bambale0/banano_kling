"""Public legal document helpers shared by Telegram handlers."""

import asyncio
import pathlib
import urllib.parse

from aiogram.exceptions import TelegramRetryAfter

_DOCUMENT_NAMES = {
    "offer": "ofert.md",
    "privacy": "privacy_policy.md",
}
_DOCUMENT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "static"


def document_text(kind: str) -> str:
    """Return an approved local legal text; never expose an empty document."""
    filename = _DOCUMENT_NAMES[kind]
    text = (_DOCUMENT_ROOT / filename).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Empty legal document: {kind}")
    return text


def https_document_url(value: str | None) -> str | None:
    """Only expose valid HTTPS destinations in external legal links."""
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme.lower() == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
    except ValueError:
        return None
    return None


def telegram_text_parts(text: str, *, max_utf16_units: int = 3800) -> list[str]:
    """Split plain text without exceeding Telegram's UTF-16 message limit.

    This intentionally preserves every character, including newlines.
    The handler sends these parts with parse_mode=None, so HTML in legal
    documents is never interpreted as Telegram markup.
    """
    if max_utf16_units < 2:
        raise ValueError("max_utf16_units must be at least 2")
    source = str(text or "")
    if not source.strip():
        return []
    parts: list[str] = []
    chars: list[str] = []
    units = 0
    for char in source:
        char_units = 2 if ord(char) > 0xFFFF else 1
        if units + char_units > max_utf16_units:
            parts.append("".join(chars))
            chars = []
            units = 0
        chars.append(char)
        units += char_units
    if chars:
        parts.append("".join(chars))
    return parts


async def send_legal_parts(
    message,
    parts: list[str],
    reply_markup,
    *,
    pause_seconds: float = 1.1,
    max_flood_retries: int = 2,
) -> None:
    """Deliver all parts in order without flooding a Telegram private chat.

    Telegram permits only a limited per-chat message rate. A full ~68 KB offer
    is a multi-message operation; keep the first answer immediate and pace
    later parts. Retry only explicit Telegram rate limits (not ambiguous
    network errors, which could already have delivered a part).
    """
    if not parts:
        raise ValueError("Legal document has no content")
    for index, part in enumerate(parts):
        if index:
            await asyncio.sleep(pause_seconds)
        for attempt in range(max_flood_retries + 1):
            try:
                await message.answer(
                    part,
                    reply_markup=reply_markup if index == len(parts) - 1 else None,
                    parse_mode=None,
                )
                break
            except TelegramRetryAfter as exc:
                if attempt == max_flood_retries:
                    raise
                await asyncio.sleep(max(float(exc.retry_after), 0.1) + 0.2)
