"""Stable unit tests for database helpers."""

import json
from unittest.mock import AsyncMock

import pytest

import bot.database as database
from bot.services.preset_manager import PresetManager


class FakeConnection:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_complete_video_task_marks_completed_with_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.aiosqlite, "connect", lambda *_args, **_kwargs: conn)

    result = await database.complete_video_task("task-ok", "http://result.url")

    assert result is True
    conn.execute.assert_awaited_once()
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("completed", "http://result.url", "task-ok")
    conn.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_video_task_marks_failed_without_result_url(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(database.aiosqlite, "connect", lambda *_args, **_kwargs: conn)

    result = await database.complete_video_task("task-fail", None)

    assert result is True
    sql, params = conn.execute.await_args.args
    assert "UPDATE generation_tasks" in sql
    assert params == ("failed", None, "task-fail")
    conn.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_master_partner_user_uses_master_telegram_id(monkeypatch):
    expected_user = object()
    get_or_create_user = AsyncMock(return_value=expected_user)
    monkeypatch.setattr(database, "get_or_create_user", get_or_create_user)

    user = await database.get_master_partner_user()

    assert user is expected_user
    get_or_create_user.assert_awaited_once_with(database.MASTER_PARTNER_TELEGRAM_ID)


def test_video_quality_costs_scale_with_selected_resolution(tmp_path):
    price_path = tmp_path / "price.json"
    price_path.write_text(
        json.dumps(
            {
                "packages": [],
                "costs_reference": {
                    "image_models": {},
                    "video_models": {
                        "veo3_fast": {
                            "base": 15,
                            "quality_costs": {
                                "720p": 2.5,
                                "1080p": 3.5,
                                "4k": 5,
                            },
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manager = PresetManager(
        presets_path=str(tmp_path / "missing_presets.json"),
        price_path=str(price_path),
    )

    assert manager.get_video_cost_with_quality("veo3_fast", 6, "720p") == 15
    assert manager.get_video_cost_with_quality("veo3_fast", 6, "1080p") == 21
    assert manager.get_video_cost_with_quality("veo3_fast", 6, "4k") == 30
