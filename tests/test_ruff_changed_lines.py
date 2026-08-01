from pathlib import Path

from scripts.ruff_changed_lines import (
    LineRange,
    diagnostic_ranges,
    diagnostic_touches_changes,
    filter_diagnostics,
    parse_added_ranges,
)


def test_parse_added_ranges_handles_modifications_new_files_and_deletions():
    diff = """
@@ -10,2 +10,3 @@
-old
+new
+extra
@@ -30,4 +31,0 @@
-deleted
@@ -0,0 +1,2 @@
+first
+second
"""

    assert parse_added_ranges(diff) == (
        LineRange(10, 12),
        LineRange(1, 2),
    )


def test_diagnostic_on_legacy_line_is_ignored():
    diagnostic = {
        "filename": "bot/miniapp.py",
        "location": {"row": 20, "column": 1},
        "end_location": {"row": 20, "column": 5},
        "code": "F401",
        "message": "unused import",
        "fix": None,
    }

    assert not diagnostic_touches_changes(
        diagnostic,
        (LineRange(300, 305),),
    )


def test_diagnostic_on_changed_line_is_relevant():
    diagnostic = {
        "filename": "bot/miniapp.py",
        "location": {"row": 302, "column": 1},
        "end_location": {"row": 302, "column": 5},
        "code": "F841",
        "message": "unused variable",
        "fix": None,
    }

    assert diagnostic_touches_changes(
        diagnostic,
        (LineRange(300, 305),),
    )


def test_file_level_diagnostic_is_relevant_when_fix_edits_changed_block():
    diagnostic = {
        "filename": "bot/miniapp.py",
        "location": {"row": 1, "column": 1},
        "end_location": {"row": 1, "column": 1},
        "code": "I001",
        "message": "imports are unsorted",
        "fix": {
            "edits": [
                {
                    "location": {"row": 1, "column": 1},
                    "end_location": {"row": 18, "column": 1},
                    "content": "sorted imports",
                }
            ]
        },
    }

    assert diagnostic_ranges(diagnostic) == (
        LineRange(1, 1),
        LineRange(1, 18),
    )
    assert diagnostic_touches_changes(
        diagnostic,
        (LineRange(12, 12),),
    )


def test_filter_diagnostics_normalizes_absolute_paths(tmp_path: Path):
    target = tmp_path / "bot" / "miniapp.py"
    target.parent.mkdir(parents=True)
    target.write_text("pass\n", encoding="utf-8")

    diagnostics = [
        {
            "filename": str(target),
            "location": {"row": 1, "column": 1},
            "end_location": {"row": 1, "column": 2},
            "code": "F401",
            "message": "example",
            "fix": None,
        }
    ]

    assert filter_diagnostics(
        diagnostics,
        repository=tmp_path,
        ranges_by_file={"bot/miniapp.py": (LineRange(1, 1),)},
    ) == diagnostics
