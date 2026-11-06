"""Verify platform launch credentials without treating external IDs as accounts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

from .errors import AuthenticationError


@dataclass(frozen=True)
class VerifiedIdentity:
    platform: str
    external_id: int


def external_id(value: object) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,18}', value):
        result = int(value)
    else:
        raise AuthenticationError('Invalid external identity')
    if not 0 < result < 2**63:
        raise AuthenticationError('Invalid external identity')
    return result


def _fields(raw: str) -> dict[str, str]:
    if not isinstance(raw, str) or not raw or len(raw) > 16384:
        raise AuthenticationError('Invalid launch credentials')
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
    except ValueError as exc:
        raise AuthenticationError('Invalid launch credentials') from exc
    values = dict(pairs)
    if len(values) != len(pairs):
        raise AuthenticationError('Duplicate launch parameters')
    return values


def _fresh(value: str | None, max_age: int) -> None:
    try:
        timestamp = external_id(value)
    except AuthenticationError as exc:
        raise AuthenticationError('Invalid launch timestamp') from exc
    now = int(time.time())
    if timestamp > now + 60 or now - timestamp > max_age:
        raise AuthenticationError('Expired launch credentials')


def verify_telegram(raw: str, bot_token: str, *, max_age: int) -> VerifiedIdentity:
    fields = _fields(raw)
    received = fields.pop('hash', '')
    if not bot_token or not re.fullmatch('[0-9a-f]{64}', received):
        raise AuthenticationError('Invalid Telegram signature')
    key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    message = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    expected = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthenticationError('Invalid Telegram signature')
    _fresh(fields.get('auth_date'), max_age)
    try:
        user = json.loads(fields.get('user', ''))
        user_id = user['id']
    except (ValueError, TypeError, KeyError) as exc:
        raise AuthenticationError('Missing Telegram identity') from exc
    return VerifiedIdentity('telegram', external_id(user_id))


def verify_vk(raw: str, app_id: int | None, app_secret: str, *, max_age: int) -> VerifiedIdentity:
    fields = _fields(raw)
    received = fields.get('sign', '')
    if not app_id or not app_secret:
        raise AuthenticationError('VK authentication is not configured')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', received):
        raise AuthenticationError('Invalid VK signature')
    signed = {k: v for k, v in fields.items() if k.startswith('vk_')}
    digest = hmac.new(app_secret.encode(), urlencode(sorted(signed.items())).encode(), hashlib.sha256).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    if not hmac.compare_digest(expected, received):
        raise AuthenticationError('Invalid VK signature')
    if external_id(fields.get('vk_app_id')) != app_id:
        raise AuthenticationError('Wrong VK application')
    _fresh(fields.get('vk_ts'), max_age)
    return VerifiedIdentity('vk', external_id(fields.get('vk_user_id')))
