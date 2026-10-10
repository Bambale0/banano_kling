"""Direct synthetic-SQLite tests, no application/database-runtime imports."""
import asyncio
import importlib.util
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("motion_receipts_under_test",
    ROOT / "bot/services/motion_launch_receipts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = str(Path(self.directory.name) / "synthetic.sqlite")
        self.store = module.MotionLaunchReceipts(self.connect, aiosqlite.Row)
        async with self.connect() as db:
            await db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, credits REAL, updated_at TEXT)")
            await db.execute("INSERT INTO users VALUES (1, 101, 100, 'initial')")
            await db.commit()
        await self.store.ensure_schema()

    def connect(self):
        return aiosqlite.connect(self.path, timeout=10)

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def reserve(self, **kwargs):
        args = {"user_id": 1, "telegram_id": 101, "request_key": "a"*32,
                    "recipe": {"model": "motion_control_v26", "quote": {"cost": 10}},
                    "cost": 10, "admin_free": False}
        args.update(kwargs)
        return await self.store.reserve(**args)

    async def balance(self):
        async with self.connect() as db:
            return (await (await db.execute("SELECT credits FROM users WHERE id=1")).fetchone())[0]

    async def test_concurrent_reservations_debit_once(self):
        rows = await asyncio.gather(self.reserve(), self.reserve())
        self.assertEqual(sum(row["created"] for row in rows), 1)
        self.assertEqual(await self.balance(), 90)

    async def test_proven_rejection_refunds_once_under_race(self):
        row = await self.reserve()
        results = await asyncio.gather(
            self.store.rejected_and_refund(row["receipt_id"]),
            self.store.rejected_and_refund(row["receipt_id"]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(await self.balance(), 100)

    async def test_admin_rejection_never_credits_balance(self):
        row = await self.reserve(admin_free=True)
        self.assertEqual(row["charged_cost"], 0)
        self.assertTrue(await self.store.rejected_and_refund(row["receipt_id"]))
        self.assertEqual(await self.balance(), 100)

    async def test_accepted_and_unknown_never_refund_or_restart(self):
        row = await self.reserve()
        await self.store.unknown(row["receipt_id"])
        self.assertFalse(await self.store.rejected_and_refund(row["receipt_id"]))
        replay = await self.reserve()
        self.assertFalse(replay["created"])
        self.assertEqual(replay["phase"], "outcome_unknown")
        self.assertTrue(await self.store.accepted(row["receipt_id"], "provider-1"))
        self.assertFalse(await self.store.rejected_and_refund(row["receipt_id"]))
        replay = await self.reserve()
        self.assertEqual(replay["provider_task_id"], "provider-1")
        self.assertEqual(await self.balance(), 90)

    async def test_conflicting_input_reuse_does_not_debit(self):
        await self.reserve()
        with self.assertRaises(module.MotionLaunchConflict):
            await self.reserve(recipe={"other": True})
        self.assertEqual(await self.balance(), 90)

    async def test_insufficient_funds_leave_no_receipt_or_partial_debit(self):
        with self.assertRaises(module.MotionInsufficientCredits):
            await self.reserve(cost=101)
        self.assertEqual(await self.balance(), 100)
        row = await self.reserve()
        self.assertTrue(row["created"])

    async def test_failed_receipt_insert_rolls_back_debit(self):
        normal_connect = self.connect

        @asynccontextmanager
        async def fail_insert():
            async with normal_connect() as db:
                original = db.execute

                async def execute(sql, *args):
                    if sql.startswith("INSERT INTO motion_launch_receipts"):
                        raise RuntimeError("synthetic persistence failure")
                    return await original(sql, *args)

                db.execute = execute
                yield db

        broken = module.MotionLaunchReceipts(fail_insert, aiosqlite.Row)
        with self.assertRaises(RuntimeError):
            await broken.reserve(user_id=1, telegram_id=101, request_key="a"*32,
                recipe={}, cost=10, admin_free=False)
        self.assertEqual(await self.balance(), 100)

    async def test_failed_refund_balance_write_rolls_back_marker(self):
        row = await self.reserve()
        normal_connect = self.connect

        @asynccontextmanager
        async def fail_credit():
            async with normal_connect() as db:
                original = db.execute

                async def execute(sql, *args):
                    if sql.startswith("UPDATE users SET credits = credits +"):
                        raise RuntimeError("synthetic credit failure")
                    return await original(sql, *args)

                db.execute = execute
                yield db

        broken = module.MotionLaunchReceipts(fail_credit, aiosqlite.Row)
        with self.assertRaises(RuntimeError):
            await broken.rejected_and_refund(row["receipt_id"])
        self.assertEqual(await self.balance(), 90)
        self.assertTrue(await self.store.rejected_and_refund(row["receipt_id"]))
        self.assertEqual(await self.balance(), 100)

    def test_transport_and_malformed_results_are_not_proven_rejections(self):
        for result in [None, {}, {"error": "network_error"}, {"error": "no_task_id"},
                       {"error": "invalid_json"}, {"error": "api_error", "status_code": 500},
                       {"task_id": "accepted", "error": "api_error", "status_code": 400},
                       {"error": "api_error", "status_code": 422, "raw": {"code": 422, "data": {"taskId": "accepted"}}}]:
            self.assertFalse(module.definitely_rejected_motion_result(result))
        self.assertTrue(module.definitely_rejected_motion_result({"error": "api_error", "status_code": 422}))


if __name__ == "__main__":
    unittest.main()
