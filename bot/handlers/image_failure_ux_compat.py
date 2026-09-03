"""Restore actionable Telegram UX for synchronous image-generation failures.

Some image providers (notably RenderGrid) finish synchronously inside
``_start_image_generation_task``. The legacy handler keeps only ``status=failed``
and the local task id, then shows a generic refund message. Provider reason and
trace id are therefore lost even though they were returned by the adapter.

This compatibility layer keeps billing/provider routing untouched. It captures
terminal provider metadata at the classifier boundary, enriches the launch
result, and replaces the legacy generic Telegram refund message with one
failure card per failed image, including a working retry keyboard.
"""

from __future__ import annotations

import html
from contextvars import ContextVar
from functools import wraps
from typing import Any

from bot.keyboards import get_failed_image_retry_keyboard, get_image_model_label
from bot.utils.user_facing_errors import make_user_friendly_generation_error

_CURRENT_PROVIDER_FAILURE: ContextVar[dict[str, Any] | None] = ContextVar(
    "image_failure_current_provider",
    default=None,
)
_HANDLER_FAILURES: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "image_failure_handler_failures",
    default=None,
)
_HANDLER_LAUNCH_INDEX: ContextVar[int] = ContextVar(
    "image_failure_handler_launch_index",
    default=0,
)

_GENERIC_FAILURE_MARKERS = (
    "Часть вариантов не удалось запустить.",
    "Не получилось запустить генерацию.",
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _provider_failure_details(result: Any, error_message: str | None) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    provider_task_id = _clean(
        payload.get("provider_task_id")
        or payload.get("creation_id")
        or payload.get("provider_id")
    )
    reason = make_user_friendly_generation_error(
        error_message
        or payload.get("message")
        or payload.get("error")
        or payload.get("detail")
    )
    return {
        "provider_task_id": provider_task_id,
        "provider": _clean(payload.get("provider")),
        "provider_model": _clean(payload.get("provider_model")),
        "reason": reason or "Сервис генерации не вернул готовый результат.",
    }


def build_image_failure_text(failure: dict[str, Any]) -> str:
    """Build the public failure card used for a failed image variant."""

    local_task_id = _clean(
        failure.get("local_task_id") or failure.get("task_id")
    )
    provider_task_id = _clean(failure.get("provider_task_id"))
    img_service = _clean(failure.get("img_service")) or "AI"
    model_label = get_image_model_label(img_service)
    reason = make_user_friendly_generation_error(failure.get("reason")) or (
        "Сервис генерации не вернул готовый результат."
    )

    lines = [
        "❌ <b>Не удалось сгенерировать изображение</b>",
    ]
    attempt_number = failure.get("attempt_number")
    if attempt_number:
        lines.append(f"• Вариант: <code>{html.escape(str(attempt_number))}</code>")
    lines.extend(
        [
            f"• Модель: <code>{html.escape(str(model_label))}</code>",
            f"• ID генерации: <code>{html.escape(local_task_id or '—')}</code>",
        ]
    )
    if provider_task_id and provider_task_id != local_task_id:
        lines.append(
            f"• ID провайдера: <code>{html.escape(provider_task_id)}</code>"
        )
    lines.append(f"• Причина: {html.escape(reason)}")
    lines.extend(
        [
            "",
            "Бананы за эту попытку уже возвращены.",
            "Можно сразу повторить запуск кнопкой ниже.",
        ]
    )
    return "\n".join(lines)


class _FailureMessageProxy:
    def __init__(self, message: Any) -> None:
        self._message = message
        self._failure_cards_sent = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    def model_copy(self, *args: Any, **kwargs: Any) -> "_FailureMessageProxy":
        if hasattr(self._message, "model_copy"):
            return _FailureMessageProxy(self._message.model_copy(*args, **kwargs))
        return self

    async def _send_failure_cards(self) -> Any:
        failures = list(_HANDLER_FAILURES.get() or [])
        if not failures:
            return None
        self._failure_cards_sent = True
        sent = None
        for failure in failures:
            task_id = _clean(
                failure.get("local_task_id") or failure.get("task_id")
            )
            sent = await self._message.answer(
                build_image_failure_text(failure),
                parse_mode="HTML",
                reply_markup=(
                    get_failed_image_retry_keyboard(task_id) if task_id else None
                ),
            )
        return sent

    async def answer(self, text: Any, **kwargs: Any) -> Any:
        if isinstance(text, str) and any(
            marker in text for marker in _GENERIC_FAILURE_MARKERS
        ):
            failures = _HANDLER_FAILURES.get() or []
            if failures:
                if self._failure_cards_sent:
                    return None
                return await self._send_failure_cards()
        return await self._message.answer(text, **kwargs)


def _install_classifier_capture(generation_module: Any) -> None:
    original_classifier = generation_module._classify_image_generation_result
    if getattr(original_classifier, "_image_failure_ux_wrapped", False):
        return

    @wraps(original_classifier)
    def classify_with_failure_capture(result: Any):
        status, error_message = original_classifier(result)
        if status == "failed":
            _CURRENT_PROVIDER_FAILURE.set(
                _provider_failure_details(result, error_message)
            )
        else:
            _CURRENT_PROVIDER_FAILURE.set(None)
        return status, error_message

    classify_with_failure_capture._image_failure_ux_wrapped = True
    generation_module._classify_image_generation_result = classify_with_failure_capture


def _install_launch_enrichment(generation_module: Any) -> None:
    original_start = generation_module._start_image_generation_task
    if getattr(original_start, "_image_failure_ux_wrapped", False):
        return

    @wraps(original_start)
    async def start_with_failure_metadata(*args: Any, **kwargs: Any):
        launch_index = _HANDLER_LAUNCH_INDEX.get() + 1
        _HANDLER_LAUNCH_INDEX.set(launch_index)
        token = _CURRENT_PROVIDER_FAILURE.set(None)
        try:
            launch_result = await original_start(*args, **kwargs)
            if not isinstance(launch_result, dict) or launch_result.get("status") != "failed":
                return launch_result

            provider_failure = dict(_CURRENT_PROVIDER_FAILURE.get() or {})
            enriched = dict(launch_result)
            local_task_id = _clean(
                enriched.get("local_task_id") or enriched.get("task_id")
            )
            enriched["local_task_id"] = local_task_id
            enriched.update(
                {
                    key: value
                    for key, value in provider_failure.items()
                    if value not in (None, "")
                }
            )

            failure = dict(enriched)
            failure["attempt_number"] = launch_index
            failure["img_service"] = _clean(kwargs.get("img_service"))
            failures = _HANDLER_FAILURES.get()
            if failures is not None:
                failures.append(failure)
            return enriched
        finally:
            _CURRENT_PROVIDER_FAILURE.reset(token)

    start_with_failure_metadata._image_failure_ux_wrapped = True
    generation_module._start_image_generation_task = start_with_failure_metadata


def _install_prompt_handler_proxy(generation_module: Any) -> None:
    original_handler = generation_module.handle_image_prompt_text
    if getattr(original_handler, "_image_failure_ux_wrapped", False):
        return

    @wraps(original_handler)
    async def handler_with_failure_cards(message: Any, state: Any):
        failures_token = _HANDLER_FAILURES.set([])
        index_token = _HANDLER_LAUNCH_INDEX.set(0)
        try:
            return await original_handler(_FailureMessageProxy(message), state)
        finally:
            _HANDLER_LAUNCH_INDEX.reset(index_token)
            _HANDLER_FAILURES.reset(failures_token)

    handler_with_failure_cards._image_failure_ux_wrapped = True

    replaced = False
    for handler_object in generation_module.router.message.handlers:
        if handler_object.callback is original_handler:
            handler_object.callback = handler_with_failure_cards
            replaced = True
    if not replaced:
        raise RuntimeError("handle_image_prompt_text is not registered on generation router")

    generation_module.handle_image_prompt_text = handler_with_failure_cards


def install_image_failure_ux(generation_module: Any) -> None:
    """Install detailed failure metadata and Telegram retry cards once."""

    if getattr(generation_module, "_image_failure_ux_compat_installed", False):
        return

    _install_classifier_capture(generation_module)
    _install_launch_enrichment(generation_module)
    _install_prompt_handler_proxy(generation_module)
    generation_module._image_failure_ux_compat_installed = True
