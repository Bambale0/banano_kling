"""Read-only cross-source preflight for *linked* TG/VK legacy balances.

Emit TG rows from inside the Telegram container; pipe them directly to the VK
reader on the same trusted host. Raw identity rows never enter the aggregate
report, command-line arguments, temporary files or application logs.

Snapshots are independent and remain moving while legacy writers are active.
This is NEVER an authorization to transfer balances.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
import re
from pathlib import Path

def emit_telegram() -> None:
    import os
    import psycopg

    dsn = os.environ.get('DATABASE_URL', '')
    if not dsn.startswith(('postgresql://', 'postgres://')):
        raise ValueError('Expected PostgreSQL DSN in the Telegram container')
    with psycopg.connect(dsn) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout = '15s'")
        query = """SELECT identity.external_id, users.credits
            FROM shared_account_identities identity
            JOIN shared_account_legacy_links legacy
              ON legacy.account_id = identity.account_id AND legacy.source = 'telegram'
            JOIN users ON users.id = legacy.legacy_user_id
            WHERE identity.platform = 'vk'
            ORDER BY identity.external_id"""
        with conn.cursor(name='linked_balance_preflight') as cursor:
            cursor.execute(query)
            for vk_id, tg_credits in cursor:
                print(json.dumps({'vk': str(vk_id), 'tg': str(tg_credits)}, separators=(',', ':')))
        stats = {}
        for key, sql in {
            'committed_links': "SELECT COUNT(*) FROM shared_account_links WHERE state='committed'",
            'live_link_transfer_entries': "SELECT COUNT(*) FROM shared_wallet_entries WHERE scope='live' AND operation_key LIKE 'link:%'",
            'live_wallets_with_funds': "SELECT COUNT(*) FROM shared_wallets WHERE scope='live' AND (available_units<>0 OR reserved_units<>0)",
        }.items():
            stats[key] = conn.execute(sql).fetchone()[0]
        conn.rollback()
    print(json.dumps({'end': stats}, separators=(',', ':')))


def _classified(raw: object, prefix: str, totals: Counter) -> None:
    # The emit half runs from stdin inside the existing container, which has
    # no access to the new script's sibling module until its eventual release.
    if __package__:
        from .audit_shared_account_migration import _exact_units
    else:
        from audit_shared_account_migration import _exact_units
    category, units = _exact_units(raw)
    totals[f'{prefix}_{category}'] += 1
    if category == 'exact':
        totals[f'{prefix}_exact_units'] += units


def aggregate(rows, vk_path: Path) -> dict:
    """Consume a complete source stream and snapshot VK read-only; never expose IDs."""
    if not vk_path.is_file():
        raise ValueError('VK SQLite file unavailable')
    paired: dict[int, object] = {}
    producer_stats = None
    for line in rows:
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError('Invalid Telegram source record')
        if 'end' in row:
            if set(row) != {'end'}:
                raise ValueError('Invalid Telegram terminator')
            if producer_stats is not None:
                raise ValueError('Duplicate Telegram source terminator')
            producer_stats = row['end']
            if not isinstance(producer_stats, dict) or set(producer_stats) != {
                'committed_links', 'live_link_transfer_entries', 'live_wallets_with_funds'
            } or any(type(v) is not int or v < 0 for v in producer_stats.values()):
                raise ValueError('Invalid Telegram source summary')
            continue
        if producer_stats is not None:
            raise ValueError('Data after Telegram source terminator')
        if set(row) != {'vk', 'tg'}:
            raise ValueError('Invalid Telegram source record')
        vk_id, tg = row['vk'], row['tg']
        if not isinstance(vk_id, str) or not re.fullmatch(r'[1-9][0-9]*', vk_id) or not int(vk_id) < 2**63:
            raise ValueError('Invalid VK identity')
        if not isinstance(tg, str):
            raise ValueError('Invalid Telegram amount')
        numeric_vk_id = int(vk_id)
        if numeric_vk_id in paired:
            raise ValueError('Ambiguous VK identity / multiple TG owners')
        paired[numeric_vk_id] = tg
    if producer_stats is None:
        raise ValueError('Truncated Telegram source: missing terminator')

    totals = Counter()
    statuses = Counter()
    with sqlite3.connect(vk_path.resolve().as_uri() + '?mode=ro', uri=True) as vk:
        vk.execute('PRAGMA query_only=ON')
        vk.execute('BEGIN')
        cols = {row[1] for row in vk.execute("PRAGMA table_info('users')")}
        if not {'user_id', 'balance'} <= cols:
            raise ValueError('Unexpected VK users schema')
        has_tasks = vk.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='generation_tasks'").fetchone()[0] == 1
        has_payments = vk.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='payments'").fetchone()[0] == 1
        for vk_id, tg_balance in paired.items():
            totals['linked_pairs'] += 1
            _classified(tg_balance, 'telegram', totals)
            row = vk.execute('SELECT balance FROM users WHERE user_id=?', (vk_id,)).fetchone()
            if row is None:
                totals['missing_vk_legacy_user'] += 1
                continue
            totals['vk_legacy_users'] += 1
            _classified(row[0], 'vk', totals)
            if has_tasks:
                for status, count in vk.execute('SELECT status,COUNT(*) FROM generation_tasks WHERE user_id=? GROUP BY status', (vk_id,)):
                    statuses[f'task:{status}'] += count
            if has_payments:
                for status, count in vk.execute('SELECT status,COUNT(*) FROM payments WHERE user_id=? GROUP BY status', (vk_id,)):
                    statuses[f'payment:{status}'] += count
        vk.rollback()
    exceptions = totals['missing_vk_legacy_user'] + sum(
        totals[f'{source}_{category}']
        for source in ('vk', 'telegram')
        for category in ('precision_review', 'invalid')
    )
    return {
        'read_only': True,
        'migration_performed': False,
        'cross_database_atomic_snapshot': False,
        'writers_fenced': False,
        'financial_cutover_allowed': False,  # No live writer/settlement proof from this check.
        'snapshot_exception_count': exceptions,
        'source': producer_stats,
        'linked': dict(sorted(totals.items())),
        'vk_legacy_statuses': dict(sorted(statuses.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--emit-telegram', action='store_true')
    mode.add_argument('--vk-sqlite', type=Path)
    args = parser.parse_args()
    try:
        if args.emit_telegram:
            emit_telegram()
        else:
            print(json.dumps(aggregate(sys.stdin, args.vk_sqlite), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        # psycopg/database exceptions can include the DSN and user identifiers.
        print(f'Linked-account read-only preflight failed: {type(error).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
