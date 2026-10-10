"""Synthetic SQLite quote/claim tests; no application bootstrap or provider calls."""
import ast
import asyncio
import importlib.util
import os
import re
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("seedance_receipts_under_test", ROOT / "bot/services/seedance_quote_receipts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


# Reuse only the test-owned SQL shim, never the application adapter.
fixture_tree = ast.parse((ROOT / "tests/isolated/test_motion_financial_lifecycle.py").read_text())
fixture_nodes = [node for node in fixture_tree.body if isinstance(node, ast.ClassDef) and node.name in {"PgCursor", "PgFixture"}]
fixture_ns = {"re": re}
exec(compile(ast.Module(body=fixture_nodes, type_ignores=[]), "test_pg_fixture", "exec"), fixture_ns)  # noqa: S102
PgFixture = fixture_ns["PgFixture"]


class ReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "synthetic.sqlite")
        self.socket = os.environ.get("SEEDANCE_TEST_PG_SOCKET")
        if self.socket:
            if Path(self.socket).resolve() != (ROOT / ".seedance-pg-test/socket").resolve():
                raise RuntimeError("Refusing non-fixture PostgreSQL socket")
            async with self.connect() as db:
                await db.execute("DROP TABLE IF EXISTS seedance_quote_media_leases,seedance_quote_receipts,seedance_snapshot_reservations,wan3_prime_media,users,fixture_locks")
                await db.commit()
        async def lock(db):
            await db.execute("SELECT id FROM fixture_locks WHERE id=1 FOR UPDATE" if self.socket else "BEGIN IMMEDIATE")
        self.store = module.SeedanceQuoteReceipts(self.connect, aiosqlite.Row, storage_lock=lock)
        async with self.connect() as db:
            await db.execute("CREATE TABLE fixture_locks (id INTEGER PRIMARY KEY)")
            await db.execute("INSERT INTO fixture_locks VALUES (1)")
            await db.execute("CREATE TABLE users (id BIGINT PRIMARY KEY, telegram_id BIGINT UNIQUE, credits REAL, updated_at TEXT)")
            await db.execute("INSERT INTO users VALUES (1,5000000001,100,'initial')")
            await db.execute("CREATE TABLE wan3_prime_media (id INTEGER PRIMARY KEY,user_id INTEGER,source TEXT)")
            await db.execute("INSERT INTO wan3_prime_media VALUES (1,1,'seedance_quote_snapshot')")
            await db.commit()
        await self.store.ensure_schema()
        self.billing = {"version": 2, "model": "seedance_2_5", "cost": 48, "charge_cost": 48}
        self.original = {"prompt": "hello", "video_urls": ["original"]}
        self.quote = await self.create()

    async def test_pause_blocks_new_debit_but_preserves_unknown_and_accepted_replay(self):
        self.store.allow_new_claim = lambda: False
        with self.assertRaisesRegex(module.QuoteConflict, "приостановлены"):
            await self.claim()
        self.assertEqual(await self.balance(), 100)
        self.assertEqual((await self.store.find(5000000001, self.quote["quote_id"]))["phase"], "quoted")
        self.store.allow_new_claim = lambda: True
        claimed = await self.claim()
        self.store.allow_new_claim = lambda: False
        await self.store.unknown(claimed["quote_id"])
        self.assertFalse((await self.claim())["created"])
        self.assertEqual(await self.balance(), 52)
        await self.store.accepted(claimed["quote_id"], "accepted-during-pause")
        replay = await self.claim()
        self.assertFalse(replay["created"])
        self.assertEqual(replay["provider_task_id"], "accepted-during-pause")
        self.assertEqual(await self.balance(), 52)

    async def asyncTearDown(self):
        self.directory.cleanup()

    @asynccontextmanager
    async def connect(self):
        if not self.socket:
            async with aiosqlite.connect(self.path, timeout=10) as db:
                yield db
            return
        import asyncpg
        connection = await asyncpg.connect(host=self.socket, user="postgres", database="seedance_test")
        await connection.set_type_codec("timestamp", schema="pg_catalog", format="text",
                                        encoder=lambda value: value.isoformat(" ") if isinstance(value, datetime) else value,
                                        decoder=datetime.fromisoformat)
        db = PgFixture(connection)
        await db.start()
        try:
            yield db
        finally:
            await db.rollback()
            await connection.close()

    async def create(self, **kwargs):
        args = {"user_id": 1, "telegram_id": 5000000001, "original": self.original,
                "provider": {"video_urls": ["immutable"]}, "billing": self.billing, "media_ids": [1]}
        args.update(kwargs)
        return await self.store.create(**args)

    async def claim(self, **kwargs):
        args = {"telegram_id": 5000000001, "quote_id": self.quote["quote_id"],
                "quote_hash": self.quote["quote_hash"], "original": self.original,
                "current_billing": self.billing}
        args.update(kwargs)
        return await self.store.claim(**args)

    async def balance(self):
        async with self.connect() as db:
            return (await (await db.execute("SELECT credits FROM users WHERE id=1")).fetchone())[0]

    async def test_pause_barrier_waits_for_pre_marker_admission_commit(self):
        admitted = asyncio.Event()
        release_debit = asyncio.Event()
        barrier_started = asyncio.Event()
        barrier_done = asyncio.Event()

        @asynccontextmanager
        async def delayed_connect():
            async with self.connect() as db:
                original_execute = db.execute
                async def execute(sql, *args):
                    if "UPDATE users SET credits = credits -" in sql:
                        admitted.set()
                        await release_debit.wait()
                    return await original_execute(sql, *args)
                db.execute = execute
                yield db

        self.store.connect = delayed_connect
        self.store.allow_new_claim = lambda: True
        claim = asyncio.create_task(self.claim())
        await admitted.wait()
        # Operator creates marker AFTER this claim passed admission.
        self.store.allow_new_claim = lambda: False
        async with self.connect() as db:
            plain = await (await db.execute("SELECT COUNT(*) FROM seedance_quote_receipts WHERE phase='submitting'")).fetchone()
            self.assertEqual(plain[0], 0)  # A bare SELECT would falsely look drained.

        async def barrier():
            async with self.connect() as db:
                barrier_started.set()
                await db.execute("SELECT id FROM fixture_locks WHERE id=1 FOR UPDATE" if self.socket else "BEGIN IMMEDIATE")
                row = await (await db.execute("SELECT COUNT(*) FROM seedance_quote_receipts WHERE phase='submitting'")).fetchone()
                await db.commit()
                barrier_done.set()
                return row[0]

        drain = asyncio.create_task(barrier())
        await barrier_started.wait()
        await asyncio.sleep(0.02)
        self.assertFalse(barrier_done.is_set())
        release_debit.set()
        self.assertTrue((await claim)["created"])
        self.assertEqual(await drain, 1)
        self.assertEqual(await self.balance(), 52)

    async def test_double_click_claim_debit_once(self):
        rows = await asyncio.gather(self.claim(), self.claim())
        self.assertEqual(sum(row["created"] for row in rows), 1)
        self.assertEqual(await self.balance(), 52)

    async def test_actor_hash_settings_rate_mismatch_no_debit(self):
        for changes in ({"telegram_id": 999}, {"quote_hash": "bad"},
                        {"original": {"prompt": "changed"}},
                        {"current_billing": dict(self.billing, cost=49)}):
            with self.assertRaises(module.QuoteConflict):
                await self.claim(**changes)
        self.assertEqual(await self.balance(), 100)

    async def test_expiry_does_not_claim_or_debit(self):
        async with self.connect() as db:
            await db.execute("UPDATE seedance_quote_receipts SET expires_at='2000-01-01'")
            await db.commit()
        with self.assertRaises(module.QuoteConflict):
            await self.claim()
        self.assertEqual(await self.balance(), 100)

    async def test_unknown_persists_across_controller_restart_and_blocks_new_quote(self):
        await self.claim()
        await self.store.unknown(self.quote["quote_id"])
        self.store = module.SeedanceQuoteReceipts(self.connect, aiosqlite.Row)
        self.assertFalse((await self.claim())["created"])
        second = await self.create()
        with self.assertRaises(module.QuoteConflict):
            await self.claim(quote_id=second["quote_id"], quote_hash=second["quote_hash"])
        self.assertEqual(await self.balance(), 52)

    async def test_accepted_unbound_recovers_without_resubmit(self):
        await self.claim()
        self.assertTrue(await self.store.accepted(self.quote["quote_id"], "provider-1"))
        rows = await self.store.unbound_accepted()
        self.assertEqual(rows[0]["provider_task_id"], "provider-1")
        self.assertFalse(await self.store.rejected_and_refund(self.quote["quote_id"]))
        await self.store.mark_bound(self.quote["quote_id"], "provider-1")
        self.assertEqual(await self.store.unbound_accepted(), [])
        self.assertFalse((await self.claim())["created"])

    async def test_rejection_refund_once_and_tombstone_prevents_relaunch(self):
        await self.claim()
        refunded = await asyncio.gather(*[self.store.rejected_and_refund(self.quote["quote_id"]) for _ in range(2)])
        self.assertEqual(sum(refunded), 1)
        self.assertEqual(await self.balance(), 100)
        self.assertFalse((await self.claim())["created"])

    async def test_admin_receipt_never_refunds_unpaid_credits(self):
        self.billing = dict(self.billing, charge_cost=0)
        self.quote = await self.create()
        await self.claim()
        await self.store.rejected_and_refund(self.quote["quote_id"])
        self.assertEqual(await self.balance(), 100)

    async def test_insufficient_balance_rollback_preserves_quote(self):
        self.billing = dict(self.billing, charge_cost=150)
        self.quote = await self.create()
        with self.assertRaises(module.InsufficientCredits):
            await self.claim()
        self.assertEqual(await self.balance(), 100)
        self.assertEqual((await self.store.find(5000000001, self.quote["quote_id"]))["phase"], "quoted")


if __name__ == "__main__":
    unittest.main()
