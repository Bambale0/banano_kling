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
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

# Classify unexpected upstream values as unresolved. Unknown metadata is never
# printed verbatim: a provider string could contain incident/debug information.
TASK_STATUSES = frozenset({
    'pending', 'processing', 'queued', 'running', 'completed', 'failed',
    'canceled', 'cancelled', 'other',
})
PAYMENT_STATUSES = frozenset({
    'pending', 'processing', 'completed', 'confirmed', 'failed',
    'canceled', 'cancelled', 'refunded', 'other',
})
PAYMENT_PROVIDERS = frozenset({
    'robokassa', 'freekassa', 'lava', 'yookassa', 'prodamus',
    'telegram_stars', 'cryptobot', 'other',
})
TERMINAL_TASK_STATUSES = frozenset({'completed', 'failed', 'canceled', 'cancelled'})
TERMINAL_PAYMENT_STATUSES = frozenset({
    'completed', 'confirmed', 'failed', 'canceled', 'cancelled', 'refunded',
})
SOURCE_COUNTS = frozenset({
    'committed_links', 'live_link_transfer_entries', 'live_wallets_with_funds',
})
SOURCE_MAPS = {
    'telegram_task_statuses': TASK_STATUSES,
    'telegram_payment_statuses': PAYMENT_STATUSES,
    'telegram_unsettled_payment_providers': PAYMENT_PROVIDERS,
}
LINKED_LEGACY_USERS = """WITH linked_legacy_users AS (
    SELECT DISTINCT legacy.legacy_user_id
    FROM shared_account_identities identity
    JOIN shared_account_legacy_links legacy
      ON legacy.account_id = identity.account_id AND legacy.source = 'telegram'
    WHERE identity.platform = 'vk'
)"""


def _safe_bucket(raw: object, permitted: frozenset[str]) -> str:
    return raw if isinstance(raw, str) and raw in permitted else 'other'


def _counts(raw: object, permitted: frozenset[str]) -> dict[str, int]:
    if (not isinstance(raw, dict) or not set(raw).issubset(permitted)
            or any(type(value) is not int or value < 0 for value in raw.values())):
        raise ValueError('Invalid Telegram source summary: unexpected count metadata')
    return raw


