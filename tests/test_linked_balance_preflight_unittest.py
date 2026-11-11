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
                           [(10, 'pending'), (10, 'completed')])
            db.execute('INSERT INTO payments VALUES (?,?)', (10, 'pending'))

    def tearDown(self):
        self.temp.cleanup()

    def feed(self, *records, summary=None):
        if summary is None:
            summary = {
                'committed_links': 3,
                'live_link_transfer_entries': 0,
                'live_wallets_with_funds': 0,
                'telegram_task_statuses': {'completed': 5, 'processing': 1},
                'telegram_payment_statuses': {'pending': 2, 'completed': 3},
                'telegram_unsettled_payment_providers': {'robokassa': 2},
            }
        return [json.dumps(entry) for entry in (*records, {'end': summary})]

    def test_exact_without_changing_vk_database(self):
        before = self.path.read_bytes()
        report = aggregate(self.feed({'vk': '10', 'tg': '2.5'}), self.path)
        self.assertEqual(report['linked']['vk_exact_units'], 30000)
        self.assertEqual(report['linked']['telegram_exact_units'], 25000)
        self.assertEqual(report['linked']['linked_pairs'], 1)
        self.assertEqual(report['vk_legacy_statuses']['task:pending'], 1)
        self.assertEqual(report['vk_legacy_statuses']['payment:pending'], 1)
        self.assertEqual(report['telegram_legacy_statuses']['task:processing'], 1)
        self.assertEqual(report['telegram_legacy_statuses']['payment:pending'], 2)
        self.assertEqual(report['telegram_unsettled_payment_providers'], {'robokassa': 2})
        self.assertEqual(report['settlement_review'], {
            'telegram_nonterminal_tasks': 1,
            'telegram_unsettled_payments': 2,
            'vk_nonterminal_tasks': 1,
            'vk_unsettled_payments': 1,
            'vk_status_tables_missing': 0,
        })
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
            with self.subTest(record=record), self.assertRaises((ValueError, TypeError)):
                aggregate(self.feed(record), self.path)

    def test_unknown_vk_state_is_unsettled_and_never_exposes_raw_metadata(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO payments VALUES (?, ?)', (10, 'secret_unknown_provider_state'))
            db.execute('INSERT INTO generation_tasks VALUES (?, ?)', (10, 'unexpected_task_state'))
        report = aggregate(self.feed({'vk': '10', 'tg': '2'}), self.path)
        self.assertEqual(report['vk_legacy_statuses']['payment:other'], 1)
        self.assertEqual(report['vk_legacy_statuses']['task:other'], 1)
        self.assertEqual(report['settlement_review']['vk_unsettled_payments'], 2)
        self.assertEqual(report['settlement_review']['vk_nonterminal_tasks'], 2)
        self.assertNotIn('secret_unknown_provider_state', json.dumps(report))
        self.assertNotIn('unexpected_task_state', json.dumps(report))
        self.assertFalse(report['financial_cutover_allowed'])

    def test_absent_telegram_settlement_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Telegram.*summary|source summary'):
            aggregate(self.feed({'vk': '10', 'tg': '2'}, summary={
                'committed_links': 1, 'live_link_transfer_entries': 0,
                'live_wallets_with_funds': 0,
            }), self.path)

    def test_telegram_unsettled_by_provider_must_balance_with_statuses(self):
        for unresolved_by_provider in ({}, {'robokassa': 1}, {'robokassa': 3}):
            with self.subTest(unresolved_by_provider=unresolved_by_provider), self.assertRaisesRegex(ValueError, 'unsettled'):
                aggregate(self.feed({'vk': '10', 'tg': '2'}, summary={
                        'committed_links': 1,
                        'live_link_transfer_entries': 0,
                        'live_wallets_with_funds': 0,
                        'telegram_task_statuses': {},
                        'telegram_payment_statuses': {'pending': 2},
                    'telegram_unsettled_payment_providers': unresolved_by_provider,
                }), self.path)

    def test_arbitrary_provider_metadata_cannot_leak_to_report(self):
        with self.assertRaisesRegex(ValueError, 'Telegram.*summary|source summary'):
            aggregate(self.feed({'vk': '10', 'tg': '2'}, summary={
                'committed_links': 1,
                'live_link_transfer_entries': 0,
                'live_wallets_with_funds': 0,
                'telegram_task_statuses': {},
                'telegram_payment_statuses': {'pending': 1},
                'telegram_unsettled_payment_providers': {'sensitive-unknown-merchant': 1},
            }), self.path)

    def test_missing_vk_operational_tables_are_explicit_blockers(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE generation_tasks')
            db.execute('DROP TABLE payments')
        report = aggregate(self.feed({'vk': '10', 'tg': '2'}), self.path)
        self.assertEqual(report['settlement_review']['vk_status_tables_missing'], 2)
        self.assertFalse(report['financial_cutover_allowed'])

    def test_no_unsafe_financial_cutover_even_without_exceptions(self):
        report = aggregate(self.feed({'vk': '10', 'tg': '2'}, summary={
            'committed_links': 1, 'live_link_transfer_entries': 0,
            'live_wallets_with_funds': 0,
            'telegram_task_statuses': {},
            'telegram_payment_statuses': {},
            'telegram_unsettled_payment_providers': {},
        }), self.path)
        self.assertEqual(report['snapshot_exception_count'], 0)
        self.assertFalse(report['financial_cutover_allowed'])


if __name__ == '__main__':
    unittest.main()
