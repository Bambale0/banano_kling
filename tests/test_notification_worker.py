from unittest.mock import AsyncMock

import pytest

from bot import notification_service


@pytest.mark.asyncio
async def test_worker_recovers_expired_delivery_leases(monkeypatch) -> None:
    class Cursor:
        rowcount = 3

    class Connection:
        execute = AsyncMock(return_value=Cursor())
        commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    connection = Connection()
    monkeypatch.setattr(notification_service.db_backend, "connect", lambda: connection)

    recovered = await notification_service._recover_expired_leases()

    assert recovered == 3
    sql = connection.execute.await_args.args[0]
    assert "status = 'sending'" in sql
    assert "lease_until < CURRENT_TIMESTAMP" in sql


@pytest.mark.asyncio
async def test_terminal_failure_is_marked_dead_letter(monkeypatch) -> None:
    class Connection:
        execute = AsyncMock()
        commit = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    connection = Connection()
    monkeypatch.setattr(notification_service.db_backend, "connect", lambda: connection)

    await notification_service._mark_failed(
        delivery_id=11,
        attempts=notification_service.MAX_ATTEMPTS,
        error=RuntimeError("provider unavailable"),
    )

    params = connection.execute.await_args.args[1]
    assert params[0] == "failed"
    assert "[dead-letter]" in params[2]
