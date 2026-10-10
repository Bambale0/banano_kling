"""Operational admission checks, isolated from application and production state."""
import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("launch_gate", ROOT / "bot/services/seedance_launch_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class LaunchGateTests(unittest.TestCase):
    def test_marker_and_broken_symlink_pause_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pause"
            self.assertTrue(gate.launches_allowed(marker))
            marker.touch()
            self.assertFalse(gate.launches_allowed(marker))
            marker.unlink()
            marker.symlink_to(Path(directory) / "missing")
            self.assertFalse(gate.launches_allowed(marker))

    def test_permission_error_fails_closed(self):
        marker = Mock()
        marker.lstat.side_effect = PermissionError()
        self.assertFalse(gate.launches_allowed(marker))

    def test_common_store_wires_gate_and_preview_checks_before_acquisition(self):
        tree = ast.parse((ROOT / "bot/services/seedance_quote_lifecycle.py").read_text())
        store = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "receipt_store")
        constructor = next(node for node in ast.walk(store) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SeedanceQuoteReceipts")
        self.assertTrue(any(kw.arg == "allow_new_claim" and isinstance(kw.value, ast.Name) and kw.value.id == "launches_allowed" for kw in constructor.keywords))
        prepare = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "prepare_quote")
        gate_line = min(node.lineno for node in ast.walk(prepare) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "launches_allowed")
        copy_line = min(node.lineno for node in ast.walk(prepare) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "prepare_video_snapshots")
        self.assertLess(gate_line, copy_line)


if __name__ == "__main__":
    unittest.main()
