from __future__ import annotations


def test_lava_reconcile_summary_counts_terminal_and_error_actions():
    results = [
        {"action": "completed"},
        {"action": "already_completed"},
        {"action": "failed"},
        {"action": "still_pending"},
        {"action": "error"},
    ]

    summary = {
        "checked": len(results),
        "completed": sum(item.get("action") == "completed" for item in results),
        "already_completed": sum(
            item.get("action") == "already_completed" for item in results
        ),
        "failed": sum(item.get("action") == "failed" for item in results),
        "pending": sum(item.get("action") == "still_pending" for item in results),
        "errors": sum(item.get("action") == "error" for item in results),
    }

    assert summary == {
        "checked": 5,
        "completed": 1,
        "already_completed": 1,
        "failed": 1,
        "pending": 1,
        "errors": 1,
    }
