"""Sandbox-only opening import rehearsal; no route, CLI or live-money adapter.

Evidence hashes identify a reviewed synthetic snapshot manifest, not proof that
production writers were fenced. Never use this as a production cutover gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from .wallet import (
    WalletConflict,
    WalletService,
    _key,
    amount_units,
    canonical_account,
    format_units,
)


class OpeningImportRehearsal:
    async def apply(self, requested_account_id: str, platform: str, external_id: int,
                    amount: str | int | Decimal, snapshot_id: str, evidence_hash: str) -> dict:
        if platform not in {'telegram', 'vk'} or type(external_id) is not int or not 0 < external_id < 2**63:
            raise ValueError('Invalid source identity')
        if isinstance(amount, bool) or not isinstance(amount, (str, int, Decimal)):
            raise TypeError('Use an exact reviewed amount')
        try:
            units = 0 if Decimal(amount).is_zero() else amount_units(amount)
        except InvalidOperation as exc:
            raise ValueError('Invalid reviewed amount') from exc
        snapshot_id = _key(snapshot_id)
        if not isinstance(evidence_hash, str) or not re.fullmatch('[0-9a-f]{64}', evidence_hash):
            raise ValueError('Expected snapshot evidence SHA-256')
        key = f'opening:{platform}:{external_id}'
        fingerprint = hashlib.sha256(json.dumps(
            [platform, external_id, units, snapshot_id, evidence_hash], separators=(',', ':')
        ).encode()).hexdigest()
        service = WalletService('sandbox')
        async with service._transaction(requested_account_id, key) as (db, balance, account_id):
            identity = await (await db.execute(
                'SELECT account_id FROM shared_account_identities WHERE platform = ? AND external_id = ?',
                (platform, external_id),
            )).fetchone()
            if not identity or await canonical_account(db, identity[0]) != account_id:
                raise PermissionError('Snapshot identity does not belong to this account')
            claim = await (await db.execute(
                '''SELECT account_id, request_hash FROM shared_wallet_opening_claims
                   WHERE scope = ? AND platform = ? AND external_id = ?''',
                ('sandbox', platform, external_id),
            )).fetchone()
            if claim:
                if await canonical_account(db, claim[0]) != account_id or claim[1] != fingerprint:
                    raise WalletConflict('Source identity already imported with another snapshot')
                return {'operation_key': key, 'amount': format_units(units), 'replayed': True}
            if units:
                await service._append(db, account_id, balance, key, 'opening', units, '', units, 0)
            await db.execute(
                '''INSERT INTO shared_wallet_opening_claims
                   (scope, platform, external_id, account_id, request_hash, snapshot_id, evidence_hash, amount_units, operation_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('sandbox', platform, external_id, account_id, fingerprint, snapshot_id, evidence_hash, units, key if units else None),
            )
            return {'operation_key': key, 'amount': format_units(units), 'replayed': False}
