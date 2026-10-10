"""HTTP seam with real new receipt store on synthetic SQLite; no app bootstrap."""
import ast
import importlib.util
import json
import logging
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import aiosqlite
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]


def load_file(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receipts = load_file("receipts_under_test", "bot/services/motion_launch_receipts.py")
quotes = load_file("quotes_under_test", "bot/services/motion_quote.py")


def functions(namespace):
    tree = ast.parse((ROOT / "bot/handlers/motion_launch.py").read_text())
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name in {"_pending", "_bind_accepted", "persist_accepted_motion", "generate_motion", "status_motion", "recover_accepted_motion"}]
    exec(compile(ast.Module(body=selected, type_ignores=[]), "motion_launch.py", "exec"), namespace)  # noqa: S102 - fixed repository functions with synthetic dependencies


class MotionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = str(Path(self.directory.name) / "synthetic.sqlite")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER, credits REAL, updated_at TEXT)")
            await db.execute("INSERT INTO users VALUES (1, 101, 100, 'initial')")
            await db.commit()
        self.provider = AsyncMock(return_value={"task_id": "provider-1"})
        fake_bot = types.ModuleType("bot")
        fake_bot.db = types.SimpleNamespace(connect=lambda: aiosqlite.connect(self.path), Row=aiosqlite.Row)
        fake_kling = types.ModuleType("bot.services.kling_service")
        fake_kling.kling_service = types.SimpleNamespace(generate_motion_control=self.provider)
        self.old = {key: sys.modules.get(key) for key in ["bot", "bot.services.kling_service"]}
        sys.modules.update({"bot": fake_bot, "bot.services.kling_service": fake_kling})
        self.quote = quotes.build_motion_quote(
            model="motion_control_v26", quality="720p", direction="video", prompt="test",
            image_url="image", video_url="video", source_sha256="hash", source_seconds=5,
            rate=1, admin_free=False, format_cost=lambda x: round(x*2)/2)
        self.api = types.SimpleNamespace(
            config=types.SimpleNamespace(WEBHOOK_HOST="", kie_notification_url=""),
            _get_user_context=AsyncMock(return_value=(101, {"user": types.SimpleNamespace(id=1)})),
            add_generation_task=AsyncMock(return_value=True),
            get_generation_task_payload=AsyncMock(return_value={"status": "pending"}),
            get_or_create_user=AsyncMock(return_value=types.SimpleNamespace(credits=90)),
            _miniapp_error_response=lambda *a, **kw: web.json_response({"ok": False}, status=500),
        )
        self.ns = {"json": json, "math": math, "web": web, "logger": logging.getLogger("test"),
            "MotionLaunchReceipts": receipts.MotionLaunchReceipts,
            "MotionLaunchConflict": receipts.MotionLaunchConflict,
            "MotionInsufficientCredits": receipts.MotionInsufficientCredits,
            "definitely_rejected_motion_result": receipts.definitely_rejected_motion_result,
            "_validated_quote": AsyncMock(side_effect=lambda *_: dict(self.quote))}
        functions(self.ns)

    async def asyncTearDown(self):
        for key, value in self.old.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
        self.directory.cleanup()

    async def balance(self):
        async with aiosqlite.connect(self.path) as db:
            return (await (await db.execute("SELECT credits FROM users")).fetchone())[0]

    async def launch(self, **overrides):
        body = {"motion_request_id": "a"*32, "motion_quote_hash": self.quote["quote_hash"],
                "motion_duration": 1}
        body.update(overrides)
        request = types.SimpleNamespace(app={}, json=AsyncMock(return_value=body))
        return await self.ns["generate_motion"](request, self.api)

    async def test_accepted_persistence_failure_never_refunds_and_replay_recovers(self):
        self.api.add_generation_task.side_effect = RuntimeError("synthetic persistence fault")
        response = await self.launch()
        self.assertEqual(response.status, 409)
        self.assertEqual(await self.balance(), 90)
        self.api.add_generation_task.side_effect = None
        response = await self.launch()
        self.assertEqual(response.status, 200)
        self.provider.assert_awaited_once()
        self.assertEqual(await self.balance(), 90)

    async def test_background_recovery_binds_without_browser_or_provider_replay(self):
        self.api.add_generation_task.side_effect = RuntimeError("synthetic canonical fault")
        self.assertEqual((await self.launch()).status, 409)
        self.api.add_generation_task.side_effect = None
        sys.modules["bot"].database = types.SimpleNamespace(add_generation_task=self.api.add_generation_task)
        self.assertEqual(await self.ns["recover_accepted_motion"](), 1)
        self.assertEqual(await self.ns["recover_accepted_motion"](), 0)
        self.provider.assert_awaited_once()
        self.assertEqual(await self.balance(), 90)

    async def test_status_owner_isolation_and_accepted_retrieval(self):
        self.assertEqual((await self.launch()).status, 200)
        request = types.SimpleNamespace(app={}, json=AsyncMock(return_value={"motion_request_id": "a"*32}))
        self.api.get_generation_task_payload.return_value = {"status": "completed", "result_url": "https://example.test/result.mp4"}
        result = await self.ns["status_motion"](request, self.api)
        self.assertEqual(json.loads(result.body)["task_id"], "provider-1")
        self.assertEqual(json.loads(result.body)["status"], "done")
        self.api._get_user_context.return_value = (202, {"user": types.SimpleNamespace(id=2)})
        result = await self.ns["status_motion"](request, self.api)
        self.assertEqual(json.loads(result.body)["status"], "not_found")
        self.provider.assert_awaited_once()

    async def test_raw_acceptance_witness_cannot_refund_on_422(self):
        self.provider.return_value = {"error": "api_error", "status_code": 422,
                                      "raw": {"data": {"taskId": "accepted-hidden"}}}
        self.assertEqual((await self.launch()).status, 409)
        self.assertEqual(await self.balance(), 90)

    async def test_duplicate_canonical_binding_checks_receipt_identity(self):
        self.assertEqual((await self.launch()).status, 200)
        receipt_id = "motion_launch_101_" + "a" * 32
        fake_database = types.ModuleType("bot.database")
        fake_database.get_generation_task_payload = AsyncMock(return_value={
            "request_data": json.dumps({"motion_launch_receipt_id": receipt_id})})
        prior = sys.modules.get("bot.database")
        sys.modules["bot.database"] = fake_database
        try:
            self.api.add_generation_task.return_value = False
            self.assertEqual((await self.launch()).status, 200)
            fake_database.get_generation_task_payload.return_value = {"request_data": "{}"}
            self.assertEqual((await self.launch()).status, 409)
            self.assertEqual(await self.balance(), 90)
            self.provider.assert_awaited_once()
        finally:
            if prior is None:
                sys.modules.pop("bot.database", None)
            else:
                sys.modules["bot.database"] = prior

    async def test_transport_exception_holds_debit_without_second_submission(self):
        self.provider.side_effect = TimeoutError("unknown acceptance")
        self.assertEqual((await self.launch()).status, 409)
        self.assertEqual(await self.balance(), 90)
        self.assertEqual((await self.launch()).status, 409)
        self.provider.assert_awaited_once()

    async def test_admin_transport_exception_never_creates_money(self):
        self.quote.update(admin_free=True, charge_cost=0)
        self.provider.side_effect = TimeoutError()
        await self.launch()
        self.assertEqual(await self.balance(), 100)

    async def test_transport_error_dict_is_unknown_and_new_key_is_blocked(self):
        self.provider.return_value = {"error": "network_error"}
        self.assertEqual((await self.launch()).status, 409)
        self.assertEqual((await self.launch(motion_request_id="b"*32)).status, 409)
        self.provider.assert_awaited_once()
        self.assertEqual(await self.balance(), 90)

    async def test_explicit_rejection_refunds_exactly_once(self):
        self.provider.return_value = {"error": "api_error", "status_code": 422}
        self.assertEqual((await self.launch()).status, 400)
        self.assertEqual((await self.launch()).status, 400)
        self.provider.assert_awaited_once()
        self.assertEqual(await self.balance(), 100)

    async def test_stale_quote_never_debits_or_launches(self):
        self.assertEqual((await self.launch(motion_quote_hash="stale")).status, 409)
        self.provider.assert_not_awaited()
        self.assertEqual(await self.balance(), 100)

    async def test_client_duration_is_not_price_or_provider_input(self):
        self.assertEqual((await self.launch(motion_duration=1)).status, 200)
        self.assertEqual(await self.balance(), 90)
        self.assertNotIn("duration", self.provider.call_args.kwargs)
        self.assertEqual(self.api.add_generation_task.call_args.kwargs["duration"], 5)


