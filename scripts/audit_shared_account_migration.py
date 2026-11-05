"""Read-only, aggregate migration preflight. Never prints users or credentials."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def audit_vk(path: Path) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('users', 'generation_tasks', 'payments') if table in tables}
        columns = {row[1]: row[2] for row in connection.execute('PRAGMA table_info(users)')}
        result = {'source': 'vk', 'read_only': True, 'counts': counts, 'user_column_types': columns}
        if {'balance', 'balance_units'} <= columns.keys():
            row = connection.execute('''SELECT
                SUM(CASE WHEN ABS(balance - ROUND(balance)) > 0.000001 THEN 1 ELSE 0 END),
                SUM(CASE WHEN ABS(balance * 100 - COALESCE(balance_units, 0)) > 0.01 THEN 1 ELSE 0 END)
                FROM users''').fetchone()
            # 100 is the legacy VK migration's documented scale, not a new rate.
            result['fractional_balances'] = int(row[0] or 0)
            result['legacy_units_mismatches'] = int(row[1] or 0)
        return result


def audit_telegram(dsn: str) -> dict:
    import psycopg

    with psycopg.connect(dsn) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '15s'")
        columns = dict(connection.execute('''SELECT column_name, data_type
            FROM information_schema.columns WHERE table_schema = current_schema()
            AND table_name = 'users' ''').fetchall())
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('users', 'generation_tasks', 'transactions')}
        connection.rollback()
    return {'source': 'telegram', 'read_only': True, 'counts': counts, 'user_column_types': columns}


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
