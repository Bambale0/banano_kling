"""Real adapter definitions with synthetic base transport; no app imports/network."""
import ast
import hashlib
import importlib.util
import json
import logging
import math
import re
import secrets
import sys
import unittest
import uuid
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from string import Formatter
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]


class Transport:
    CREATE_TASK_ENDPOINT = "/api/v1/jobs/createTask"
    kie_key = "synthetic"


def adapter_classes():
    ns = {"KlingService": Transport, "Iterable": Iterable, "Any": Any, "re": re,
              "Formatter": Formatter, "logger": logging.getLogger("test"),
              "canonicalize_local_upload_url": lambda value: value}
    for name in ["wan3_prime_service.py", "wan3_standard_service.py"]:
        tree = ast.parse((ROOT / "bot/services" / name).read_text())
        selected = [node for node in tree.body if isinstance(node, (
            ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef
        )) or isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id.isupper() for target in node.targets
        )]
        exec(compile(ast.Module(body=selected, type_ignores=[]), name, "exec"), ns)  # noqa: S102 - fixed adapter definitions, synthetic transport
    ns["get_wan3_edit_template"] = AsyncMock(return_value=ns["DEFAULT_WAN3_EDIT_TEMPLATE"])
    return ns


def pure_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {name: module}):
        spec.loader.exec_module(module)
    return module


