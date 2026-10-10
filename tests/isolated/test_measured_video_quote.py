"""AST-selected tariff tests; no bot bootstrap or database imports."""
import ast
import hashlib
import json
import math
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

source = Path(__file__).parents[2] / "bot/creator_tariff.py"
parsed = ast.parse(source.read_text())
selected = ast.Module(body=[node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {"VideoQuote", "_measured_video_quote"}], type_ignores=[])
namespace = {"dataclass": dataclass, "asdict": asdict, "Any": Any, "math": math, "hashlib": hashlib, "json": json,
                 "CREATOR_MODELS": ("seedance_2", "seedance_2_5"),
                 "creator_tariff_status": lambda: {"enabled": True, "configured": True},
                 "video_quality_rates": lambda model, tariff: {"720p": 2 if tariff == "creator" else 4},
                 "preset_manager": SimpleNamespace(_format_cost=lambda value: round(value * 2) / 2)}
# Only the explicitly selected trusted repository definitions are executed.
exec(compile(selected, str(source), "exec"), namespace)  # noqa: S102
quote = namespace["_measured_video_quote"]


class QuoteTests(unittest.TestCase):
    def make(self, **changes):
        values = {"model": "seedance_2_5", "duration": 5, "quality": "720p", "tariff": "standard",
                      "input_seconds": 7, "selected_output_seconds": None, "references_fingerprint": "a" * 64}
        values.update(changes)
        return quote(**values)

    def test_sum_once_and_frozen_snapshot(self):
        result = self.make()
        self.assertEqual((result.cost, result.charge_cost, result.billable_seconds), (48, 48, 12))
        self.assertEqual((result.version, result.reference_multiplier), (2, 1))
        self.assertEqual(result.to_dict()["selected_output_seconds"], 5)
        with self.assertRaises(AttributeError):
            result.cost = 100

    def test_actor_rates_and_admin_zero(self):
        self.assertEqual(self.make(tariff="creator").cost, 24)
        self.assertEqual(self.make(tariff="admin").charge_cost, 0)
        self.assertEqual(self.make(tariff="admin").cost, 48)

    def test_fractional_source_and_source_locked_output(self):
        result = self.make(input_seconds=7.25, duration=-1, selected_output_seconds=7.25)
        self.assertEqual(result.cost, 58)
        self.assertEqual(result.selected_output_seconds, 7.25)

    def test_invalid_duration_never_default_five(self):
        for changes in ({"duration": -1}, {"input_seconds": float("nan")},
                        {"input_seconds": -1}, {"input_seconds": True},
                        {"references_fingerprint": None}, {"selected_output_seconds": 0}):
            with self.assertRaises(ValueError):
                self.make(**changes)

    def test_legacy_serialization_unchanged(self):
        result = namespace["VideoQuote"]("seedance_2", 5, "720p", 40, 40, "standard", 20, 2, "old")
        self.assertNotIn("input_seconds", result.to_dict())
        self.assertEqual(result.to_dict()["version"], 1)


if __name__ == "__main__":
    unittest.main()
