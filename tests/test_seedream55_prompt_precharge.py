"""Seedream 5.5 prompt length is validated before user credit deduction."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "bot/handlers/generation.py").read_text(
    encoding="utf-8"
)
TREE = ast.parse(SOURCE)
VALIDATOR = next(
    x for x in TREE.body if isinstance(x, ast.FunctionDef)
    and x.name == "_image_prompt_precharge_error"
)
namespace = {}
exec(  # noqa: S102 - static AST-extracted pure function owned by the repo
    compile(ast.Module(body=[VALIDATOR], type_ignores=[]), "generation.py", "exec"),
    namespace,
)
validate = namespace["_image_prompt_precharge_error"]


class Seedream55PromptPrechargeTests(unittest.TestCase):
    def test_boundary_lengths(self):
        for length in (5, 5000):
            self.assertIsNone(validate("seedream_55", "т" * length))
        for length in (0, 1, 4, 5001):
            message = validate("seedream_55", "т" * length)
            self.assertIn("от 5 до 5000", message)
            self.assertIn("не списаны", message)

    def test_trimmed_length_not_raw_length(self):
        self.assertIsNotNone(validate("seedream_55", "    x   "))
        self.assertIsNone(validate("seedream_55", "   12345   "))

    def test_other_models_keep_existing_validation_including_layers_auto(self):
        for model in ("nanobanana", "seedream_55_layers", "seedream_edit"):
            self.assertIsNone(validate(model, ""))
            self.assertIsNone(validate(model, "x"))

    def test_handler_checks_before_database_and_debit(self):
        handler = next(
            x for x in TREE.body if isinstance(x, ast.AsyncFunctionDef)
            and x.name == "handle_image_prompt_text"
        )
        body = ast.get_source_segment(SOURCE, handler)
        self.assertIn("precharge_error = _image_prompt_precharge_error(", body)
        self.assertLess(
            body.index("precharge_error = _image_prompt_precharge_error("),
            body.index("user = await get_or_create_user("),
        )
        self.assertLess(
            body.index("if precharge_error:"),
            body.index("await deduct_credits("),
        )


if __name__ == "__main__":
    unittest.main()
