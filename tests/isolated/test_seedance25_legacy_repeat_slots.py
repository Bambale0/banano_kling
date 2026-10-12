"""Pure AST regressions: no app/database imports or production media."""
import ast
import json
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_functions():
    namespace = {"Any": Any, "Iterable": Iterable, "json": json,
                 # Exact synthetic URLs; canonical local aliases are covered by CI.
                 "resolve_reference_source": lambda value, values: value if value in values else None}
    contract = ast.parse((ROOT / "bot/video_repeat_reference_contract.py").read_text())
    nodes = [n for n in contract.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in {"parse_video_repeat_grant", "VideoRepeatContractError"}]
    # Fixed pure definitions only; application imports are intentionally excluded.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "grant", "exec"), namespace)  # noqa: S102
    tree = ast.parse((ROOT / "bot/handlers/miniapp_video_continuity_compat.py").read_text())
    names = {"_clean_list", "_missing", "_first_list", "_first_value", "_source_request_data",
             "_publication_repeat_selection", "_video_repeat_selection",
             "_validate_selected_reference_candidates", "_enrich_legacy_video_repeat_body",
             "_infer_scenario", "_resolve_repeat_source", "VideoRepeatReferenceError"}
    constants = {"_REPEAT_LIST_ALIASES", "_REPEAT_SCALAR_ALIASES", "_ADVANCED_VIDEO_KEYS"}
    nodes = [n for n in tree.body if
             (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
             or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                 and n.target.id in constants)
             or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                 and t.id in constants for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "repeat", "exec"), namespace)  # noqa: S102
    return namespace


class LegacyRepeatSlotsTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_functions()
        self.face = "https://example.test/author-face.png"
        self.fixed = "https://example.test/author-style.png"
        self.viewer = "https://example.test/viewer.png"
        self.source = {
            "model": "seedance_2_5", "prompt": "Synthetic @Image1 with @Image2",
            "feed_references_visible": False, "feed_reference_selection": None,
            "request_data": {"seedance25_scenario": "multimodal", "v_type": "video",
                             "reference_images": [self.face, self.fixed]},
        }
        self.body = {"v_model": "seedance_2_5", "v_type": "imgtxt",
                     "reference_images": [self.viewer]}

    def restore(self):
        return self.ns["_enrich_legacy_video_repeat_body"](self.body, self.source)

    def test_one_photo_replaces_only_first_slot_and_retains_hidden_tail(self):
        result = self.restore()
        self.assertEqual(result["reference_images"], [self.viewer, self.fixed])
        self.assertEqual(result["_private_repeat_reference_images"], [self.fixed])
        self.assertEqual(result["prompt"], self.source["prompt"])
        self.assertEqual(self.source["request_data"]["reference_images"], [self.face, self.fixed])

    def test_extra_viewer_photos_cannot_replace_hidden_slots_without_grant(self):
        self.body["reference_images"].append("https://example.test/extra.png")
        with self.assertRaises(self.ns["VideoRepeatReferenceError"]):
            self.restore()

    def test_viewer_cannot_collapse_a_retained_slot(self):
        self.body["reference_images"] = [self.fixed]
        with self.assertRaises(self.ns["VideoRepeatReferenceError"]):
            self.restore()

    def test_client_cannot_claim_owner_or_inject_private_provenance(self):
        self.body["_repeat_is_owner"] = True
        self.body["_private_repeat_reference_images"] = ["https://example.test/foreign.png"]
        result = self.restore()
        self.assertEqual(result["reference_images"], [self.viewer, self.fixed])
        self.assertEqual(result["_private_repeat_reference_images"], [self.fixed])

    def test_editing_recipe_keeps_its_existing_contract(self):
        self.source["request_data"]["seedance25_video_editing"] = True
        self.assertEqual(self.restore()["reference_images"], [self.viewer])

    def test_explicit_identity_keeps_its_existing_contract(self):
        self.body["seedance25_identity_transfer"] = True
        self.assertEqual(self.restore()["reference_images"], [self.viewer])

    def test_visible_legacy_repeat_accepts_all_displayed_images(self):
        self.source["feed_references_visible"] = True
        self.body["reference_images"] = [self.face, self.fixed]
        self.assertEqual(self.restore()["reference_images"], [self.face, self.fixed])

    def test_visible_legacy_repeat_keeps_existing_multi_photo_edit(self):
        self.source["feed_references_visible"] = True
        self.body["reference_images"] = [self.viewer, "https://example.test/new-style.png"]
        self.assertEqual(self.restore()["reference_images"], self.body["reference_images"])

    def test_exact_repeat_keeps_all_source_slots(self):
        self.body["reference_images"] = []
        result = self.restore()
        self.assertEqual(result["reference_images"], [self.face, self.fixed])

    def test_owner_keeps_existing_full_edit_authority(self):
        self.source["_repeat_is_owner"] = True
        result = self.restore()
        self.assertEqual(result["reference_images"], [self.viewer])

    def test_other_model_is_unchanged(self):
        self.source["model"] = self.body["v_model"] = "seedance_2"
        result = self.restore()
        self.assertEqual(result["reference_images"], [self.face, self.fixed])

    def test_legacy_alias_keeps_order(self):
        self.source["request_data"]["reference_image_urls"] = self.source["request_data"].pop("reference_images")
        self.assertEqual(self.restore()["reference_images"], [self.viewer, self.fixed])


if __name__ == "__main__":
    unittest.main()
