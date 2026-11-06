import sqlite3

from scripts.audit_shared_account_migration import audit_vk


def test_vk_preflight_reports_aggregate_drift_without_modifying_database(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE users(user_id INTEGER PRIMARY KEY, balance REAL, balance_units INTEGER)')
        connection.executemany('INSERT INTO users VALUES (?, ?, ?)', [(1, 2.5, 250), (2, 7, 0)])
    before = path.read_bytes()
    report = audit_vk(path)
    assert report['counts']['users'] == 2
    assert report['fractional_balances'] == 1
    assert report['legacy_units_mismatches'] == 1
    assert 'user_id' not in report.get('counts', {})
    assert path.read_bytes() == before


def test_vk_preflight_blocks_ambiguous_precision_null_and_negative_balances(tmp_path):
    path = tmp_path / 'ambiguous.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE users(balance, balance_units)')
        connection.executemany('INSERT INTO users VALUES (?, ?)', [
            (0.30000000000000004, 30), (None, 0), (-1, -100), ('bad', 0), (1.125, 0), (0, None),
        ])
    before = path.read_bytes()
    report = audit_vk(path)
    assert report['authority_candidate'] == 'users.balance'
    assert report['opening_balance_readiness'] == {
        'exact': 2, 'precision_review': 1, 'invalid': 3,
        'exact_total_units': '11250', 'blocked': 4,
    }
    assert report['legacy_units_uncomparable'] == 4
    assert path.read_bytes() == before


def test_nonzero_scientific_balance_never_underflows_to_importable_zero(tmp_path):
    path = tmp_path / 'tiny.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE users(balance TEXT)')
        connection.execute('INSERT INTO users VALUES (?)', ('1e-100000000',))
    assert audit_vk(path)['opening_balance_readiness'] == {
        'exact': 0, 'precision_review': 1, 'invalid': 0,
        'exact_total_units': '0', 'blocked': 1,
    }
