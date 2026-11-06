"""Detect wallet/ledger/reservation drift; never silently repair financial data."""
from __future__ import annotations

from collections import defaultdict


async def reconcile_in_transaction(db, scope: str, account_id: str, balance) -> dict:
    # The caller holds the canonical account lock, also used by merges and every
    # wallet mutation. The report therefore describes one consistent state.
    aliases = await (await db.execute('''WITH RECURSIVE owned(id) AS (
        SELECT ? UNION ALL SELECT a.id FROM shared_accounts a JOIN owned o ON a.merged_into = o.id WHERE a.status = 'merged')
        SELECT id FROM owned''', (account_id,))).fetchall()
    issues = set()
    totals = [0, 0]
    captures, refunds = defaultdict(int), defaultdict(int)
    reserves = {}
    transfers = defaultdict(list)
    settled = defaultdict(lambda: [0, 0])
    entry_count = 0
    for alias in aliases:
        owner = alias[0]
        rows = await (await db.execute('''SELECT sequence, available_delta, reserved_delta, available_after,
            reserved_after, kind, operation_key, amount_units, reference_key FROM shared_wallet_entries
            WHERE scope = ? AND account_id = ? ORDER BY sequence''', (scope, owner))).fetchall()
        available, reserved, sequence = 0, 0, 0
        for row in rows:
            sequence += 1
            if int(row[0]) != sequence:
                issues.add('ledger_sequence_gap')
            available += int(row[1])
            reserved += int(row[2])
            if (available, reserved) != (int(row[3]), int(row[4])):
                issues.add('ledger_running_balance_mismatch')
            kind, key, units, reference = row[5], row[6], int(row[7]), row[8]
            deltas = (int(row[1]), int(row[2]))
            expected = {'opening': (units, 0), 'credit': (units, 0), 'reserve': (-units, units),
                        'capture': (0, -units), 'release': (units, -units), 'refund': (units, 0)}
            if kind in expected and deltas != expected[kind]:
                issues.add('ledger_operation_delta_mismatch')
            elif kind in {'transfer_in', 'transfer_out'}:
                sign = 1 if kind == 'transfer_in' else -1
                if sum(deltas) != sign * units or any(delta * sign < 0 for delta in deltas):
                    issues.add('ledger_operation_delta_mismatch')
                transfers[reference].append((kind, units, *deltas))
            if kind == 'capture':
                captures[key] += units
                settled[reference][0] += units
            elif kind == 'release':
                settled[reference][1] += units
            elif kind == 'refund':
                refunds[reference] += units
            elif kind == 'reserve':
                reserves[key] = units
        entry_count += len(rows)
        wallet = await (await db.execute('SELECT available_units, reserved_units, revision FROM shared_wallets WHERE scope = ? AND account_id = ?', (scope, owner))).fetchone()
        if wallet:
            if available != int(wallet[0]):
                issues.add('available_ledger_mismatch')
            if reserved != int(wallet[1]):
                issues.add('reserved_ledger_mismatch')
            if sequence != int(wallet[2]):
                issues.add('wallet_revision_mismatch')
            if owner != account_id and (int(wallet[0]) or int(wallet[1])):
                issues.add('merged_wallet_not_empty')
        elif rows:
            issues.add('missing_wallet')
        totals[0] += available
        totals[1] += reserved
    if totals[0] != balance.available_units:
        issues.add('available_ledger_mismatch')
    if totals[1] != balance.reserved_units:
        issues.add('reserved_ledger_mismatch')
    for capture, refunded in refunds.items():
        if refunded > captures.get(capture, 0):
            issues.add('refund_exceeds_capture')
    for legs in transfers.values():
        incoming = [leg for leg in legs if leg[0] == 'transfer_in']
        outgoing = [leg for leg in legs if leg[0] == 'transfer_out']
        if len(incoming) != 1 or len(outgoing) != 1 or incoming[0][1] != outgoing[0][1] or incoming[0][2:] != tuple(-delta for delta in outgoing[0][2:]):
            issues.add('transfer_pair_mismatch')
    reservations = await (await db.execute('''WITH RECURSIVE owned(id) AS (
        SELECT ? UNION ALL SELECT a.id FROM shared_accounts a JOIN owned o ON a.merged_into = o.id WHERE a.status = 'merged')
        SELECT reservation_key, amount_units, captured_units, released_units, account_id
        FROM shared_wallet_reservations WHERE scope = ? AND account_id IN (SELECT id FROM owned)''', (account_id, scope))).fetchall()
    open_reservations, reserved_total = 0, 0
    for row in reservations:
        key, amount, captured, released = row[0], int(row[1]), int(row[2]), int(row[3])
        if row[4] != account_id:
            issues.add('reservation_not_canonical')
        if reserves.pop(key, None) != amount:
            issues.add('reservation_ledger_mismatch')
        if settled.pop(key, [0, 0]) != [captured, released]:
            issues.add('reservation_settlement_mismatch')
        remaining = amount - captured - released
        reserved_total += remaining
        open_reservations += remaining > 0
    if settled:
        issues.add('missing_reservation')
    if reserves:
        issues.add('missing_reservation')
    if reserved_total != balance.reserved_units:
        issues.add('reservation_balance_mismatch')
    return {'scope': scope, 'consistent': not issues, 'issues': sorted(issues), 'ledger_entries': entry_count,
            'open_reservations': open_reservations, 'balance': balance.payload()}
