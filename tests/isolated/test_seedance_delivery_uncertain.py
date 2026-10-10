"""Run directly; never imports application bootstrap or database modules."""
import ast
import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)  # noqa: S102 - fixed repository source, isolated from application imports
    return namespace[name]


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


class Rejected(Exception):
    pass


class Uncertain(Exception):
    pass


class Retryable(Exception):
    def __init__(self, delay):
        self.retry_after = delay


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = types.SimpleNamespace(send_video=AsyncMock(), send_document=AsyncMock(),
                                         send_message=AsyncMock(), send_photo=AsyncMock())
        self.mark = AsyncMock()
        self.download = AsyncMock(return_value="/nonexistent/test.mp4")
        fake_bot = types.ModuleType("bot")
        fake_bot.keyboards = types.SimpleNamespace(get_video_result_keyboard=lambda *a, **kw: None)
        self.old_bot = sys.modules.get("bot")
        sys.modules["bot"] = fake_bot
        self.ns = {
            "web": types.SimpleNamespace(Application=dict),
            "Any": object, "logging": logging, "logger": logging.getLogger("test"),
            "types": types.SimpleNamespace(FSInputFile=lambda *a, **kw: "file"),
            "FSInputFile": lambda *a, **kw: "file",
            "os": __import__("os"), "MODEL_KEY": "seedance_2_5",
            "TelegramDeliveryUncertain": Uncertain,
            "TelegramDeliveryRetryable": Retryable,
            "telegram_delivery_retry_delay": lambda exc: exc.retry_after if isinstance(exc, Retryable) else None,
            "telegram_delivery_is_definitely_rejected": lambda exc: isinstance(exc, Rejected),
            "is_terminal_telegram_delivery_error": lambda exc: False,
            "terminal_telegram_delivery_reason": lambda exc: None,
            "fullstack": types.SimpleNamespace(_extension_from_url=lambda _: "mp4",
                _download_to_temp=self.download, _mark_seedance25_delivery=self.mark),
            "_extension_from_url": lambda _: "mp4", "_download_to_temp": self.download,
            "_mark_seedance25_delivery": self.mark,
        }

        load_function("bot/services/delivery_state.py", "tracked_telegram_send", self.ns)

    async def asyncTearDown(self):
        if self.old_bot is None:
            sys.modules.pop("bot", None)
        else:
            sys.modules["bot"] = self.old_bot

    async def run_delivery(self, path, name):
        fn = load_function(path, name, self.ns)
        return await fn({"bot": self.bot}, 1, "task", "https://example.test/result.mp4", None, {})

    async def test_public_timeout_never_retries_as_file_or_link(self):
        self.bot.send_video.side_effect = TimeoutError("response lost")
        with self.assertRaises(Uncertain):
            await self.run_delivery("bot/handlers/seedance_25_public_release.py", "_public_send_results")
        self.assertEqual(self.bot.send_video.await_count, 1)
        self.download.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_admin_timeout_never_retries_as_file_or_link(self):
        self.bot.send_video.side_effect = TimeoutError("response lost")
        with self.assertRaises(Uncertain):
            await self.run_delivery("bot/handlers/seedance_25_fullstack.py", "_send_seedance25_results")
        self.assertEqual(self.bot.send_video.await_count, 1)
        self.download.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_explicit_rejection_allows_downloaded_file(self):
        self.bot.send_video.side_effect = [Rejected("wrong file"), None]
        self.assertTrue(await self.run_delivery("bot/handlers/seedance_25_public_release.py", "_public_send_results"))
        self.assertEqual(self.bot.send_video.await_count, 2)

    async def test_file_timeout_never_sends_link(self):
        self.bot.send_video.side_effect = [Rejected("wrong file"), TimeoutError("response lost")]
        with self.assertRaises(Uncertain):
            await self.run_delivery("bot/handlers/seedance_25_public_release.py", "_public_send_results")
        self.bot.send_message.assert_not_awaited()

    async def test_link_timeout_is_uncertain(self):
        self.bot.send_video.side_effect = Rejected("bad media")
        self.download.return_value = None
        self.bot.send_message.side_effect = TimeoutError("response lost")
        with self.assertRaises(Uncertain):
            await self.run_delivery("bot/handlers/seedance_25_public_release.py", "_public_send_results")
        self.assertEqual(self.bot.send_message.await_count, 1)

    async def test_uncertain_is_not_automatically_retryable(self):
        ns = {}
        exec(compile((ROOT / "bot/services/delivery_state.py").read_text(),  # noqa: S102 - fixed pure repository module only
                     "delivery_state.py", "exec"), ns)
        self.assertIn("uncertain", ns["TASK_DELIVERY_STATUSES"])
        self.assertIn("uncertain", ns["TERMINAL_TASK_DELIVERY_STATUSES"])
        self.assertNotIn("uncertain", ns["RETRYABLE_TASK_DELIVERY_STATUSES"])

    async def test_explicit_rate_limit_does_not_fallback(self):
        for path, name in [
            ("bot/handlers/seedance_25_public_release.py", "_public_send_results"),
            ("bot/handlers/seedance_25_fullstack.py", "_send_seedance25_results"),
        ]:
            self.bot.send_video.side_effect = Retryable(75)
            with self.assertRaises(Retryable) as caught:
                await self.run_delivery(path, name)
            self.assertEqual(caught.exception.retry_after, 75)
        self.download.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_dispatcher_honors_rate_limit_and_presend_timeout(self):
        self.ns.update(asyncio=asyncio, SEEDANCE25_DELIVERY_TIMEOUT_SECONDS=1,
            _can_attempt_seedance25_result_delivery=AsyncMock(return_value=True),
            _claim_seedance25_delivery=AsyncMock(return_value=True),
            _stored_result_urls=lambda _: ["https://example.test/result.mp4"],
            _classify_results=lambda *a: ("https://example.test/result.mp4", None))
        fn = load_function("bot/handlers/seedance_25_fullstack.py", "_retry_seedance25_delivery", self.ns)
        self.ns["_send_seedance25_results"] = AsyncMock(side_effect=Retryable(75))
        await fn({"bot": self.bot}, {"task_id": "task", "telegram_id": 1}, {})
        self.assertEqual(self.mark.call_args.args[:2], ("task", "pending"))
        self.assertEqual(self.mark.call_args.kwargs["retry_after_seconds"], 75)
        self.ns["_send_seedance25_results"] = AsyncMock(side_effect=TimeoutError())
        await fn({"bot": self.bot}, {"task_id": "task", "telegram_id": 1}, {})
        self.assertEqual(self.mark.call_args.args[:2], ("task", "pending"))
        await fn({"bot": self.bot}, {"task_id": "task", "telegram_id": 1},
                 {"_telegram_send_inflight": True})
        self.assertEqual(self.mark.call_args.args[:2], ("task", "uncertain"))

    async def test_auxiliary_rate_limit_or_timeout_never_requeues_primary(self):
        self.ns.update(asyncio=asyncio, SEEDANCE25_DELIVERY_TIMEOUT_SECONDS=1,
            _can_attempt_seedance25_result_delivery=AsyncMock(return_value=True),
            _claim_seedance25_delivery=AsyncMock(return_value=True),
            _stored_result_urls=lambda _: ["https://example.test/result.mp4"],
            _classify_results=lambda *a: ("https://example.test/result.mp4", "frame"))
        fn = load_function("bot/handlers/seedance_25_fullstack.py", "_retry_seedance25_delivery", self.ns)
        for error in [Retryable(75), TimeoutError(), Uncertain(), RuntimeError()]:
            self.ns["_send_seedance25_results"] = AsyncMock(side_effect=error)
            self.assertTrue(await fn({"bot": self.bot}, {"task_id": "task", "telegram_id": 1},
                 {"_telegram_primary_delivered": True}))
            self.assertEqual(self.mark.call_args.args[:2], ("task", "delivered"))

    async def test_actual_auxiliary_rejection_chain_preserves_primary(self):
        self.ns.update(asyncio=asyncio, SEEDANCE25_DELIVERY_TIMEOUT_SECONDS=1,
            _can_attempt_seedance25_result_delivery=AsyncMock(return_value=True),
            _claim_seedance25_delivery=AsyncMock(return_value=True),
            _stored_result_urls=lambda _: ["https://example.test/result.mp4"],
            _classify_results=lambda *a: ("https://example.test/result.mp4", "frame"))
        dispatcher = load_function("bot/handlers/seedance_25_fullstack.py", "_retry_seedance25_delivery", self.ns)
        for path, name in [
            ("bot/handlers/seedance_25_public_release.py", "_public_send_results"),
            ("bot/handlers/seedance_25_fullstack.py", "_send_seedance25_results"),
        ]:
            self.bot.send_video.reset_mock()
            self.bot.send_message.reset_mock()
            self.ns["aiohttp"] = types.SimpleNamespace(
                ClientTimeout=lambda **kw: None,
                ClientSession=lambda: AsyncContext(types.SimpleNamespace(
                    get=lambda *a, **kw: AsyncContext(types.SimpleNamespace(status=404)))))
            self.bot.send_photo.side_effect = Rejected("bad photo")
            self.bot.send_message.side_effect = Retryable(75)
            self.ns["_send_seedance25_results"] = load_function(path, name, self.ns)
            self.assertTrue(await dispatcher({"bot": self.bot},
                {"task_id": "task", "telegram_id": 1}, {"return_last_frame": True}))
            self.assertEqual(self.bot.send_video.await_count, 1)
            self.assertEqual(self.bot.send_message.await_count, 1)
            self.assertEqual(self.mark.call_args.args[:2], ("task", "delivered"))

    async def test_tracker_clears_each_confirmed_rejection(self):
        for error in [Rejected("bad"), Retryable(75)]:
            progress = {}
            with self.assertRaises(type(error)):
                await self.ns["tracked_telegram_send"](progress, False,
                    AsyncMock(side_effect=error), 1)
            self.assertFalse(progress["_telegram_send_inflight"])

    async def test_dispatcher_stores_uncertain_and_does_not_requeue(self):
        self.ns.update(asyncio=asyncio, SEEDANCE25_DELIVERY_TIMEOUT_SECONDS=1,
            _can_attempt_seedance25_result_delivery=AsyncMock(return_value=True),
            _claim_seedance25_delivery=AsyncMock(return_value=True),
            _stored_result_urls=lambda _: ["https://example.test/result.mp4"],
            _classify_results=lambda *a: ("https://example.test/result.mp4", None),
            _send_seedance25_results=AsyncMock(side_effect=Uncertain("response lost")))
        fn = load_function("bot/handlers/seedance_25_fullstack.py", "_retry_seedance25_delivery", self.ns)
        await fn({"bot": self.bot}, {"task_id": "task", "telegram_id": 1}, {})
        self.assertEqual(self.mark.call_args.args[:2], ("task", "uncertain"))


if __name__ == "__main__":
    unittest.main()
