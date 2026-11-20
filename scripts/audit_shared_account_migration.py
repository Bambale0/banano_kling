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


def _status_counts(connection, table: str) -> dict[str, int]:
    """Counts only: never export legacy task/payment rows or customer fields."""
    if table not in ('generation_tasks', 'transactions'):
        raise ValueError('Unsupported legacy status table')
    rows = connection.execute(
        'SELECT status, COUNT(*) FROM ' + table + ' GROUP BY status'
    ).fetchall()
    return {str(status) if status is not None else '<null>': int(count)
            for status, count in rows}


def _operational_snapshot(connection) -> dict:
    """Read-only status/financial authority preflight, not a cutover approval.

    Uses the same REPEATABLE READ, READ ONLY PostgreSQL transaction as the
    existing opening balance report. No identity, amount or secret per user
    is ever read here.
    """
    generations = _status_counts(connection, 'generation_tasks')
    transactions = _status_counts(connection, 'transactions')
    # Unrecognized statuses are considered unresolved, not silently accepted
    # as settled. Terminal status names must follow the legacy DB contract.
    terminal = frozenset(('completed', 'failed', 'cancelled', 'canceled', 'refunded'))
    outstanding_gen = sum(v for k, v in generations.items() if k not in terminal)
    outstanding_payments = sum(v for k, v in transactions.items() if k not in terminal)

    # Provider and age are aggregate-only diagnostics; a pending legacy row is
    # not evidence of payment, receivable, refund or provider settlement.
    pending_by_provider = [
        {
            'provider': str(provider),
            'pending': int(count),
            'older_1d': int(older_1d),
            'older_7d': int(older_7d),
            'older_30d': int(older_30d),
        }
        for provider, count, older_1d, older_7d, older_30d in connection.execute(
            """SELECT COALESCE(provider, '<unknown>'), COUNT(*),
                      COUNT(*) FILTER (WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 day'),
                      COUNT(*) FILTER (WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '7 days'),
                      COUNT(*) FILTER (WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days')
               FROM transactions WHERE status='pending'
               GROUP BY COALESCE(provider, '<unknown>')
               ORDER BY COUNT(*) DESC, COALESCE(provider, '<unknown>')"""
        ).fetchall()
    ]
    unresolved_by_model = [
        {
            'status': str(status) if status is not None else '<null>',
            'model': str(model) if model is not None else '<unknown>',
            'count': int(count),
            'older_1d': int(older_1d),
        }
        for status, model, count, older_1d in connection.execute(
            """SELECT status, model, COUNT(*),
                      COUNT(*) FILTER (WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 day')
               FROM generation_tasks
               WHERE status IS NULL OR status NOT IN
                     ('completed', 'failed', 'cancelled', 'canceled', 'refunded')
               GROUP BY status, model
               ORDER BY COUNT(*) DESC, status, model"""
        ).fetchall()
    ]
    # These fixed SELECTs run inside the same PostgreSQL snapshot, so an
    # inconsistency is an error, not permission to ignore missing liabilities.
    if sum(item['pending'] for item in pending_by_provider) != transactions.get('pending', 0):
        raise RuntimeError('Inconsistent pending transaction status snapshot')
    if sum(item['count'] for item in unresolved_by_model) != outstanding_gen:
        raise RuntimeError('Inconsistent generation status snapshot')

    def exists(name: str) -> bool:
        return bool(connection.execute(
            """SELECT EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema=current_schema() AND table_name=%s)""",
            (name,),
        ).fetchone()[0])

    wallet_scopes = None
    opening_claims_by_scope = None
    if exists('shared_wallets') and exists('shared_wallet_opening_claims'):
        wallet_scopes = {
            str(scope): {
                'wallets': int(count),
                'available_units': str(available or 0),
                'reserved_units': str(reserved or 0),
            }
            for scope, count, available, reserved in connection.execute(
                """SELECT scope, COUNT(*), SUM(available_units), SUM(reserved_units)
                   FROM shared_wallets GROUP BY scope"""
            ).fetchall()
        }
        opening_claims_by_scope = {
            str(scope): int(count)
            for scope, count in connection.execute(
                """SELECT scope, COUNT(*)
                   FROM shared_wallet_opening_claims GROUP BY scope"""
            ).fetchall()
        }

    # Even a zero-pending snapshot is NOT sufficient evidence to activate
    # live wallets: legacy writers, event replay and opening approval remain
    # external, independent release gates.
    blockers = [
        'legacy_writers_not_fenced',
        'opening_snapshot_not_approved',
        'legacy_event_watermarks_unverified',
        'historical_refund_mapping_unverified',
    ]
    if outstanding_gen:
        blockers.append('unresolved_generation_jobs')
    if outstanding_payments:
        blockers.append('unreconciled_legacy_transactions')
    if wallet_scopes is None or opening_claims_by_scope is None:
        blockers.append('shared_wallet_schema_unverified')
    return {
        'legacy_generation_status_counts': generations,
        'legacy_transaction_status_counts': transactions,
        'pending_transactions_by_provider_age': pending_by_provider,
        'unresolved_generations_by_model_age': unresolved_by_model,
        'nonterminal_generations': outstanding_gen,
        'unreconciled_transaction_statuses': outstanding_payments,
        'wallet_scopes': wallet_scopes,
        'opening_claims_by_scope': opening_claims_by_scope,
        'production_cutover_authorized': False,
        'cutover_blockers': blockers,
    }


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
        operational = _operational_snapshot(connection)
        if readiness['blocked']:
            operational['cutover_blockers'].append('balance_precision_not_resolved')
        connection.rollback()
    return {'source': 'telegram', 'read_only': True, 'counts': counts, 'user_column_types': columns,
            'authority_candidate': 'users.credits', 'opening_balance_readiness': readiness,
            'operational_readiness': operational}


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
