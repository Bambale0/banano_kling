"""Unify user-facing generation lifecycle feedback.

The production generation handlers expose useful trace identifiers and persist
all task states in ``generation_tasks``.  This compatibility layer normalizes
the start summary and attaches a provider-agnostic Telegram progress indicator
to every generation without changing provider, billing or persistence logic.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware

from bot.generation_progress import (
    build_progress_line,
    ensure_progress_line,
    extract_task_ids,
    track_generation_progress,
)

logger = logging.getLogger(__name__)

_GENERATION_STARTED_MARKER = "Генерация запущена"
_STANDALONE_CODE_BULLET_RE = re.compile(r"^\s*•\s*<code>([^<]+)</code>\s*$")
_ETA_VARIANTS = {
    "Обычно результат приходит в течение 1-3 минут.",
    "Обычно результат приходит в течение 1–3 минут.",
}


def _clean_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(number)) if number.is_integer() else str(number)


def build_generation_started_text(
    *,
    model_label: str,
    aspect_ratio: str = "",
    launched_count: int = 1,
    unit_cost: float | None = None,
    reference_count: int | None = None,
    local_task_id: str = "",
    provider_task_id: str = "",
) -> str:
    """Build the single public contract for a successfully launched generation."""

    lines = [
        "🚀 <b>Генерация запущена</b>",
        build_progress_line(),
        "",
        f"• Модель: <code>{html.escape(str(model_label))}</code>",
    ]
    if aspect_ratio:
        lines.append(f"• Формат: <code>{html.escape(str(aspect_ratio))}</code>")
    if reference_count is not None and reference_count > 0:
        lines.append(f"• Референсов: <code>{int(reference_count)}</code>")
    lines.append(f"• Запущено задач: <code>{max(1, int(launched_count))}</code>")
    if unit_cost not in (None, "", 0, 0.0):
        lines.append(f"• Списано: <code>{html.escape(_clean_number(unit_cost))}</code>🍌")

    trace_lines: list[str] = []
    if local_task_id:
        trace_lines.append(f"• ID задачи: <code>{html.escape(str(local_task_id))}</code>")
    if provider_task_id:
        trace_lines.append(
            f"• ID провайдера: <code>{html.escape(str(provider_task_id))}</code>"
        )
    if trace_lines:
        lines.append("")
        lines.extend(trace_lines)

    lines.extend(
        [
            "",
            "Обычно результат приходит в течение 1–3 минут.",
            "Я пришлю его сюда сразу после готовности.",
        ]
    )
    return "\n".join(lines)


def sanitize_generation_started_text(
    text: Any,
    *,
    reference_count: int | None = None,
) -> Any:
    """Normalize the legacy Telegram start summary while preserving trace IDs."""

    if not isinstance(text, str) or _GENERATION_STARTED_MARKER not in text:
        return text

    cleaned: list[str] = []
    has_reference_line = False
    for line in text.splitlines():
        stripped = line.strip()
        task_match = _STANDALONE_CODE_BULLET_RE.fullmatch(stripped)
        if task_match:
            task_id = task_match.group(1)
            line = f"• ID задачи: <code>{task_id}</code>"
        elif stripped.startswith("• ID провайдера:"):
            line = stripped
        if stripped.startswith("• Референсов:"):
            has_reference_line = True
        if stripped in _ETA_VARIANTS:
            line = "Обычно результат приходит в течение 1–3 минут."
        cleaned.append(line)

    if reference_count is not None and reference_count > 0 and not has_reference_line:
        insert_at = next(
            (
                index + 1
                for index, line in enumerate(cleaned)
                if line.strip().startswith("• Формат:")
            ),
            2,
        )
        cleaned.insert(insert_at, f"• Референсов: <code>{int(reference_count)}</code>")

    compact: list[str] = []
    for line in cleaned:
        if not line.strip() and (not compact or not compact[-1].strip()):
            continue
        compact.append(line)
    while compact and not compact[-1].strip():
        compact.pop()

    if not any("Я пришлю его сюда сразу после готовности." in line for line in compact):
        if compact and compact[-1].strip() not in _ETA_VARIANTS and not compact[-1].startswith(
            "Обычно результат приходит"
        ):
            compact.append("")
            compact.append("Обычно результат приходит в течение 1–3 минут.")
        compact.append("Я пришлю его сюда сразу после готовности.")

    return ensure_progress_line("\n".join(compact))


class _FriendlyMessageProxy:
    """Forward a Message unchanged except for generation lifecycle feedback."""

    def __init__(self, message: Any, *, reference_count: int | None = None) -> None:
        self._message = message
        self._reference_count = reference_count

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    def model_copy(self, *args: Any, **kwargs: Any) -> _FriendlyMessageProxy:
        """Keep the UX wrapper when prompt coalescing clones an aiogram Message."""

        cloned = self._message.model_copy(*args, **kwargs)
        return _FriendlyMessageProxy(
            cloned,
            reference_count=self._reference_count,
        )

    async def answer(self, text: Any, **kwargs: Any) -> Any:
        normalized = sanitize_generation_started_text(
            text,
            reference_count=self._reference_count,
        )
        sent = await self._message.answer(normalized, **kwargs)
        if isinstance(normalized, str) and _GENERATION_STARTED_MARKER in normalized:
            task_ids = extract_task_ids(normalized)
            from_user = getattr(self._message, "from_user", None)
            chat = getattr(self._message, "chat", None)
            bot = getattr(self._message, "bot", None)
            message_id = getattr(sent, "message_id", None)
            if task_ids and from_user and chat and bot and message_id:
                track_generation_progress(
                    bot,
                    chat_id=chat.id,
                    message_id=message_id,
                    telegram_id=from_user.id,
                    task_ids=task_ids,
                    text=normalized,
                )
        return sent


Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class GenerationStartedUxMiddleware(BaseMiddleware):
    """Normalize the established Telegram generation summary without changing flow."""

    async def __call__(
        self,
        handler: Handler,
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        reference_count: int | None = None
        state = data.get("state")
        if state is not None:
            try:
                state_data = await state.get_data()
                raw_references = state_data.get("reference_images")
                if isinstance(raw_references, (list, tuple)):
                    reference_count = len(
                        [item for item in raw_references if str(item or "").strip()]
                    )
            except Exception:
                logger.debug("Unable to inspect generation reference count", exc_info=True)

        return await handler(
            _FriendlyMessageProxy(event, reference_count=reference_count),
            data,
        )


def _install_miniapp_started_notifier() -> None:
    import bot.miniapp as miniapp_module

    if getattr(miniapp_module, "_generation_started_ux_notifier_installed", False):
        return

    async def notify_generation_started(
        app: Any,
        telegram_id: int,
        launch_result: dict[str, Any],
        *,
        img_service: str,
        img_ratio: str,
        unit_cost: float,
    ) -> None:
        status = str(launch_result.get("status") or "").strip().lower()
        provider_task_id = str(launch_result.get("task_id") or "").strip()
        local_task_id = str(launch_result.get("local_task_id") or "").strip()
        if status not in {"queued", "done"} or not provider_task_id:
            return

        model_label = miniapp_module.get_image_model_label(img_service)
        text = build_generation_started_text(
            model_label=str(model_label),
            aspect_ratio=img_ratio,
            launched_count=1,
            unit_cost=unit_cost,
            local_task_id=local_task_id,
            provider_task_id=provider_task_id,
        )
        try:
            sent = await app["bot"].send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
            )
            task_ids = [local_task_id, provider_task_id]
            track_generation_progress(
                app["bot"],
                chat_id=telegram_id,
                message_id=sent.message_id,
                telegram_id=telegram_id,
                task_ids=task_ids,
                text=text,
            )
            logger.info(
                "Mini App generation start notified: telegram_id=%s status=%s local_task_id=%s provider_task_id=%s",
                telegram_id,
                status,
                local_task_id,
                provider_task_id,
            )
        except Exception:
            logger.exception(
                "Mini App generation start notification failed: telegram_id=%s local_task_id=%s provider_task_id=%s",
                telegram_id,
                local_task_id,
                provider_task_id,
            )

    miniapp_module._notify_miniapp_image_task_queued = notify_generation_started
    miniapp_module._generation_started_ux_notifier_installed = True


def install_generation_started_ux(generation_module: Any) -> None:
    """Install the Telegram normalizer and Mini App/Pinterest start notifier once."""

    if not getattr(generation_module, "_generation_started_ux_middleware_installed", False):
        generation_module.router.message.middleware(GenerationStartedUxMiddleware())
        generation_module._generation_started_ux_middleware_installed = True

    _install_miniapp_started_notifier()
