"""Typed preview controls stored in the existing audited administrator surface."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from uuid import uuid4

from bot import db as db_backend
from bot.config import config

from .auth import VerifiedIdentity, external_id
from .errors import AuthenticationError, PreviewConflict
from .schema import ensure_schema

POLICY_KEY = 'shared_accounts.preview'


@dataclass(frozen=True)
class PreviewPolicy:
    enabled: bool = False
    revision: int = 0
    vk_app_id: int | None = None
    vk_admin_ids: tuple[int, ...] = ()
    session_ttl_seconds: int = 3600
    launch_max_age_seconds: int = 600
    link_ttl_seconds: int = 600

    @classmethod
    def parse(cls, raw: dict) -> PreviewPolicy:
        if not isinstance(raw, dict) or set(raw) - {f.name for f in fields(cls)}:
            raise ValueError('Invalid preview settings')
        data = asdict(cls()) | raw
        if type(data['enabled']) is not bool:
            raise ValueError('Enabled must be boolean')
        for key, lower, upper in [('revision', 0, 2**63 - 1), ('session_ttl_seconds', 60, 86400), ('launch_max_age_seconds', 60, 86400), ('link_ttl_seconds', 60, 86400)]:
            if type(data[key]) is not int or not lower <= data[key] <= upper:
                raise ValueError(f'Invalid {key}')
        try:
            if data['vk_app_id'] is not None:
                data['vk_app_id'] = external_id(data['vk_app_id'])
            admins = data['vk_admin_ids']
            if not isinstance(admins, (list, tuple)) or len(admins) > 100:
                raise ValueError('Invalid VK administrator list')
            data['vk_admin_ids'] = tuple(sorted({external_id(value) for value in admins}))
        except AuthenticationError as exc:
            raise ValueError('Invalid configured VK identity') from exc
        return cls(**data)

    def allows(self, identity: VerifiedIdentity) -> bool:
        # This is a hard administrator ceiling, not a public rollout switch.
        if not self.enabled:
            return False
        if identity.platform == 'telegram':
            return config.is_admin(identity.external_id)
        return identity.platform == 'vk' and identity.external_id in self.vk_admin_ids

    def payload(self) -> dict:
        return asdict(self)


async def load_policy() -> PreviewPolicy:
    # No process cache: disabling preview or removing a VK administrator revokes
    # access on the next request, even for an otherwise unexpired session.
    async with db_backend.connect() as db:
        row = await (await db.execute('SELECT value FROM bot_settings WHERE key = ?', (POLICY_KEY,))).fetchone()
    return PreviewPolicy.parse(json.loads(row[0])) if row else PreviewPolicy()


async def save_policy(actor_telegram_id: int, changes: dict, expected_revision: int) -> PreviewPolicy:
    if not config.is_admin(actor_telegram_id):
        raise PermissionError('Administrator access required')
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('Invalid expected revision')
    if not isinstance(changes, dict) or 'revision' in changes:
        raise ValueError('Revision is managed by the server')
    async with db_backend.connect() as db:
        await ensure_schema(db)
        if not db_backend.is_postgres():
            await db.execute('BEGIN IMMEDIATE')
        try:
            await db.execute('INSERT INTO bot_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING',
                             (POLICY_KEY, json.dumps(PreviewPolicy().payload())))
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            row = await (await db.execute('SELECT value FROM bot_settings WHERE key = ?' + suffix, (POLICY_KEY,))).fetchone()
            before = PreviewPolicy.parse(json.loads(row[0]))
            if before.revision != expected_revision:
                raise PreviewConflict('Settings changed; reload before saving')
            after = PreviewPolicy.parse(before.payload() | changes | {'revision': before.revision + 1})
            await db.execute('UPDATE bot_settings SET value = ?, updated_by_telegram_id = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?',
                             (json.dumps(after.payload()), actor_telegram_id, POLICY_KEY))
            await db.execute('INSERT INTO shared_account_policy_audit(id, actor_telegram_id, before_state, after_state) VALUES (?, ?, ?, ?)',
                             (uuid4().hex, actor_telegram_id, json.dumps(before.payload()), json.dumps(after.payload())))
            await db.commit()
            return after
        except Exception:
            await db.rollback()
            raise
