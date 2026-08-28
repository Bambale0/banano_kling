"""Unify user-facing confirmation after a generation has actually started.

The production generation handlers historically exposed internal task/provider IDs in
Telegram and the Mini App notifier only spoke for queued tasks. The latter meant fast
provider responses (including Pinterest repeat runs) could complete without any visible
"started" acknowledgement at all.

This compatibility layer keeps provider, billing and persistence logic untouched. It
only normalizes the outbound start message and broadens the Mini App acknowledgement to
all successful launches (queued or already done).
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)

_GENERATION_STARTED_MARKER = "Генерация запущена"
_TECH_PROVIDER_ID_MARKER = "ID провайдера:"
_STANDALONE_CODE_BULLET_RE = re.compile(r"^\s*•\s*<code>[^<]+</code>\s*$")
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
    unit_cost: float | int | None = None,
    reference_count: int | None = None,
) -> str:
    """Build the single public contract for a successfully launched generation."""

    lines = [
        "🚀 <b>Генерация запущена</b>",
        f"• Модель: <code>{html.escape(str(model_label))}</code>",
    ]
    if aspect_ratio:
        lines.append(f"• Формат: <code>{html.escape(str(aspect_ratio))}</code>")
    if reference_count is not None and reference_count > 0:
        lines.append(f"• Референсов: <code>{int(reference_count)}</code>")
    lines.append(f"• Запущено задач: <code>{max(1, int(launched_count))}</code>")
    if unit_cost not in (None, "", 0, 0.0):
        lines.append(f"• Списано: <code>{html.escape(_clean_number(unit_cost))}</code>🍌")
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
    """Remove implementation IDs from the legacy Telegram start summary."""

    if not isinstance(text, str) or _GENERATION_STARTED_MARKER not in text:
        return text

    cleaned: list[str] = []
    has_reference_line = False
    for line in text.splitlines():
        stripped = line.strip()
        if _TECH_PROVIDER_ID_MARKER in stripped:
            continue
        # Legacy image launch summaries print every local task ID as a bare
        # bullet containing only <code>...</code>. Public status text does not
        # need those identifiers; they remain available in DB/logs/admin tools.
        if _STANDALONE_CODE_BULLET_RE.fullmatch(stripped):
            continue
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

    # Collapse the blank block that used to separate user data from task IDs.
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

    return "\n".join(compact)


class _FriendlyMessageProxy:
    """Forward a Message unchanged except for generation-start answer text."""

    def __init__(self, message: Any, *, reference_count: int | None = None) -> None:
        self._message = message
        self._reference_count = reference_count

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    async def answer(self, text: Any, **kwargs: Any) -> Any:
        return await self._message.answer(
            sanitize_generation_started_text(
                text,
                reference_count=self._reference_count,
            ),
            **kwargs,
        )


Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class GenerationStartedUxMiddleware(BaseMiddleware):
    """Sanitize the established Telegram generation summary without changing flow."""

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
        if status not in {"queued", "done"} or not launch_result.get("task_id"):
            return

        model_label = miniapp_module.get_image_model_label(img_service)
        text = build_generation_started_text(
            model_label=str(model_label),
            aspect_ratio=img_ratio,
            launched_count=1,
            unit_cost=unit_cost,
        )
        try:
            await app["bot"].send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
            )
            logger.info(
                "Mini App generation start notified: telegram_id=%s status=%s task_id=%s",
                telegram_id,
                status,
                launch_result.get("task_id"),
            )
        except Exception:
            logger.exception(
                "Mini App generation start notification failed: telegram_id=%s task_id=%s",
                telegram_id,
                launch_result.get("task_id"),
            )

    miniapp_module._notify_miniapp_image_task_queued = notify_generation_started
    miniapp_module._generation_started_ux_notifier_installed = True


def install_generation_started_ux(generation_module: Any) -> None:
    """Install the Telegram sanitizer and Mini App/Pinterest start notifier once."""

    if not getattr(generation_module, "_generation_started_ux_middleware_installed", False):
        generation_module.router.message.middleware(GenerationStartedUxMiddleware())
        generation_module._generation_started_ux_middleware_installed = True

    _install_miniapp_started_notifier()
