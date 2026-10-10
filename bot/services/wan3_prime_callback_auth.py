"""KIE's documented HMAC headers, without secrets in proxy request URLs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from bot.config import config


def nonce_callbacks_enabled() -> bool:
    return os.getenv('WAN3_CALLBACK_QUERY_LOGS_REDACTED') == '1'


def signed_callbacks_enabled() -> bool:
    return bool(config.KIE_WEBHOOK_HMAC_KEY)


def verify_callback_headers(task_id: str, headers) -> bool:
    if not signed_callbacks_enabled() or not headers:
        return False
    timestamp = str(headers.get('X-Webhook-Timestamp') or '')
    signature = str(headers.get('X-Webhook-Signature') or '')
    if not timestamp.isdigit() or len(timestamp) > 12 or len(signature) > 128:
        return False
    if abs(time.time() - int(timestamp)) > 300:
        return False
    digest = hmac.new(config.KIE_WEBHOOK_HMAC_KEY.encode(), f'{task_id}.{timestamp}'.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)
