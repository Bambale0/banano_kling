"""Verified identity and product ownership, without platform-role inheritance.

The Telegram legacy link is currently the only supported product-owner proof.
VK legacy IDs belong to a different database and must never be joined to users.
This foundation deliberately cannot create standalone production owners.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot import db as db_backend

from .auth import VerifiedIdentity
from .errors import AuthenticationError
from .store import Account


@dataclass(frozen=True)
class ProductActor:
    account_id: str
    owner_user_id: int | None
    identity: VerifiedIdentity
    telegram_id: int | None

    def require_telegram_owner(self) -> int:
        """Explicit compatibility guard, not authorization or an admin identity."""
        if self.owner_user_id is None or self.telegram_id is None or self.telegram_id <= 0:
            raise AuthenticationError('A linked Telegram product owner is required')
        return self.telegram_id

    def is_administrator(self, policy) -> bool:
        # Ownership/linking never grants another platform's role.
        return policy.is_administrator(self.identity)


async def legacy_product_owner(db, account_id: str) -> tuple[int, int] | None:
    """Read under the caller's account lock; reject corrupt/ambiguous proofs."""
    rows = await (await db.execute(
        '''SELECT legacy.legacy_user_id, users.telegram_id, identity.external_id
           FROM shared_account_legacy_links legacy
           LEFT JOIN users ON users.id = legacy.legacy_user_id
           LEFT JOIN shared_account_identities identity
             ON identity.account_id = legacy.account_id AND identity.platform = 'telegram'
           WHERE legacy.source = 'telegram' AND legacy.account_id = ? LIMIT 2''',
        (account_id,),
    )).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise AuthenticationError('Ambiguous product owner')
    owner, telegram, verified = rows[0]
    if telegram is None or verified is None or int(telegram) <= 0 or int(telegram) != int(verified):
        raise AuthenticationError('Product owner does not match verified identity')
    return int(owner), int(telegram)


async def resolve_actor(account: Account) -> ProductActor:
    """Resolve a server-authenticated account, never a client-supplied owner ID."""
    async with db_backend.connect() as db:
        if not db_backend.is_postgres():
            await db.execute('BEGIN IMMEDIATE')
        try:
            suffix = ' FOR UPDATE' if db_backend.is_postgres() else ''
            row = await (await db.execute('SELECT status FROM shared_accounts WHERE id = ?' + suffix,
                                         (account.id,))).fetchone()
            if not row or row[0] != 'active':
                raise AuthenticationError('Account is no longer active')
            identity = await (await db.execute(
                'SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?',
                (account.identity.platform, account.identity.external_id),
            )).fetchone()
            if not identity or identity[0] != account.id:
                raise AuthenticationError('Identity ownership changed')
            owner = await legacy_product_owner(db, account.id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return ProductActor(account.id, owner[0] if owner else None, account.identity, owner[1] if owner else None)
