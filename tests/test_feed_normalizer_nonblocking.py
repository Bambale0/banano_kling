"""Regression tests for the real feed normalizer: never hold DB locks during media I/O."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Cursor:
    def __init__(self, rows=(), rowcount=1):
        self.rows = rows
        self.rowcount = rowcount

    async def fetchall(self):
        return self.rows


class FakeDb:
    def __init__(self, state):
        self.state = state
        self.row_factory = None

    async def execute(self, sql, params):
        if "SELECT id, result_url, result_urls" in sql:
            self.state["events"].append("read")
            self.state["read_sql"].append(sql)
            last_id, limit = params
            rows = [row for row in self.state["rows"] if row["id"] > last_id]
            return Cursor(rows[:limit])
        self.state["events"].append("write")
        self.state["write_sql"].append(sql)
        self.state["write_params"].append(params)
        return Cursor(rowcount=self.state["write_rowcount"])

    async def commit(self):
        self.state["events"].append("commit")


class FakeContext:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        self.state["open_connections"] += 1
        self.state["events"].append("db_open")
        return FakeDb(self.state)

    async def __aexit__(self, exc_type, exc, tb):
        self.state["open_connections"] -= 1
        self.state["events"].append("db_close")


class NormalizerIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "events": [], "rows": [], "read_sql": [],
            "write_sql": [], "write_params": [], "write_rowcount": 1,
            "open_connections": 0,
        }
        source = ast.parse((ROOT / "bot/main.py").read_text(encoding="utf-8"))
        node = next(n for n in source.body
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "_normalize_public_feed_storage")

        module = types.ModuleType("bot.services.feed_persist")
        self.module = module
        self.patcher = patch.dict(sys.modules, {"bot.services.feed_persist": module})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        env = types.SimpleNamespace(getenv=lambda key, default=None: default)
        db = types.SimpleNamespace(
            Row=dict, connect=lambda: FakeContext(self.state)
        )
        namespace = {
            "asyncio": asyncio, "db_backend": db, "json": json,
            "logger": logging.getLogger(__name__), "os": env, "time": time,
            "_row_public_result_urls": lambda row: [row["result_url"]],
        }
        exec(  # noqa: S102
            compile(ast.Module(body=[node], type_ignores=[]), "bot/main.py", "exec"),
            namespace,
        )
        self.normalize = namespace["_normalize_public_feed_storage"]
        self.normalize._next_id = 0

    @staticmethod
    def row(index=1):
        return {
            "id": index, "result_url": f"https://provider.invalid/{index}.jpg",
            "result_urls": None,
        }

    async def test_media_operations_do_not_hold_db_connection_or_block_telegram_loop(self):
        self.state["rows"] = [self.row()]
        main_thread = threading.get_ident()

        async def slow_persist(_urls):
            self.assertEqual(self.state["open_connections"], 0)
            self.assertNotEqual(threading.get_ident(), main_thread)
            self.state["events"].append("media_start")
            await asyncio.sleep(0.08)
            self.state["events"].append("media_end")
            return ["https://durable.invalid/1.jpg"]

        self.module.persist_feed_result_urls = slow_persist

        async def telegram_heartbeat():
            await asyncio.sleep(0.015)
            self.state["events"].append("telegram_heartbeat")

        result, _ = await asyncio.gather(
            self.normalize(), telegram_heartbeat()
        )
        self.assertEqual(result, {
            "checked": 1, "updated": 1, "unchanged": 0, "failed": 0
        })
        events = self.state["events"]
        self.assertLess(events.index("db_close"), events.index("media_start"))
        self.assertLess(events.index("telegram_heartbeat"), events.index("media_end"))
        self.assertLess(events.index("media_end"), events.index("write"))
        self.assertEqual(self.state["open_connections"], 0)
        self.assertIn("commit", events)

    async def test_compare_and_swap_prevents_overwriting_newer_or_private_feed(self):
        self.state["rows"] = [self.row()]
        self.state["write_rowcount"] = 0

        async def persist(_urls):
            self.assertEqual(self.state["open_connections"], 0)
            return ["https://durable.invalid/1.jpg"]

        self.module.persist_feed_result_urls = persist
        result = await self.normalize()
        self.assertEqual(result, {
            "checked": 1, "updated": 0, "unchanged": 1, "failed": 0
        })
        self.assertEqual(len(self.state["write_sql"]), 1)
        sql = self.state["write_sql"][0]
        for safety in ("is_public_feed = 1", "status = 'completed'",
                       "result_url = ? OR (result_url IS NULL AND ? IS NULL)",
                       "result_urls = ? OR (result_urls IS NULL AND ? IS NULL)"):
            self.assertIn(safety, sql)
        params = self.state["write_params"][0]
        self.assertEqual(params[2], 1)
        self.assertEqual(params[3:], (
            self.state["rows"][0]["result_url"],
            self.state["rows"][0]["result_url"],
            None, None,
        ))

    async def test_network_failure_does_not_leave_a_open_transaction(self):
        self.state["rows"] = [self.row()]

        async def persist(_urls):
            self.assertEqual(self.state["open_connections"], 0)
            raise TimeoutError("simulated media-provider timeout")

        self.module.persist_feed_result_urls = persist
        with self.assertLogs(level="ERROR"):
            result = await self.normalize()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(self.state["open_connections"], 0)
        self.assertFalse(self.state["write_sql"])

    async def test_keyset_progresses_in_bounded_batches_without_starvation(self):
        self.state["rows"] = [self.row(i) for i in range(1, 42)]

        async def persist(urls):
            return urls

        self.module.persist_feed_result_urls = persist
        first = await self.normalize()
        self.assertEqual(first["checked"], 32)
        self.assertEqual(self.normalize._next_id, 32)
        second = await self.normalize()
        self.assertEqual(second["checked"], 9)
        self.assertEqual(self.normalize._next_id, 41)
        third = await self.normalize()
        self.assertEqual(third["checked"], 0)
        self.assertEqual(self.normalize._next_id, 0)
        self.assertEqual(self.state["open_connections"], 0)
        self.assertFalse(self.state["write_sql"])


if __name__ == "__main__":
    unittest.main()
