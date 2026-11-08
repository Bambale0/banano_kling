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
VK_DELIVERY_KEY = 'shared_accounts.vk_delivery'
VK_DELIVERY_FIELDS = frozenset({'vk_community_id', 'vk_result_delivery_enabled', 'vk_delivery_max_attempts',
                                'vk_delivery_retry_seconds', 'vk_result_message_template'})


class VKDeliveryConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PreviewPolicy:
    enabled: bool = False
    revision: int = 0
    vk_app_id: int | None = None
    vk_admin_ids: tuple[int, ...] = ()
    session_ttl_seconds: int = 3600
    launch_max_age_seconds: int = 600
    link_ttl_seconds: int = 600
    vk_community_id: int | None = None
    vk_result_delivery_enabled: bool = False
    vk_delivery_max_attempts: int = 3
    vk_delivery_retry_seconds: int = 30
    vk_result_message_template: str = '✅ Результат готов!\n\n{result_url}\n\nID: {task_id}'

    @classmethod
    def parse(cls, raw: dict) -> PreviewPolicy:
        if not isinstance(raw, dict) or set(raw) - {f.name for f in fields(cls)}:
            raise ValueError('Invalid preview settings')
        data = asdict(cls()) | raw
        if type(data['enabled']) is not bool or type(data['vk_result_delivery_enabled']) is not bool:
            raise ValueError('Enabled must be boolean')
        for key, lower, upper in [('revision', 0, 2**63 - 1), ('session_ttl_seconds', 60, 86400), ('launch_max_age_seconds', 60, 86400), ('link_ttl_seconds', 60, 86400)]:
            if type(data[key]) is not int or not lower <= data[key] <= upper:
                raise ValueError(f'Invalid {key}')
        for key, upper in [('vk_delivery_max_attempts', 10), ('vk_delivery_retry_seconds', 3600)]:
            if type(data[key]) is not int or not 1 <= data[key] <= upper:
                raise ValueError(f'Invalid {key}')
        template = data['vk_result_message_template']
        if not isinstance(template, str) or not 1 <= len(template) <= 1024:
            raise ValueError('Invalid VK result template')
        from string import Formatter

        template_fields = set()
        for _literal, name, spec, conversion in Formatter().parse(template):
            if name is not None and (name not in {'result_url', 'task_id'} or spec or conversion):
                raise ValueError('Invalid VK result template field')
            if name is not None:
                template_fields.add(name)
        if 'result_url' not in template_fields:
            raise ValueError('VK result template must include result URL')
        try:
            if data['vk_app_id'] is not None:
                data['vk_app_id'] = external_id(data['vk_app_id'])
            if data['vk_community_id'] is not None:
                data['vk_community_id'] = external_id(data['vk_community_id'])
            admins = data['vk_admin_ids']
            if not isinstance(admins, (list, tuple)) or len(admins) > 100:
                raise ValueError('Invalid VK administrator list')
            data['vk_admin_ids'] = tuple(sorted({external_id(value) for value in admins}))
        except AuthenticationError as exc:
            raise ValueError('Invalid configured VK identity') from exc
        if data['vk_result_delivery_enabled'] and data['vk_community_id'] is None:
            raise ValueError('VK community is required for result delivery')
        return cls(**data)

    def is_administrator(self, identity: VerifiedIdentity) -> bool:
        """Platform-scoped role, independent of user-session admission.

        Linking accounts or admitting a broader audience must never grant the
        signed-in identity access to preview financial/commerce administration.
        """
        if identity.platform == 'telegram':
            return config.is_admin(identity.external_id)
        return identity.platform == 'vk' and identity.external_id in self.vk_admin_ids

    def allows(self, identity: VerifiedIdentity) -> bool:
        # Admission remains administrator-only until the full public release.
        return self.enabled and self.is_administrator(identity)

    def payload(self) -> dict:
        return asdict(self)

    def auth_payload(self) -> dict:
        # Old releases reject unknown auth keys. Keep additive delivery controls
        # in their own row while sharing this policy's revision/audit transaction.
        return {key: value for key, value in self.payload().items() if key not in VK_DELIVERY_FIELDS}

    def vk_delivery_payload(self) -> dict:
        return {key: value for key, value in self.payload().items() if key in VK_DELIVERY_FIELDS}


def _read_policy(auth_raw: str, vk_raw: str) -> PreviewPolicy:
    auth, delivery = json.loads(auth_raw), json.loads(vk_raw)
    if not isinstance(auth, dict) or not isinstance(delivery, dict) or set(delivery) - VK_DELIVERY_FIELDS:
        raise ValueError('Invalid stored preview settings')
    return PreviewPolicy.parse(auth | delivery)


async def load_policy() -> PreviewPolicy:
    # No process cache: disabling preview or removing a VK administrator revokes
    # access on the next request, even for an otherwise unexpired session.
    async with db_backend.connect() as db:
        rows = await (await db.execute('SELECT key, value FROM bot_settings WHERE key IN (?, ?)', (POLICY_KEY, VK_DELIVERY_KEY))).fetchall()
    saved = {row[0]: row[1] for row in rows}
    return _read_policy(saved.get(POLICY_KEY, '{}'), saved.get(VK_DELIVERY_KEY, '{}'))


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
                             (POLICY_KEY, json.dumps(PreviewPolicy().auth_payload())))
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            row = await (await db.execute('SELECT value FROM bot_settings WHERE key = ?' + suffix, (POLICY_KEY,))).fetchone()
            vk_row = await (await db.execute('SELECT value FROM bot_settings WHERE key = ?', (VK_DELIVERY_KEY,))).fetchone()
            before = _read_policy(row[0], vk_row[0] if vk_row else '{}')
            if before.revision != expected_revision:
                raise PreviewConflict('Settings changed; reload before saving')
            after = PreviewPolicy.parse(before.payload() | changes | {'revision': before.revision + 1})
            if after.vk_result_delivery_enabled and (not before.vk_result_delivery_enabled or after.vk_community_id != before.vk_community_id):
                from bot.services.vk_result_transport import VKResultTransport

                if not VKResultTransport.configured_for(after.vk_community_id):
                    raise VKDeliveryConfigurationError('VK community sender is not configured')
            await db.execute('UPDATE bot_settings SET value = ?, updated_by_telegram_id = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?',
                             (json.dumps(after.auth_payload()), actor_telegram_id, POLICY_KEY))
            await db.execute('''INSERT INTO bot_settings(key, value, updated_by_telegram_id) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                updated_by_telegram_id = excluded.updated_by_telegram_id, updated_at = CURRENT_TIMESTAMP''',
                (VK_DELIVERY_KEY, json.dumps(after.vk_delivery_payload()), actor_telegram_id))
            await db.execute('INSERT INTO shared_account_policy_audit(id, actor_telegram_id, before_state, after_state) VALUES (?, ?, ?, ?)',
                             (uuid4().hex, actor_telegram_id, json.dumps(before.payload()), json.dumps(after.payload())))
            await db.commit()
            return after
        except Exception:
            await db.rollback()
            raise
