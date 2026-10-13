"""Synthetic slot metadata only; no application/database imports."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LegacySelectionDescriptorTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("legacy_slots", ROOT / "bot/legacy_video_repeat_slots.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.build = module.legacy_selection_plan
        self.recipe = {
            "model": "seedance_2_5", "scenario": "multimodal",
            "images": [{"index": i, "kind": "images", "role": "reference", "url": f"source-{i}"}
                       for i in range(4)], "videos": [], "audio": [],
        }

    @staticmethod
    def resolve(value, candidates):
        value = value.removeprefix("alias:")
        return value if value in candidates else None

    def test_exact_reported_shape_requires_two_uploads_before_two_retained_slots(self):
        plan = self.build(self.recipe, {"images": ["alias:source-2", "alias:source-3"], "videos": []},
                          resolve=self.resolve)
        self.assertEqual([slot["binding"] for slot in plan["images"]], ["upload", "upload", "fixed", "fixed"])
        self.assertEqual([slot["index"] for slot in plan["images"]], [0, 1, 2, 3])
        self.assertEqual([slot["url"] for slot in plan["images"][2:]], ["source-2", "source-3"])
        self.assertNotIn("binding", self.recipe["images"][0])

    def test_selected_source_missing_fails_closed(self):
        with self.assertRaises(ValueError):
            self.build(self.recipe, {"images": ["unknown"], "videos": []}, resolve=self.resolve)

    def test_empty_selection_keeps_existing_free_upload_contract(self):
        self.assertIsNone(self.build(self.recipe, {"images": [], "videos": []}, resolve=self.resolve))

    def test_optional_trailing_slots_do_not_become_required(self):
        self.assertIsNone(self.build(self.recipe, {"images": ["source-2"], "videos": []}, resolve=self.resolve))

    def test_frame_recipe_is_not_promoted(self):
        self.recipe["scenario"] = "first_last"
        self.assertIsNone(self.build(self.recipe, {"images": ["source-3"], "videos": []}, resolve=self.resolve))

    def test_other_model_is_not_promoted(self):
        self.recipe["model"] = "seedance_2"
        self.assertIsNone(self.build(self.recipe, {"images": ["source-3"], "videos": []}, resolve=self.resolve))


if __name__ == "__main__":
    unittest.main()
