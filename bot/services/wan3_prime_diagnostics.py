"""Private operator diagnostics with credentials and reference URLs removed."""
import re

from bot.config import config
from bot.utils.user_facing_errors import sanitize_provider_log_payload


def provider_failure_reason(message: str) -> str:
    try:
        text = str(sanitize_provider_log_payload(str(message or '')[:8000]))
    except (ValueError, TypeError, RecursionError):
        return 'Provider rejected generation; diagnostic payload could not be sanitized'
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [redacted]', text)
    text = re.sub(r'(?i)((?:api[-_ ]?key|token|secret|authorization)\s*[:=]\s*)\S+', r'\1[redacted]', text)
    for secret in (config.KIE_AI_API_KEY, config.KIE_WEBHOOK_HMAC_KEY):
        if secret and len(secret) >= 8:
            text = text.replace(secret, '[redacted]')
    return ' '.join(text.split())[:2000] or 'Provider generation failed'
