"""Stable unit tests for database helpers."""

from unittest.mock import AsyncMock

import pytest

import bot.database as database


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