class QuoteTests(unittest.TestCase):
    def quote(self, **overrides):
        args = {"model": "motion_control_v26", "quality": "720p", "direction": "video", "prompt": "test",
            "image_url": "image", "video_url": "video", "source_sha256": "hash", "source_seconds": 7,
            "rate": 4, "admin_free": False, "format_cost": lambda x: round(x*2)/2}
        args.update(overrides)
        return quotes.build_motion_quote(**args)

    def test_source_locked_input_and_output(self):
        quote = self.quote()
        self.assertEqual(quote["cost"], 56)
        self.assertEqual(quote["input_seconds"], 7)
        self.assertEqual(quote["output_seconds"], 7)

    def test_bad_duration_and_rate_fail_closed(self):
        for duration in [0, -1, float("nan"), float("inf"), 31, True]:
            with self.assertRaises(ValueError):
                self.quote(source_seconds=duration)
        for rate in [0, -1, float("nan"), float("inf"), True]:
            with self.assertRaises(ValueError):
                self.quote(rate=rate)
        with self.assertRaises(ValueError):
            self.quote(source_seconds=11, direction="image")

    def test_quote_binds_content_rate_and_settings(self):
        old = self.quote()["quote_hash"]
        for change in [{"rate": 5}, {"source_sha256": "different"}, {"source_seconds": 8},
                       {"quality": "1080p"}, {"admin_free": True}]:
            self.assertNotEqual(self.quote(**change)["quote_hash"], old)


if __name__ == "__main__":
    unittest.main()
