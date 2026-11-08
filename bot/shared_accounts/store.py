"""Transactional identities and hashed, revocable signed-user sessions."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from uuid import uuid4

from bot import db as db_backend

from .auth import VerifiedIdentity
from .errors import AuthenticationError
from .schema import ensure_schema


@dataclass(frozen=True)
class Account:
    id: str
    identity: VerifiedIdentity

    def payload(self) -> dict:
        return {'id': self.id, 'identity': {'platform': self.identity.platform, 'external_id': self.identity.external_id}}


def _token_hash(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise AuthenticationError('Invalid session')
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(identity: VerifiedIdentity, ttl_seconds: int, policy_revision: int) -> tuple[Account, str, int]:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires = now + ttl_seconds
    async with db_backend.connect() as db:
        await ensure_schema(db)
        if not db_backend.is_postgres():
            await db.execute('BEGIN IMMEDIATE')
        try:
            # Public sign-in creates short-lived rows. Keep the indexed session
            # table bounded without touching active or unexpired revoked tokens.
            await db.execute(
                'DELETE FROM shared_account_sessions WHERE expires_at_epoch <= ?',
                (now,),
            )
            row = await (await db.execute(
                'SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?',
                (identity.platform, identity.external_id),
            )).fetchone()
            if row:
                account_id = row[0]
            else:
                candidate = uuid4().hex
                await db.execute('INSERT INTO shared_accounts(id) VALUES (?)', (candidate,))
                inserted = await db.execute(
                    'INSERT INTO shared_account_identities(platform, external_id, account_id) VALUES (?, ?, ?) '
                    'ON CONFLICT(platform, external_id) DO NOTHING',
                    (identity.platform, identity.external_id, candidate),
                )
                if inserted.rowcount == 1:
                    account_id = candidate
                else:
                    # Another transaction won the same verified external ID.
                    await db.execute('DELETE FROM shared_accounts WHERE id = ?', (candidate,))
                    row = await (await db.execute(
                        'SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?',
                        (identity.platform, identity.external_id),
                    )).fetchone()
                    account_id = row[0]
            row = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?', (account_id,))).fetchone()
            if not row or row[0] != 'active':
                raise PermissionError('Account is not available')
            if identity.platform == 'telegram':
                legacy = await (await db.execute('SELECT id FROM users WHERE telegram_id = ?', (identity.external_id,))).fetchone()
                if legacy:
                    await db.execute(
                        'INSERT INTO shared_account_legacy_links(source, legacy_user_id, account_id) VALUES (?, ?, ?) '
                        'ON CONFLICT(source, legacy_user_id) DO NOTHING', ('telegram', legacy[0], account_id),
                    )
            await db.execute(
                'INSERT INTO shared_account_sessions '
                '(token_hash, account_id, platform, external_id, created_at_epoch, expires_at_epoch, policy_revision) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (_token_hash(token), account_id, identity.platform, identity.external_id, now, expires, policy_revision),
            )
            await db.commit()
            return Account(account_id, identity), token, expires
        except Exception:
            await db.rollback()
            raise


async def get_session(token: str, policy_revision: int) -> Account:
    digest = _token_hash(token)
    async with db_backend.connect() as db:
        row = await (await db.execute(
            '''SELECT session.account_id, session.platform, session.external_id
               FROM shared_account_sessions session
               JOIN shared_accounts account ON account.id = session.account_id
               JOIN shared_account_identities identity ON identity.platform = session.platform
                 AND identity.external_id = session.external_id AND identity.account_id = session.account_id
               WHERE session.token_hash = ? AND session.revoked_at_epoch IS NULL
                 AND session.expires_at_epoch > ? AND account.status = 'active'
                 AND session.policy_revision = ? ''',
            (digest, int(time.time()), policy_revision),
        )).fetchone()
    if not row:
        raise AuthenticationError('Expired or revoked session')
    return Account(row[0], VerifiedIdentity(row[1], int(row[2])))


async def revoke_session(token: str) -> None:
    async with db_backend.connect() as db:
        await db.execute('UPDATE shared_account_sessions SET revoked_at_epoch = ? WHERE token_hash = ? AND revoked_at_epoch IS NULL',
                         (int(time.time()), _token_hash(token)))
        await db.commit()


async def linked_telegram_id(account_id: str) -> int | None:
    """Resolve the single legacy Telegram identity owned by a shared account."""
    if not isinstance(account_id, str) or not re.fullmatch(r'[0-9a-f]{32}', account_id):
        raise AuthenticationError('Invalid account')
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            '''SELECT users.telegram_id
               FROM shared_account_legacy_links legacy
               JOIN users ON users.id = legacy.legacy_user_id
               WHERE legacy.source = ? AND legacy.account_id = ?
               ORDER BY users.id LIMIT 2''',
            ('telegram', account_id),
        )).fetchall()
    if len(rows) > 1:
        raise AuthenticationError('Ambiguous linked account')
    return int(rows[0][0]) if rows else None


async def linked_platforms(account_id: str) -> list[str]:
    """Read persisted platform membership for an authenticated shared account."""
    if not isinstance(account_id, str) or not re.fullmatch(r'[0-9a-f]{32}', account_id):
        raise AuthenticationError('Invalid account')
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            'SELECT DISTINCT platform FROM shared_account_identities WHERE account_id = ? ORDER BY platform',
            (account_id,),
        )).fetchall()
    return [row[0] for row in rows]