class BillingTests(unittest.TestCase):
    def test_new_fixed_quote_never_reprices_short_or_long_output(self):
        billing = pure_module("wan_billing_isolated", "bot/services/wan3_billing.py")
        quote = {"version": 2, "billing_mode": "input_plus_selected_output",
                 "input_video_seconds": 7, "requested_output_seconds": 5, "rate_per_second": 4}
        for measured in (4, 4.7, 5, 20):
            self.assertEqual(billing.settlement_amounts(quote, 48, measured), (48, 0))
        self.assertEqual(billing.settlement_amounts(quote, 0, 5), (0, 0))

    def test_legacy_and_auto_keep_actual_duration_refund(self):
        billing = pure_module("wan_billing_isolated", "bot/services/wan3_billing.py")
        legacy = {"input_video_seconds": 7, "rate_per_second": 4}
        self.assertEqual(billing.settlement_amounts(legacy, 48, 4), (44, 4))
        auto = {**legacy, "version": 2, "billing_mode": "auto_reserve"}
        self.assertEqual(billing.settlement_amounts(auto, 120, 4), (44, 76))


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.models = pure_module("bot.services.wan3_models", "bot/services/wan3_models.py")
        modules = {"bot": ModuleType("bot"), "bot.services": ModuleType("bot.services"),
                   "bot.services.wan3_models": self.models}
        with patch.dict(sys.modules, modules):
            self.media = pure_module("wan_media_isolated", "bot/services/wan3_prime_media.py")

    def test_legacy_fingerprint_and_standard_namespace(self):
        prime = self.media.Wan3PrimeRecipe(scenario="text", prompt="hello")
        legacy = prime.safe_summary()
        legacy.pop("model")
        legacy.pop("prepared_input")
        legacy["provider_args"] = prime.raw_provider_args()
        expected = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(prime.fingerprint(), expected)
        standard = self.media.Wan3PrimeRecipe(scenario="text", prompt="hello", model="wan_3")
        self.assertNotEqual(prime.fingerprint(), standard.fingerprint())
        self.assertEqual(standard.provider_model, "wan/3-0-video")
        self.assertEqual(prime.provider_model, "wan/3-0-video-prime")

    def test_recovery_requires_persisted_model_not_global_prime(self):
        namespace = {"json": json, "secrets": secrets, "parse_qs": parse_qs, "urlparse": urlparse,
                     "wan3_model_spec": self.models.wan3_model_spec}
        tree = ast.parse((ROOT / "bot/services/wan3_prime_recovery.py").read_text())
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in {"_object", "matches_submission"}]
        exec(compile(ast.Module(body=selected, type_ignores=[]), "selected_recovery", "exec"), namespace)  # noqa: S102 - fixed pure source functions
        row = {"provider_model": "wan/3-0-video", "internal_task_id": "wan3_test",
               "callback_nonce": "nonce", "request_summary": {"prepared_input": {"prompt": "test"}}}
        canonical = {"model": "wan/3-0-video", "param": {"model": "wan/3-0-video",
            "callBackUrl": "https://example.test/callback?intent=wan3_test&nonce=nonce",
            "input": {"prompt": "test"}}}
        self.assertTrue(namespace["matches_submission"](row, canonical))
        canonical["model"] = "wan/3-0-video-prime"
        self.assertFalse(namespace["matches_submission"](row, canonical))

    def test_rates_are_model_specific_and_missing_standard_never_uses_prime(self):
        tree = ast.parse((ROOT / "bot/services/wan3_prime_lifecycle.py").read_text())
        lifecycle = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Wan3PrimeLifecycle")
        method = next(node for node in lifecycle.body if isinstance(node, ast.FunctionDef) and node.name == "_rate_snapshot")
        error = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Wan3PrimeLifecycleError")
        ns = {"math": math, "Wan3PrimeRecipe": self.media.Wan3PrimeRecipe, "Wan3PrimeActor": object}
        exec(compile(ast.Module(body=[error, method], type_ignores=[]), "selected_rates", "exec"), ns)  # noqa: S102 - fixed pure methods
        owner = SimpleNamespace(preset_manager=SimpleNamespace(get_video_quality_costs=lambda model: {"720p": 99} if model == "wan_3_prime" else {}))
        recipe = self.media.Wan3PrimeRecipe(scenario="text", prompt="hello", model="wan_3", resolution="720P")
        with self.assertRaises(ns["Wan3PrimeLifecycleError"]) as caught:
            ns["_rate_snapshot"](owner, recipe, SimpleNamespace(is_admin=False))
        self.assertEqual(caught.exception.code, "missing_rate")
        owner.preset_manager.get_video_quality_costs = lambda model: {"720p": 4} if model == "wan_3" else {"720p": 99}
        self.assertEqual(ns["_rate_snapshot"](owner, recipe, SimpleNamespace(is_admin=False))[0], 4)

    def test_telegram_draft_state_and_public_repeat_preserve_standard_model(self):
        tree = ast.parse((ROOT / "bot/handlers/wan3_prime.py").read_text())
        names = {"Wan3PrimeDraft", "draft_to_state", "draft_from_state", "sync_auto_scenario", "build_wan3_payload", "_draft_from_repeat_plan"}
        selected = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
        ns = {"dataclass": dataclass, "field": field, "asdict": asdict, "deepcopy": deepcopy,
              "uuid": uuid, "Any": Any}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "selected_draft", "exec"), ns)  # noqa: S102 - pure draft definitions only
        draft = ns["Wan3PrimeDraft"](model="wan_3", prompt="ordinary", duration=8)
        restored = ns["draft_from_state"](ns["draft_to_state"](draft))
        self.assertEqual(ns["build_wan3_payload"](restored)["model"], "wan_3")
        plan = {"recipe": {"model": "wan_3", "scenario": "text", "duration": 8},
                "repeat_plan_hash": "hash", "slots": [], "source_feed_gen_id": 12}
        repeated = ns["_draft_from_repeat_plan"](plan)
        self.assertEqual(ns["build_wan3_payload"](repeated)["model"], "wan_3")

    def test_model_registry_is_closed_and_immutable(self):
        for value in ("wan3", "wan_3", "wan/3-0-video"):
            self.assertEqual(self.models.wan3_model_spec(value).key, "wan_3")
        self.assertEqual(self.models.wan3_model_spec().key, "wan_3_prime")
        with self.assertRaises(ValueError):
            self.models.wan3_model_spec("other")
        with self.assertRaises(TypeError):
            self.models.WAN3_MODELS["other"] = object()


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = adapter_classes()
        self.standard = self.ns["Wan3StandardService"]()
        self.prime = self.ns["Wan3PrimeService"]()

    async def test_all_modes_preserve_identical_input_but_distinct_model(self):
        cases = [
            {"prompt": "text", "scenario": "text"},
            {"prompt": "first", "scenario": "first_frame", "first_frame_url": "https://example.test/first.png"},
            {"prompt": "both", "scenario": "first_last", "first_frame_url": "https://example.test/first.png",
                 "last_frame_url": "https://example.test/last.png"},
            {"prompt": "Image1 Video1 Audio1", "scenario": "reference",
                 "reference_image_urls": ["https://example.test/image.png"],
                 "reference_video_urls": ["https://example.test/video.mp4"],
                 "reference_audio_urls": ["https://example.test/audio.mp3"]},
            {"prompt": "file", "scenario": "file", "reference_file_urls": ["https://example.test/file.pdf"]},
            {"prompt": "link", "scenario": "link", "reference_link_urls": ["https://example.test/page"]},
            {"prompt": "Change colors", "scenario": "edit", "reference_video_urls": ["https://example.test/source.mp4"]},
        ]
        fields = set()
        for case in cases:
            payload = dict(case, resolution="720P", aspect_ratio="adaptive", duration=5,
                           audio=True, nsfw_checker=False, seed=0)
            expected = await self.prime.prepare_request(**payload)
            actual = await self.standard.prepare_request(**payload)
            self.assertEqual(actual, expected)
            fields.update(actual)
            self.standard._kie_post = AsyncMock(return_value={"task_id": "synthetic"})
            await self.standard.submit_prepared(actual, callback_url="https://example.test/callback")
            sent = self.standard._kie_post.call_args.args[1]
            self.assertEqual(sent["model"], "wan/3-0-video")
            self.assertEqual(sent["input"], expected)
        self.assertEqual(fields, {
            "prompt", "first_frame_url", "last_frame_url", "reference_image_urls",
            "reference_video_urls", "reference_audio_urls", "reference_file_urls",
            "reference_link_urls", "resolution", "aspect_ratio", "duration", "audio",
            "seed", "nsfw_checker",
        })
        self.assertEqual(self.prime.MODEL_NAME, "wan/3-0-video-prime")
        self.assertNotEqual(self.prime.INTERNAL_MODEL_KEY, self.standard.INTERNAL_MODEL_KEY)

    async def test_provider_boundaries_and_prompt_validation_are_inherited(self):
        for duration in [2, 30, -1]:
            result = await self.standard.prepare_request(prompt="hello", duration=duration)
            self.assertEqual(result["duration"], duration)
        for duration in [0, 1, 31, True, 5.1]:
            with self.assertRaises(ValueError):
                await self.standard.prepare_request(prompt="hello", duration=duration)
        with self.assertRaises(ValueError):
            await self.standard.prepare_request(prompt="hello", reference_video_urls=["url"]*6)


if __name__ == "__main__":
    unittest.main()
