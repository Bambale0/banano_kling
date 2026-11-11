"""Validated, immutable actor for the common VK / Telegram Mini App.

A platform identity is not a Telegram user. The shared account UUID maps
optional links, whereas platform+external_id selects the authoritative
platform wallet, tasks and delivery. Callers must never manufacture the
other platform's user ID to satisfy a legacy database field.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import AuthenticationError
from .policy import load_policy
from .store import get_session, linked_platforms, linked_telegram_id

Platform = Literal['vk', 'telegram']


@dataclass(frozen=True, slots=True)
class PlatformActor:
    platform: Platform
    external_id: int
    shared_account_id: str
    linked_platforms: tuple[str, ...]
    linked_telegram_id: int | None

    @property
    def account_id(self) -> str:
        return self.shared_account_id

    @property
    def wallet_platform(self) -> Platform:
        """Route by the verified launch platform, NOT optional account links."""
        return self.platform

    @property
    def owner_key(self) -> str:
        return f'{self.platform}:{self.external_id}'

    def payload(self) -> dict:
        return {
            'id': self.shared_account_id,
            'identity': {'platform': self.platform, 'external_id': self.external_id},
        }


async def resolve_platform_actor(
    session_token: str, *, expected_platform: Platform | None = None,
) -> PlatformActor:
    """Resolve a signed, policy-scoped, unexpired, non-revoked session.

    This never creates a users row and never derives a synthetic Telegram ID
    from the VK external ID (even if both platforms use the same integer).
    """
    policy = await load_policy()
    if not policy.enabled:
        raise PermissionError('Account access unavailable')
    account = await get_session(session_token, policy.revision)
    identity = account.identity
    if not policy.allows_public(identity):
        raise PermissionError('Account access unavailable')
    if identity.platform not in ('telegram', 'vk'):
        raise AuthenticationError('Unsupported platform')
    if expected_platform and identity.platform != expected_platform:
        raise PermissionError('Wrong platform')
    platforms = tuple(await linked_platforms(account.id))
    legacy_telegram_id = await linked_telegram_id(account.id)
    return PlatformActor(
        platform=identity.platform,
        external_id=identity.external_id,
        shared_account_id=account.id,
        linked_platforms=platforms,
        linked_telegram_id=legacy_telegram_id,
    )
