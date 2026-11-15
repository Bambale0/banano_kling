"""Regression tests for Mini App recent-task timing instrumentation."""
from unittest.mock import AsyncMock, Mock

import pytest

from bot import miniapp


@pytest.mark.asyncio
async def test_recent_tasks_empty_history_preserves_response_and_has_no_slow_warning(
    monkeypatch, caplog
):
    """An empty owned history stays empty without leaking account identifiers."""
    cursor = Mock()
    cursor.fetchall = AsyncMock(return_value=[])

    class ReadOnlyConnection:
        row_factory = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args):
            return cursor

    monkeypatch.setattr(miniapp.db_backend, "connect", lambda *_: ReadOnlyConnection())
    with caplog.at_level("WARNING", logger="bot.miniapp"):
        rows = await miniapp._fetch_recent_tasks(8675309)

    assert rows == []
    assert not any("Mini App recent_tasks slow" in record.getMessage() for record in caplog.records)
