"""Feed normalizer must run in independent, rate-limited background batches."""

from __future__ import annotations

import ast
import asyncio
import logging
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = (ROOT / "bot/main.py").read_text(encoding="utf-8")
TREE = ast.parse(CODE)


def _function(name: str):
    return next(node for node in TREE.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)


class NormalizerScheduleTests(unittest.IsolatedAsyncioTestCase):
    def _load(self, settings=None, sleep=None, normalizer=None):
        environment = types.SimpleNamespace(environ=settings or {})
        logger = logging.getLogger(__name__)
        namespace = {
            "os": environment, "logger": logger,
            "asyncio": types.SimpleNamespace(
                sleep=sleep or asyncio.sleep,
                CancelledError=asyncio.CancelledError,
            ),
            "_normalize_public_feed_storage": normalizer,
        }
        nodes = [_function("_feed_normalizer_interval_seconds"),
                 _function("_feed_normalizer_loop")]
        exec(  # noqa: S102
            compile(ast.Module(body=nodes, type_ignores=[]), "bot/main.py", "exec"),
            namespace,
        )
        return namespace

    def test_default_and_clamps(self):
        for supplied, expected in [(None, 900), ("0", 300), ("100", 300),
                                   ("900", 900), ("7200", 3600),
                                   ("invalid", 900)]:
            setting = {} if supplied is None else {
                "FEED_NORMALIZER_INTERVAL_SECONDS": supplied}
            self.assertEqual(
                self._load(setting)["_feed_normalizer_interval_seconds"](), expected
            )

    async def test_independent_cycle_is_serial_and_sleeps_between_batches(self):
        events = []

        async def sleep(seconds):
            events.append(("sleep", seconds))
            if len([x for x in events if x[0] == "sleep"]) == 3:
                raise asyncio.CancelledError

        async def normalizer():
            events.append(("run", None))
            await asyncio.sleep(0)
            return {"checked": 32, "updated": 0, "failed": 0, "unchanged": 32}

        namespace = self._load(
            {"FEED_NORMALIZER_INTERVAL_SECONDS": "300"},
            sleep=sleep, normalizer=normalizer,
        )
        with self.assertRaises(asyncio.CancelledError):
            await namespace["_feed_normalizer_loop"]()
        self.assertEqual(events, [
            ("sleep", 300), ("run", None), ("sleep", 300),
            ("run", None), ("sleep", 300),
        ])

    async def test_failed_pass_does_not_stop_next_tick(self):
        events = []

        async def sleep(seconds):
            events.append("sleep")
            if events.count("sleep") == 3:
                raise asyncio.CancelledError

        async def normalizer():
            events.append("run")
            if events.count("run") == 1:
                raise RuntimeError("synthetic media failure")
            return {"checked": 0, "updated": 0, "failed": 0}

        namespace = self._load(sleep=sleep, normalizer=normalizer)
        with self.assertLogs(level="ERROR"), self.assertRaises(asyncio.CancelledError):
            await namespace["_feed_normalizer_loop"]()
        self.assertEqual(events, ["sleep", "run", "sleep", "run", "sleep"])

    def test_cleanup_remains_daily_without_reentering_normalizer(self):
        cleanup = _function("_cleanup_loop")
        calls = [call.func.id for call in ast.walk(cleanup)
                 if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)]
        self.assertNotIn("_normalize_public_feed_storage", calls)
        self.assertIn("asyncio.create_task(_feed_normalizer_loop())", CODE)
        self.assertIn("asyncio.create_task(_cleanup_loop())", CODE)


if __name__ == "__main__":
    unittest.main()
