"""Standalone stdlib regression suite, independent of the production bot deps."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.audit_linked_balance_preflight import aggregate


class LinkedBalancePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'vk.db'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE users(user_id INTEGER PRIMARY KEY, balance)')
            db.execute('CREATE TABLE generation_tasks(user_id INTEGER, status TEXT)')
            db.execute('CREATE TABLE payments(user_id INTEGER, status TEXT)')
            db.executemany('INSERT INTO users VALUES (?, ?)', [
                (10, 3), (11, 0.30000000000000004), (12, -5),
            ])
            db.executemany('INSERT INTO generation_tasks VALUES (?,?)',
                           [(10, 'pending'), (10, 'done')])
            db.execute('INSERT INTO payments VALUES (?,?)', (10, 'pending'))

    def tearDown(self):
        self.temp.cleanup()

    def feed(self, *records, summary=None):
        summary = summary or {'committed_links': 3, 'live_link_transfer_entries': 0,
                              'live_wallets_with_funds': 0}
        return [json.dumps(entry) for entry in (*records, {'end': summary})]

    def test_exact_without_changing_vk_database(self):
        before = self.path.read_bytes()
        report = aggregate(self.feed({'vk': '10', 'tg': '2.5'}), self.path)
        self.assertEqual(report['linked']['vk_exact_units'], 30000)
        self.assertEqual(report['linked']['telegram_exact_units'], 25000)
        self.assertEqual(report['linked']['linked_pairs'], 1)
        self.assertEqual(report['vk_legacy_statuses']['task:pending'], 1)
        self.assertEqual(report['vk_legacy_statuses']['payment:pending'], 1)
        self.assertFalse(report['financial_cutover_allowed'])
        self.assertEqual(before, self.path.read_bytes())
        self.assertNotIn('10', json.dumps(report['linked']))

    def test_uncertain_float_negative_and_missing_do_not_pretend_ready(self):
        report = aggregate(self.feed({'vk': '11', 'tg': '0.30000000000000004'},
                                     {'vk': '12', 'tg': '3'},
                                     {'vk': '13', 'tg': '1'}), self.path)
        self.assertEqual(report['linked']['telegram_precision_review'], 1)
        self.assertEqual(report['linked']['vk_precision_review'], 1)
        self.assertEqual(report['linked']['vk_invalid'], 1)
        self.assertEqual(report['linked']['missing_vk_legacy_user'], 1)
        self.assertEqual(report['snapshot_exception_count'], 4)
        self.assertFalse(report['financial_cutover_allowed'])

    def test_missing_terminator_cannot_hide_partial_source(self):
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            aggregate([json.dumps({'vk': '10', 'tg': '2'})], self.path)

    def test_duplicate_vk_owner_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            aggregate(self.feed({'vk': '10', 'tg': '2'}, {'vk': '10', 'tg': '4'}), self.path)

    def test_malformed_source_blocks(self):
        for record in ({'vk': 'x', 'tg': '1'}, {'vk': '-1', 'tg': '1'},
                       {'vk': '10', 'tg': 2}, {'vk': '10', 'tg': '2', 'extra': 'bad'}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                aggregate(self.feed(record), self.path)

    def test_no_unsafe_financial_cutover_even_without_exceptions(self):
        report = aggregate(self.feed({'vk': '10', 'tg': '2'}, summary={
            'committed_links': 1, 'live_link_transfer_entries': 0,
            'live_wallets_with_funds': 0,
        }), self.path)
        self.assertEqual(report['snapshot_exception_count'], 0)
        self.assertFalse(report['financial_cutover_allowed'])


if __name__ == '__main__':
    unittest.main()