def _nonterminal(statuses: dict[str, int], terminal: frozenset[str]) -> int:
    return sum(count for status, count in statuses.items() if status not in terminal)


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
        # These counts run under the SAME read-only PostgreSQL snapshot as
        # the balances. Neither payment status nor task status is a ledger.
        task_rows = conn.execute(LINKED_LEGACY_USERS + """SELECT task.status, COUNT(*)
            FROM generation_tasks task
            JOIN linked_legacy_users linked ON linked.legacy_user_id = task.user_id
            GROUP BY task.status""").fetchall()
        payment_rows = conn.execute(LINKED_LEGACY_USERS + """SELECT payment.status, payment.provider, COUNT(*)
            FROM transactions payment
            JOIN linked_legacy_users linked ON linked.legacy_user_id = payment.user_id
            GROUP BY payment.status, payment.provider""").fetchall()
        task_statuses = Counter()
        payment_statuses = Counter()
        unsettled_providers = Counter()
        for status, count in task_rows:
            task_statuses[_safe_bucket(status, TASK_STATUSES)] += int(count)
        for status, provider, count in payment_rows:
            category = _safe_bucket(status, PAYMENT_STATUSES)
            payment_statuses[category] += int(count)
            if category not in TERMINAL_PAYMENT_STATUSES:
                unsettled_providers[_safe_bucket(provider, PAYMENT_PROVIDERS)] += int(count)
        stats.update({
            'telegram_task_statuses': dict(sorted(task_statuses.items())),
            'telegram_payment_statuses': dict(sorted(payment_statuses.items())),
            'telegram_unsettled_payment_providers': dict(sorted(unsettled_providers.items())),
        })
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
            raise TypeError('Invalid Telegram source record')
        if 'end' in row:
            if set(row) != {'end'}:
                raise ValueError('Invalid Telegram terminator')
            if producer_stats is not None:
                raise ValueError('Duplicate Telegram source terminator')
            producer_stats = row['end']
            if not isinstance(producer_stats, dict) or set(producer_stats) != SOURCE_COUNTS | SOURCE_MAPS.keys():
                raise ValueError('Invalid Telegram source summary')
            if any(type(producer_stats[key]) is not int or producer_stats[key] < 0 for key in SOURCE_COUNTS):
                raise ValueError('Invalid Telegram source summary')
            for key, allowed in SOURCE_MAPS.items():
                _counts(producer_stats[key], allowed)
            payments = producer_stats['telegram_payment_statuses']
            unsettled_providers = producer_stats['telegram_unsettled_payment_providers']
            if _nonterminal(payments, TERMINAL_PAYMENT_STATUSES) != sum(unsettled_providers.values()):
                raise ValueError('Telegram unsettled payment status/provider totals disagree')
            continue
        if producer_stats is not None:
            raise ValueError('Data after Telegram source terminator')
        if set(row) != {'vk', 'tg'}:
            raise ValueError('Invalid Telegram source record')
        vk_id, tg = row['vk'], row['tg']
        if not isinstance(vk_id, str) or not re.fullmatch(r'[1-9][0-9]*', vk_id) or not int(vk_id) < 2**63:
            raise ValueError('Invalid VK identity')
        if not isinstance(tg, str):
            raise TypeError('Invalid Telegram amount')
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
                    statuses[f'task:{_safe_bucket(status, TASK_STATUSES)}'] += count
            if has_payments:
                for status, count in vk.execute('SELECT status,COUNT(*) FROM payments WHERE user_id=? GROUP BY status', (vk_id,)):
                    statuses[f'payment:{_safe_bucket(status, PAYMENT_STATUSES)}'] += count
        vk.rollback()
    exceptions = totals['missing_vk_legacy_user'] + sum(
        totals[f'{source}_{category}']
        for source in ('vk', 'telegram')
        for category in ('precision_review', 'invalid')
    )
    telegram_task_statuses = producer_stats['telegram_task_statuses']
    telegram_payment_statuses = producer_stats['telegram_payment_statuses']
    telegram_statuses = {
        **{f'task:{key}': count for key, count in telegram_task_statuses.items()},
        **{f'payment:{key}': count for key, count in telegram_payment_statuses.items()},
    }
    vk_task_statuses = {
        key.removeprefix('task:'): count for key, count in statuses.items() if key.startswith('task:')
    }
    vk_payment_statuses = {
        key.removeprefix('payment:'): count for key, count in statuses.items() if key.startswith('payment:')
    }
    return {
        'read_only': True,
        'migration_performed': False,
        'cross_database_atomic_snapshot': False,
        'writers_fenced': False,
        'financial_cutover_allowed': False,  # No live writer/settlement proof from this check.
        'snapshot_exception_count': exceptions,
        'source': {key: producer_stats[key] for key in sorted(SOURCE_COUNTS)},
        'linked': dict(sorted(totals.items())),
        'telegram_legacy_statuses': dict(sorted(telegram_statuses.items())),
        'telegram_unsettled_payment_providers': producer_stats['telegram_unsettled_payment_providers'],
        'vk_legacy_statuses': dict(sorted(statuses.items())),
        'settlement_review': {
            'telegram_nonterminal_tasks': _nonterminal(telegram_task_statuses, TERMINAL_TASK_STATUSES),
            'telegram_unsettled_payments': _nonterminal(telegram_payment_statuses, TERMINAL_PAYMENT_STATUSES),
            'vk_nonterminal_tasks': _nonterminal(vk_task_statuses, TERMINAL_TASK_STATUSES),
            'vk_unsettled_payments': _nonterminal(vk_payment_statuses, TERMINAL_PAYMENT_STATUSES),
            'vk_status_tables_missing': int(not has_tasks) + int(not has_payments),
        },
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
    except Exception as error:  # noqa: BLE001 - driver exceptions may contain DSN credentials.
        # psycopg/database exceptions can include the DSN and user identifiers.
        print(f'Linked-account read-only preflight failed: {type(error).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
