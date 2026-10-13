"""Keep infrastructure identity out of user-facing WAN messages."""
from __future__ import annotations

import re

_INFRASTRUCTURE = re.compile(r'kie|provider|провайдер|upstream|api[ _-]?key|bearer|https?://', re.IGNORECASE)


def public_wan_error(message: str, *, code: str = '') -> str:
    text = str(message or '')
    if _INFRASTRUCTURE.search(text) or code in {'provider_rejected', 'provider_failed', 'submit_unknown'}:
        return 'Не удалось завершить операцию. Проверьте статус задачи или попробуйте позже.'
    return text


def public_wan_status(payload: dict) -> dict:
    result = {key: value for key, value in payload.items()
              if key not in {'provider_task_id', 'provider_model', 'provider_state'}}
    if result.get('error_message'):
        result['error_message'] = ('Не удалось создать видео. Проверьте статус оплаты.'
                                   if result.get('status') == 'failed' else
                                   'Статус задачи уточняется. Не запускайте её повторно.')
    return result


def log_wan_publication_failure(logger, exc: Exception, *, actor_id: int, telegram_id: int, model: str) -> str:
    """Correlate protected diagnostics without exception text, locals or source lines."""
    from os.path import basename
    from uuid import uuid4

    error_id = uuid4().hex
    stack = []
    cursor = exc.__traceback__
    while cursor is not None:
        code = cursor.tb_frame.f_code
        stack.append(f"{basename(code.co_filename)}:{cursor.tb_lineno}:{code.co_name}")
        cursor = cursor.tb_next
    logger.error(
        "WAN publication failed: error_id=%s actor_id=%s telegram_id=%s model=%s error_type=%s stack=%s",
        error_id, actor_id, telegram_id,
        model if model in {'wan_3', 'wan_3_prime'} else 'unknown',
        type(exc).__name__, stack[-12:],
    )
    return error_id
