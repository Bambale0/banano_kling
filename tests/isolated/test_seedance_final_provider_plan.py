"""Actual adapter methods with mocked _kie_post: no provider, config, or DB imports."""
import ast
import hashlib
import logging
import unittest
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[2]


class FakeKling:
    CREATE_TASK_ENDPOINT = "/api/v1/jobs/createTask"
    def __init__(self, **_):
        self.kie_key = "synthetic-not-a-credential"
    @staticmethod
    def _build_error(code, message):
        return {"error":code,"message":message}


def adapter(model):
    name = "SeedanceService" if model == "seedance_2" else "Seedance25Service"
    path = "bot/services/seedance_service.py" if model == "seedance_2" else "bot/services/seedance_25_service.py"
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node,ast.ClassDef) and node.name == name
             or isinstance(node,ast.FunctionDef) and node.name == "_clean_unique_urls"]
    namespace = {"Any":Any,"ClassVar":ClassVar,"Iterable":Iterable,"KlingService":FakeKling,
        "logger":logging.getLogger(__name__),"hashlib":hashlib,"config":SimpleNamespace(kie_notification_url=""),
        "canonicalize_local_upload_url":lambda value:value,
        "canonicalize_seedance_reference_tags":lambda prompt,**_:prompt,
        "missing_seedance_reference_tags":lambda *_,**__:[],
        "get_seedance25_callback_url":lambda:"", "IDENTITY_ROLE_VERSION":1,
        "SEEDANCE_25_PROMPT_MAX_CHARS":30000,
        "validate_identity_transfer_refs":Mock(),
        "resolve_identity_transfer_prompt":AsyncMock(return_value="TEMPLATE_B"),
        "build_identity_transfer_prompt":lambda prompt,**_:prompt}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),path,"exec"),namespace)  # noqa: S102
    instance = namespace[name]()
    instance._kie_post = AsyncMock(return_value={"task_id":"synthetic-provider-id"})
    instance._prepare_image_urls = AsyncMock(return_value=([],[],[]))
    return instance, namespace


class ProviderPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordered_pinned_occurrences_reach_both_actual_provider_payloads(self):
        # A and A are deliberate slots, pinned to distinct immutable object URLs.
        urls = ["https://example.test/pinned-a-slot0.mp4", "https://example.test/pinned-b-slot0.mp4", "https://example.test/pinned-a-slot1.mp4"]
        for model in ("seedance_2","seedance_2_5"):
            service,_ = adapter(model)
            result = await service.generate_video(prompt="Use @Video1 @Video2 @Video3",duration=5,reference_video_urls=urls)
            self.assertEqual(result["task_id"],"synthetic-provider-id")
            body = service._kie_post.await_args.args[1]
            self.assertEqual(body["input"]["reference_video_urls"],urls)
            self.assertEqual(body["input"]["duration"],5)
            self.assertNotIn("_snapshot_media_ids",body["input"])

    async def test_frozen_identity_prompt_never_reads_mutated_template_after_debit(self):
        service, namespace = adapter("seedance_2_5")
        service.prepare_prompt = Mock(side_effect=AssertionError("must not rebuild approved prompt"))
        await service.generate_video(prompt="FROZEN_TEMPLATE_A @Image1 @Video1",duration=-1,
            reference_image_urls=["https://example.test/image.png"],reference_video_urls=["https://example.test/pinned.mp4"],
            identity_transfer=True,_prompt_is_prepared=True)
        namespace["resolve_identity_transfer_prompt"].assert_not_awaited()
        service.prepare_prompt.assert_not_called()
        body = service._kie_post.await_args.args[1]
        self.assertEqual(body["input"]["prompt"],"FROZEN_TEMPLATE_A @Image1 @Video1")
        self.assertEqual(body["input"]["omni_reference_task_type"],"edit")
        self.assertNotIn("_prompt_is_prepared",body["input"])

    async def test_effective_plan_normalizes_accidental_aliases_but_preserves_declared_slots(self):
        tree = ast.parse((ROOT / "bot/services/seedance_quote_lifecycle.py").read_text())
        node = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == "effective_video_sources")
        node.body = [part for part in node.body if not isinstance(part,ast.ImportFrom)]
        namespace = {"canonicalize_local_upload_url":lambda value:value.replace("alias-A","A"),"QuoteConflict":ValueError}
        exec(compile(ast.Module(body=[node],type_ignores=[]),"effective_sources","exec"),namespace)  # noqa: S102
        plan = namespace["effective_video_sources"]
        ordinary = {"video_urls":["A","alias-A","B"]}
        self.assertEqual(plan(ordinary,"video_urls","seedance_2"),["A","B"])
        self.assertEqual(plan(dict(ordinary,reference_contract="typed-slots"),"video_urls","seedance_2"),["A","A","B"])
        with self.assertRaises(ValueError):
            plan({"video_urls":["A","B","C","D"]},"video_urls","seedance_2")


if __name__ == "__main__":
    unittest.main()
