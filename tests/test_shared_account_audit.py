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
