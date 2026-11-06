"""Read-only, aggregate migration preflight. Never prints users or credentials."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


def _exact_units(raw) -> tuple[str, int | None]:
    """Classify legacy storage without choosing an unapproved rounding policy."""
    try:
        if raw is None or isinstance(raw, bool):
            return 'invalid', None
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0 or value > Decimal('922337203685477.5807'):
            return 'invalid', None
        if 0 < value < Decimal('0.0001'):
            return 'precision_review', None
        with localcontext() as context:
            context.prec = max(64, len(value.as_tuple().digits) + 8)
            units = value * 10000
            if units != units.to_integral_value():
                return 'precision_review', None
            return 'exact', int(units)
    except (InvalidOperation, ValueError, TypeError):
        return 'invalid', None


def _readiness(rows) -> dict:
    result = {'exact': 0, 'precision_review': 0, 'invalid': 0}
    total = 0
    for row in rows:
        state, units = _exact_units(row[0])
        result[state] += 1
        total += units or 0
    return {**result, 'exact_total_units': str(total), 'blocked': result['precision_review'] + result['invalid']}


def audit_vk(path: Path) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('users', 'generation_tasks', 'payments') if table in tables}
        columns = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(users)')}
        result = {'source': 'vk', 'read_only': True, 'counts': counts, 'user_column_types': columns}
        if 'balance' in columns:
            result['authority_candidate'] = 'users.balance'
            result['opening_balance_readiness'] = _readiness(connection.execute('SELECT balance FROM users'))
        if {'balance', 'balance_units'} <= columns.keys():
            row = connection.execute('''SELECT
                SUM(CASE WHEN ABS(balance - ROUND(balance)) > 0.000001 THEN 1 ELSE 0 END),
                SUM(CASE WHEN ABS(balance * 100 - COALESCE(balance_units, 0)) > 0.01 THEN 1 ELSE 0 END)
                FROM users''').fetchone()
            # 100 is the legacy VK migration's documented scale, not a new rate.
            result['fractional_balances'] = int(row[0] or 0)
            result['legacy_units_mismatches'] = int(row[1] or 0)
            # SQLite numeric coercion silently treats malformed text as zero.
            # Report those rows separately instead of declaring them reconciled.
            result['legacy_units_uncomparable'] = sum(
                _exact_units(raw)[0] == 'invalid' or units is None or type(units) is not int
                for raw, units in connection.execute('SELECT balance, balance_units FROM users')
            )
        return result


def audit_telegram(dsn: str) -> dict:
    import psycopg

    with psycopg.connect(dsn) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '15s'")
        columns = dict(connection.execute('''SELECT column_name, data_type
            FROM information_schema.columns WHERE table_schema = current_schema()
            AND table_name = 'users' ''').fetchall())
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('users', 'generation_tasks', 'transactions')}
        with connection.cursor(name='opening_balance_readiness') as cursor:
            cursor.execute('SELECT credits FROM users')
            readiness = _readiness(cursor)
        connection.rollback()
    return {'source': 'telegram', 'read_only': True, 'counts': counts, 'user_column_types': columns,
            'authority_candidate': 'users.credits', 'opening_balance_readiness': readiness}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--vk-sqlite', type=Path)
    source.add_argument('--telegram-dsn-env', help='Name of an explicitly configured DSN environment variable')
    arguments = parser.parse_args()
    try:
        if arguments.vk_sqlite:
            result = audit_vk(arguments.vk_sqlite)
        else:
            dsn = os.environ.get(arguments.telegram_dsn_env, '')
            if not dsn:
                raise ValueError('Audit DSN is not configured')
            result = audit_telegram(dsn)
    except Exception as exc:  # noqa: BLE001 - database errors can contain DSN/credentials.
        parser.exit(1, f'Migration preflight failed ({type(exc).__name__}); no credentials or row data emitted.\n')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
