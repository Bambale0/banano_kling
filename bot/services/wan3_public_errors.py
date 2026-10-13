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
