from pathlib import Path

import pytest

from bot import trend_task_privacy


@pytest.mark.asyncio
async def test_task_detail_redacts_protected_trend_prompt(monkeypatch) -> None:
    async def fake_protected(task_ids: list[str]) -> set[str]:
        assert task_ids == ["trend-task-1"]
        return {"trend-task-1"}

    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", fake_protected)
    payload = {
        "ok": True,
        "task": {
            "task_id": "trend-task-1",
            "prompt": "SECRET TREND PROMPT",
            "prompt_preview": "SECRET TREND PROMPT",
            "prompt_hidden": False,
            "prompt_actions_allowed": True,
            "feed_prompt_visible": True,
        },
    }

    sanitized = await trend_task_privacy.sanitize_task_api_payload(payload)
    task = sanitized["task"]
    assert task["prompt"] == ""
    assert task["prompt_preview"] == ""
    assert task["prompt_hidden"] is True
    assert task["prompt_actions_allowed"] is False
    assert task["feed_prompt_visible"] is False


@pytest.mark.asyncio
async def test_recent_tasks_only_redacts_protected_entries(monkeypatch) -> None:
    async def fake_protected(task_ids: list[str]) -> set[str]:
        assert task_ids == ["normal", "trend"]
        return {"trend"}

    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", fake_protected)
    payload = {
        "recent_tasks": [
            {"task_id": "normal", "prompt_preview": "visible"},
            {"task_id": "trend", "prompt_preview": "secret"},
        ]
    }
    sanitized = await trend_task_privacy.sanitize_task_api_payload(payload)
    assert sanitized["recent_tasks"][0]["prompt_preview"] == "visible"
    assert sanitized["recent_tasks"][1]["prompt_preview"] == ""
    assert sanitized["recent_tasks"][1]["prompt_hidden"] is True


def test_shared_prompt_detail_is_sanitized_even_for_admin_contract() -> None:
    source = Path("bot/browser_auth.py").read_text(encoding="utf-8")
    assert 'request.path == f"{prompt_api_root}/detail"' in source
    assert 'start_param.startswith("prompt_")' in source
    assert "if not viewer_is_admin or shared_prompt_detail:" in source
    assert "payload = await sanitize_task_api_payload(payload)" in source
    assert 'task_detail_path = f"{miniapp_root}/api/task-detail"' in source
    assert 'bootstrap_path = f"{miniapp_root}/api/bootstrap"' in source
