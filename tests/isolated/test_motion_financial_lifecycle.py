"""Real receipt SQL + selected watchdog function on disposable databases only.

Optional PostgreSQL uses a test-only asyncpg cursor shim, never the application
adapter. MOTION_TEST_PG_SOCKET must point into this worktree's isolated fixture.
"""
import ast
import asyncio
import importlib.util
import json
import logging
import math
import os
import re
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("motion_store_financial", ROOT / "bot/services/motion_launch_receipts.py")
receipts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipts)


class PgCursor:
    def __init__(self, rows, count):
        self.rows = rows
        self.rowcount = count

    async def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    async def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class PgFixture:
    """Minimal SQL protocol for these test statements; no runtime adapter code."""
    row_factory = None

    def __init__(self, conn):
        self.conn = conn
        self.tx = conn.transaction()
        self.active = False
        self.fail_credit = False

    async def start(self):
        await self.tx.start()
        self.active = True

    async def execute(self, sql, params=()):
        if self.fail_credit and sql.startswith("UPDATE users SET credits = credits +"):
            raise RuntimeError("synthetic credit fault")
        index = iter(range(1, len(params) + 1))
        sql = re.sub(r"\?", lambda _: "$" + str(next(index)), sql)
        if sql.lstrip().startswith("SELECT") or "RETURNING" in sql:
            rows = list(await self.conn.fetch(sql, *params))
            return PgCursor(rows, len(rows))
        status = await self.conn.execute(sql, *params)
        tail = status.rsplit(" ", 1)[-1]
        return PgCursor([], int(tail) if tail.isdigit() else 0)

    async def execute_native_ddl(self, sql):
        await self.conn.execute(sql)

    async def commit(self):
        if self.active:
            await self.tx.commit()
            self.active = False

    async def rollback(self):
        if self.active:
            await self.tx.rollback()
            self.active = False


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = str(Path(self.directory.name) / "synthetic.sqlite")
        self.socket = os.environ.get("MOTION_TEST_PG_SOCKET")
        self.fail_credit = False
        if self.socket:
            expected = ROOT / ".motion-pg-test" / "socket"
            if Path(self.socket).resolve() != expected.resolve():
                raise RuntimeError("Refusing non-fixture PostgreSQL socket")
            import asyncpg
            self.pg = await asyncpg.connect(host=self.socket, user="postgres", database="motion_test")
            await self.pg.execute("DROP TABLE IF EXISTS generation_tasks, motion_launch_receipts, users")
            await self.pg.close()
        async with self.connect() as db:
            await db.execute("CREATE TABLE users (id BIGINT PRIMARY KEY, telegram_id BIGINT, credits REAL, updated_at TIMESTAMP)")
            await db.execute("CREATE TABLE generation_tasks (id BIGINT PRIMARY KEY, user_id BIGINT, task_id TEXT, status TEXT, request_data TEXT, completed_at TIMESTAMP, updated_at TIMESTAMP)")
            await db.execute("INSERT INTO users (id, telegram_id, credits) VALUES (1, 5000000001, 100)")
            await db.commit()
        self.store = receipts.MotionLaunchReceipts(self.connect, aiosqlite.Row)
        await self.store.ensure_schema()
        ns = {"db_backend": SimpleNamespace(connect=self.connect, Row=aiosqlite.Row),
                  "DATABASE_PATH": self.path, "json": json, "math": math, "logger": logging.getLogger("test"),
                  "_is_admin_user": AsyncMock(return_value=True)}
        tree = ast.parse((ROOT / "bot/services/task_watchdog.py").read_text())
        selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "force_fail_task"]
        exec(compile(ast.Module(body=selected, type_ignores=[]), "watchdog_selected", "exec"), ns)  # noqa: S102 - fixed repository function, disposable database
        self.fail = ns["force_fail_task"]
        self.admin_lookup = ns["_is_admin_user"]

    @asynccontextmanager
    async def connect(self, *_):
        if self.socket:
            import asyncpg
            conn = await asyncpg.connect(host=self.socket, user="postgres", database="motion_test")
            db = PgFixture(conn)
            db.fail_credit = self.fail_credit
            await db.start()
            try:
                yield db
            finally:
                await db.rollback()
                await conn.close()
        else:
            async with aiosqlite.connect(self.path, timeout=10) as db:
                original = db.execute
                async def execute(sql, params=()):
                    if self.fail_credit and sql.startswith("UPDATE users SET credits = credits +"):
                        raise RuntimeError("synthetic credit fault")
                    return await original(sql, params)
                db.execute = execute
                yield db

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def row(self, sql):
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            return dict(await (await db.execute(sql)).fetchone())

    async def reserve(self, key="a"):
        return await self.store.reserve(user_id=1, telegram_id=5000000001, request_key=key*32,
            recipe={"version": 2, "charge_cost": 10}, cost=10, admin_free=False)

    async def accepted(self):
        receipt = await self.reserve()
        await self.store.accepted(receipt["receipt_id"], "provider-one")
        metadata = {"motion_launch_receipt_id": receipt["receipt_id"],
                    "motion_quote": {"version": 2, "charge_cost": 10},
                    "charged": True, "charged_cost": 10, "admin_free": False,
                    "refund_on_failure": True, "refund_claimed": False}
        async with self.connect() as db:
            await db.execute("INSERT INTO generation_tasks (id, user_id, task_id, status, request_data) VALUES (1, 1, ?, 'pending', ?)",
                             ("provider-one", json.dumps(metadata)))
            await db.commit()
        return receipt

    async def test_bigint_and_concurrent_reserve(self):
        results = await asyncio.gather(self.reserve(), self.reserve())
        self.assertEqual(sum(r["created"] for r in results), 1)
        self.assertEqual((await self.row("SELECT * FROM users"))["credits"], 90)
        self.assertEqual((await self.row("SELECT * FROM motion_launch_receipts"))["telegram_id"], 5000000001)

    async def test_pending_unknown_and_wrong_provider_cannot_refund(self):
        await self.accepted()
        self.assertFalse(await self.fail(1, 1, 10))
        self.assertFalse(await self.fail(1, 1, 10, expected_provider_task_id="different", provider_confirmed_failed=True))
        self.assertEqual((await self.row("SELECT * FROM users"))["credits"], 90)
        self.assertEqual((await self.row("SELECT * FROM generation_tasks"))["status"], "pending")

    async def test_terminal_failure_race_refunds_once_despite_later_admin_role(self):
        await self.accepted()
        results = await asyncio.gather(*[
            self.fail(1, 1, 999, expected_provider_task_id="provider-one", provider_confirmed_failed=True)
            for _ in range(2)])
        self.assertEqual(sum(results), 1)
        self.assertEqual((await self.row("SELECT * FROM users"))["credits"], 100)
        self.assertEqual((await self.row("SELECT * FROM motion_launch_receipts"))["refunded"], 1)
        self.admin_lookup.assert_not_awaited()

    async def test_refund_failure_rolls_back_task_receipt_and_balance(self):
        await self.accepted()
        self.fail_credit = True
        with self.assertRaises(RuntimeError):
            await self.fail(1, 1, 10, provider_confirmed_failed=True)
        self.fail_credit = False
        self.assertEqual((await self.row("SELECT * FROM users"))["credits"], 90)
        self.assertEqual((await self.row("SELECT * FROM generation_tasks"))["status"], "pending")
        self.assertEqual((await self.row("SELECT * FROM motion_launch_receipts"))["phase"], "accepted")
        self.assertTrue(await self.fail(1, 1, 10, provider_confirmed_failed=True))

    async def test_accepted_unbound_blocks_new_request_until_canonical_binding(self):
        receipt = await self.reserve()
        await self.store.accepted(receipt["receipt_id"], "provider-one")
        with self.assertRaises(receipts.MotionLaunchConflict):
            await self.reserve("b")
        rows = await self.store.unbound_accepted()
        self.assertEqual(rows[0]["provider_task_id"], "provider-one")
        await self.store.mark_bound(receipt["receipt_id"], "provider-one")
        self.assertEqual(await self.store.unbound_accepted(), [])
        self.assertTrue((await self.reserve("b"))["created"])


if __name__ == "__main__":
    unittest.main()
