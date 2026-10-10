"""Atomic Seedance callback/watchdog refund using synthetic test database only."""
import ast
import importlib.util
import json
import logging
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("receipt_fixture", ROOT / "tests/isolated/test_seedance_quote_receipts.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class RefundTests(fixture.ReceiptTests):
    async def setup_task(self):
        await self.claim()
        await self.store.accepted(self.quote["quote_id"], "provider-1")
        async with self.connect() as db:
            await db.execute("DROP TABLE IF EXISTS generation_tasks")
            await db.execute("CREATE TABLE generation_tasks (id BIGINT PRIMARY KEY,task_id TEXT,status TEXT,request_data TEXT,completed_at TIMESTAMP,updated_at TIMESTAMP)")
            metadata = {"seedance_quote_id": self.quote["quote_id"], "billing_quote": self.billing,
                        "charged": True,"charged_cost":48,"refund_on_failure":True,"admin_free":False}
            await db.execute("INSERT INTO generation_tasks (id,task_id,status,request_data) VALUES (1,'provider-1','pending',?)", (json.dumps(metadata),))
            await db.commit()
        tree = ast.parse((ROOT / "bot/services/task_watchdog.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "force_fail_task"]
        self.admin = AsyncMock(return_value=True)
        namespace = {"db_backend":SimpleNamespace(connect=lambda _: self.connect(), Row=aiosqlite.Row),
                     "DATABASE_PATH":"synthetic", "json":json,"math":math,"logger":logging.getLogger(__name__),"_is_admin_user":self.admin}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),"selected_refund","exec"),namespace)  # noqa: S102
        self.fail = namespace["force_fail_task"]

    async def test_unknown_age_does_not_refund(self):
        await self.setup_task()
        self.assertFalse(await self.fail(1,1,48))
        self.assertEqual(await self.balance(),52)
        async with self.connect() as db:
            self.assertEqual((await (await db.execute("SELECT status FROM generation_tasks WHERE id=1")).fetchone())[0],"pending")

    async def test_terminal_refund_once_uses_frozen_paid_role(self):
        await self.setup_task()
        self.assertTrue(await self.fail(1,1,999,expected_provider_task_id="provider-1",provider_confirmed_failed=True))
        self.assertFalse(await self.fail(1,1,999,expected_provider_task_id="provider-1",provider_confirmed_failed=True))
        self.assertEqual(await self.balance(),100)
        self.admin.assert_not_awaited()
        async with self.connect() as db:
            self.assertEqual((await (await db.execute("SELECT phase FROM seedance_quote_receipts")).fetchone())[0],"provider_failed")

    async def test_mismatched_provider_never_refunds(self):
        await self.setup_task()
        self.assertFalse(await self.fail(1,1,48,expected_provider_task_id="another",provider_confirmed_failed=True))
        self.assertEqual(await self.balance(),52)

    async def test_media_validation_failure_rolls_back_before_debit(self):
        self.store.validate_media = AsyncMock(side_effect=fixture.module.QuoteConflict("missing media"))
        with self.assertRaises(fixture.module.QuoteConflict):
            await self.claim()
        self.assertEqual(await self.balance(),100)


if __name__ == "__main__":
    unittest.main()
