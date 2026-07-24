from __future__ import annotations

import asyncio

import pytest

from bot.services import lava_binding_schema_compat as compat
from bot.services import lava_payment_safety as safety


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeConnection:
    def __init__(self, events, *, fail_index: bool = False):
        self.events = events
        self.fail_index = fail_index

    async def execute(self, sql: str, parameters=None):
        normalized = " ".join(sql.split())
        self.events.append(("execute", normalized))
        if self.fail_index and normalized.startswith("CREATE UNIQUE INDEX"):
            raise compat.db_backend.OperationalError("concurrent index creation")

    async def commit(self):
        self.events.append(("commit", None))


@pytest.mark.asyncio
async def test_table_commit_survives_optional_index_failure(monkeypatch):
    events = []
    connections = iter(
        [
            _FakeConnection(events),
            _FakeConnection(events, fail_index=True),
        ]
    )

    monkeypatch.setattr(
        compat.db_backend,
        "connect",
        lambda: _ConnectionContext(next(connections)),
    )
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_READY", False)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_LOCK", asyncio.Lock())

    await compat._ensure_bindings_table_postgres_safe()

    assert events[0][0] == "execute"
    assert f"CREATE TABLE IF NOT EXISTS {safety._BINDINGS_TABLE}" in events[0][1]
    assert events[1] == ("commit", None)
    assert events[2][0] == "execute"
    assert events[2][1].startswith("CREATE UNIQUE INDEX IF NOT EXISTS")
    assert compat._BINDINGS_SCHEMA_READY is True


@pytest.mark.asyncio
async def test_schema_initializer_runs_only_once(monkeypatch):
    events = []
    connections = iter([_FakeConnection(events), _FakeConnection(events)])

    monkeypatch.setattr(
        compat.db_backend,
        "connect",
        lambda: _ConnectionContext(next(connections)),
    )
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_READY", False)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_LOCK", asyncio.Lock())

    await compat._ensure_bindings_table_postgres_safe()
    first_run_events = list(events)
    await compat._ensure_bindings_table_postgres_safe()

    assert events == first_run_events


def test_install_replaces_safety_initializer(monkeypatch):
    original = safety._ensure_bindings_table
    monkeypatch.delattr(safety, compat._INSTALL_MARKER, raising=False)

    compat.install_lava_binding_schema_compat()

    assert safety._ensure_bindings_table is compat._ensure_bindings_table_postgres_safe

    safety._ensure_bindings_table = original
    monkeypatch.delattr(safety, compat._INSTALL_MARKER, raising=False)
