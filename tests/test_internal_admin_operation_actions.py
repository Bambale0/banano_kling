from typing import Any

import pytest

from bot.internal_admin_operation_actions import _provider_accepted
from bot.internal_admin_operation_replay import (
    _annotate_replay_child,
    _provider_task_id,
)
from bot.internal_admin_user_commands import CommandConflictError


class FakeCursor:
    async def fetchone(self):
        return {"request_data": '{"prompt":"portrait"}'}


class FakeConnection:
    def __init__(self) -> None:
        self.row_factory = None
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, parameters: tuple[Any, ...] = ()):
        self.calls.append((sql, tuple(parameters)))
        return FakeCursor()

    async def commit(self) -> None:
        self.committed = True


def test_provider_acceptance_requires_task_and_non_failed_status() -> None:
    assert _provider_accepted({"task_id": "child-task", "status": "pending"})
    assert _provider_accepted({"task_id": "child-task", "status": "completed"})
    assert not _provider_accepted({"task_id": "", "status": "pending"})
    assert not _provider_accepted({"task_id": "child-task", "status": "failed"})
    assert not _provider_accepted({"task_id": "child-task", "status": "rejected"})
    assert not _provider_accepted(None)


def test_provider_task_id_rejects_structured_provider_error() -> None:
    with pytest.raises(CommandConflictError, match="provider rejected replay"):
        _provider_task_id(
            {"error": "rate_limit", "message": "provider rejected replay"},
            provider="Kling",
        )


@pytest.mark.asyncio
async def test_replay_metadata_is_written_as_text_without_jsonb_cast(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        "bot.internal_admin_operation_replay.db_backend.connect",
        lambda: connection,
    )

    await _annotate_replay_child(
        8,
        source_operation_id=7,
        admin_user_id="admin-user",
        request_id="request-123",
        idempotency_key="idempotency-123",
        reason="retry after outage",
        comment=None,
    )

    update_sql, parameters = next(
        (sql, params)
        for sql, params in connection.calls
        if "UPDATE generation_tasks" in sql
    )
    assert "CAST" not in update_sql.upper()
    assert '"admin_replay"' in parameters[1]
    assert connection.committed is True
