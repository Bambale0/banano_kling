"""Selected lifecycle controller, mocked provider and repository; no app imports."""
import ast
import json
import logging
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]


class QuoteConflict(ValueError):
    pass


def load_functions():
    names = {"confirmed_rejection", "submit_claimed_quote"}
    tree = ast.parse((ROOT / "bot/services/seedance_quote_lifecycle.py").read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    witness_tree = ast.parse((ROOT / "bot/services/motion_launch_receipts.py").read_text())
    nodes += [node for node in witness_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_has_acceptance_witness"]
    namespace = {"json": json, "logger": logging.getLogger(__name__), "QuoteConflict": QuoteConflict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "selected_lifecycle", "exec"), namespace)  # noqa: S102
    return namespace


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = load_functions()
        self.store = type("Store", (), {})()
        for name in ("unknown", "accepted", "rejected_and_refund"):
            setattr(self.store, name, AsyncMock(return_value=True))
        self.ns["receipt_store"] = AsyncMock(return_value=self.store)
        self.submit = AsyncMock(return_value={"task_id":"provider-1"})
        self.bind = AsyncMock()
        self.row = {"quote_id":"q", "phase":"submitting", "provider_json":"{}", "created":True}

    async def launch(self):
        return await self.ns["submit_claimed_quote"](self.row, submit=self.submit, bind=self.bind)

    async def test_actual_seedance25_callback_passes_owner_and_cost_to_atomic_refund(self):
        from types import SimpleNamespace

        tree = ast.parse((ROOT / "bot/handlers/seedance_25_public_release.py").read_text())
        node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_public_process_payload")
        class StripImports(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None if (node.module or "").startswith("bot") else node
        node = StripImports().visit(node)
        node.returns = None
        for arg in node.args.args:
            arg.annotation = None
        metadata = {"seedance_quote_id":"q", "charged_cost":48}
        fullstack = SimpleNamespace(_load_task_row=AsyncMock(return_value={"id":11,"user_id":22,"request_data":json.dumps(metadata)}),
                                    _auto_retry_seedance25_video_editing=AsyncMock(), _process_seedance25_payload_original=AsyncMock())
        fail = AsyncMock(return_value=True)
        ns = {"json":json,"fullstack":fullstack,"force_fail_task":fail,"logger":logging.getLogger(__name__)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "actual_seedance_callback", "exec"), ns)  # noqa: S102
        handler = ns["_public_process_payload"]
        self.assertTrue(await handler({}, {"data":{"taskId":"provider-1","state":"fail","failMsg":"failed"}}))
        fail.assert_awaited_once_with(11,22,48.0,expected_provider_task_id="provider-1",provider_confirmed_failed=True)
        self.assertFalse(await handler({}, {"code":500,"data":{"taskId":"provider-1","state":"processing"}}))
        self.assertEqual(fail.await_count,1)
        fullstack._auto_retry_seedance25_video_editing.assert_not_awaited()
        fullstack._process_seedance25_payload_original.assert_not_awaited()

    async def test_accepted_is_persisted_before_binding(self):
        async def bind(row):
            self.store.accepted.assert_awaited_once_with("q", "provider-1")
            self.assertEqual(row["provider_task_id"], "provider-1")
        self.bind.side_effect = bind
        result = await self.launch()
        self.assertEqual(result["phase"], "accepted")
        self.store.rejected_and_refund.assert_not_awaited()

    async def test_network_unknown_no_refund_or_resubmit(self):
        self.submit.side_effect = TimeoutError()
        self.assertEqual((await self.launch())["phase"], "outcome_unknown")
        self.store.unknown.assert_awaited_once()
        self.store.rejected_and_refund.assert_not_awaited()
        self.bind.assert_not_awaited()

    async def test_malformed_and_nested_acceptance_are_unknown(self):
        for result in (None, {}, {"error":"api_error","status_code":422,"raw":{"data":{"taskId":"accepted"}}}):
            self.submit.return_value = result
            self.assertEqual((await self.launch())["phase"], "outcome_unknown")
        self.store.rejected_and_refund.assert_not_awaited()

    async def test_confirmed_rejection_refunds(self):
        self.submit.return_value = {"error":"api_error","status_code":422}
        self.assertEqual((await self.launch())["phase"], "rejected")
        self.store.rejected_and_refund.assert_awaited_once_with("q")
        self.bind.assert_not_awaited()

    async def test_binding_error_never_refunds_known_acceptance(self):
        self.bind.side_effect = RuntimeError("synthetic persistence failure")
        with self.assertRaises(RuntimeError):
            await self.launch()
        self.store.accepted.assert_awaited_once()
        self.store.rejected_and_refund.assert_not_awaited()

    async def test_replayed_accepted_only_binds_and_unknown_does_nothing(self):
        self.row.update(created=False, phase="accepted", provider_task_id="provider-1")
        await self.launch()
        self.bind.assert_awaited_once()
        self.row["phase"] = "outcome_unknown"
        await self.launch()
        self.submit.assert_not_awaited()
        self.assertEqual(self.bind.await_count, 1)

    async def test_acceptance_commit_failure_logs_id_without_refund(self):
        self.store.accepted.side_effect = RuntimeError("commit")
        with self.assertLogs(self.ns["logger"], level="INFO") as logs, self.assertRaises(RuntimeError):
            await self.launch()
        self.assertIn("provider-1", " ".join(logs.output))
        self.store.rejected_and_refund.assert_not_awaited()
        self.bind.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
