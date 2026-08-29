from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bot.handlers import trend_success_compat


def test_public_trend_counter_is_separate_from_accepted_uses_count() -> None:
    prompt = {
        "id": 42,
        "tags": ["trend"],
        "description": "Портрет по вашему фото",
        "uses_count": 99,
    }
    enriched = trend_success_compat._public_counter_description(prompt, 7)

    assert enriched["successful_runs_count"] == 7
    assert enriched["uses_count"] == 99
    assert enriched["description"].startswith("✅ Успешных запусков: 7")
    assert prompt["description"] == "Портрет по вашему фото"


@pytest.mark.asyncio
async def test_successful_launch_links_exact_task_to_trend(monkeypatch) -> None:
    recorded: list[dict] = []

    async def fake_register(**kwargs):
        recorded.append(kwargs)
        return True

    monkeypatch.setattr(
        trend_success_compat,
        "register_trend_generation_run",
        fake_register,
    )
    response = SimpleNamespace(
        body=json.dumps({"ok": True, "task_id": "provider_task_123"}).encode()
    )

    await trend_success_compat._record_response_task(
        response,
        SimpleNamespace(trend_id=55),
        SimpleNamespace(id=77),
    )

    assert recorded == [
        {"task_id": "provider_task_123", "trend_id": 55, "user_id": 77}
    ]


@pytest.mark.asyncio
async def test_failed_launch_does_not_register_success_candidate(monkeypatch) -> None:
    called = False

    async def fake_register(**_kwargs):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(
        trend_success_compat,
        "register_trend_generation_run",
        fake_register,
    )
    response = SimpleNamespace(
        body=json.dumps({"ok": False, "task_id": "failed_task"}).encode()
    )

    await trend_success_compat._record_response_task(
        response,
        SimpleNamespace(trend_id=55),
        SimpleNamespace(id=77),
    )

    assert called is False


def test_success_count_query_uses_completed_generation_rows() -> None:
    source = open("bot/handlers/trend_success_compat.py", encoding="utf-8").read()
    assert "task_id TEXT PRIMARY KEY" in source
    assert "JOIN generation_tasks g ON g.task_id = r.task_id" in source
    assert "g.status = 'completed'" in source
