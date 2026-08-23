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
            "source_url": "https://pinterest.com/pin/secret",
            "pinterest_url": "https://pin.it/secret",
            "request_data": {
                "prompt": "SECRET TREND PROMPT",
                "effective_prompt": "SECRET PROVIDER PROMPT",
                "source_url": "https://pinterest.com/pin/secret",
                "pinterest_url": "https://pin.it/secret",
                "reference_images": ["https://example.com/scene.jpg"],
                "source_reference_images": ["https://example.com/user.jpg"],
                "provider_model": "nano-banana-pro",
            },
        },
    }

    sanitized = await trend_task_privacy.sanitize_task_api_payload(payload)
    task = sanitized["task"]
    assert task["prompt"] == ""
    assert task["prompt_preview"] == ""
    assert task["prompt_hidden"] is True
    assert task["prompt_actions_allowed"] is False
    assert task["feed_prompt_visible"] is False
    assert "source_url" not in task
    assert "pinterest_url" not in task
    assert "prompt" not in task["request_data"]
    assert "effective_prompt" not in task["request_data"]
    assert "source_url" not in task["request_data"]
    assert "pinterest_url" not in task["request_data"]
    assert "reference_images" not in task["request_data"]
    assert "source_reference_images" not in task["request_data"]
    assert task["request_data"]["provider_model"] == "nano-banana-pro"
    assert task["request_data"]["prompt_hidden"] is True
    assert task["request_data"]["prompt_actions_allowed"] is False


@pytest.mark.asyncio
async def test_recent_tasks_only_redacts_protected_entries(monkeypatch) -> None:
    async def fake_protected(task_ids: list[str]) -> set[str]:
        assert task_ids == ["normal", "trend"]
        return {"trend"}

    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", fake_protected)
    payload = {
        "recent_tasks": [
            {
                "task_id": "normal",
                "prompt_preview": "visible",
                "request_data": {"reference_images": ["https://example.com/normal.jpg"]},
            },
            {
                "task_id": "trend",
                "prompt_preview": "secret",
                "request_data": {"reference_images": ["https://example.com/secret.jpg"]},
            },
        ]
    }
    sanitized = await trend_task_privacy.sanitize_task_api_payload(payload)
    assert sanitized["recent_tasks"][0]["prompt_preview"] == "visible"
    assert sanitized["recent_tasks"][0]["request_data"]["reference_images"] == [
        "https://example.com/normal.jpg"
    ]
    assert sanitized["recent_tasks"][1]["prompt_preview"] == ""
    assert sanitized["recent_tasks"][1]["prompt_hidden"] is True
    assert "reference_images" not in sanitized["recent_tasks"][1]["request_data"]


@pytest.mark.asyncio
async def test_privacy_lookup_failure_redacts_every_task_and_reference_link(monkeypatch) -> None:
    async def broken_lookup(task_ids: list[str]) -> set[str]:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(trend_task_privacy, "_protected_task_ids", broken_lookup)
    payload = {
        "task": {
            "task_id": "unknown-task",
            "prompt": "possibly secret",
            "request_data": {
                "reference_images": ["https://example.com/private.jpg"],
                "provider_model": "nano-banana-pro",
            },
        }
    }

    sanitized = await trend_task_privacy.sanitize_task_api_payload(payload)
    task = sanitized["task"]
    assert task["prompt"] == ""
    assert task["prompt_hidden"] is True
    assert "reference_images" not in task["request_data"]
    assert task["request_data"]["provider_model"] == "nano-banana-pro"


def test_shared_prompt_detail_is_sanitized_even_for_admin_contract() -> None:
    source = Path("bot/browser_auth.py").read_text(encoding="utf-8")
    assert 'request.path == f"{prompt_api_root}/detail"' in source
    assert 'start_param.startswith("prompt_")' in source
    assert "if not viewer_is_admin or shared_prompt_detail:" in source
    assert "payload = await sanitize_task_api_payload(payload)" in source
    assert 'task_detail_path = f"{miniapp_root}/api/task-detail"' in source
    assert 'bootstrap_path = f"{miniapp_root}/api/bootstrap"' in source
