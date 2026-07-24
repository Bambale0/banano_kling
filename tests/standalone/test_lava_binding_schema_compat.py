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


class _CursorContext:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, sql: str):
        self.events.append(("raw_execute", " ".join(sql.split())))


class _RawConnection:
    def __init__(self, events):
        self.events = events

    def cursor(self):
        return _CursorContext(self.events)

    async def commit(self):
        self.events.append(("raw_commit", None))

    async def rollback(self):
        self.events.append(("raw_rollback", None))


class _WrappedPostgresConnection:
    def __init__(self, events):
        self._conn = _RawConnection(events)

    async def execute(self, sql: str, parameters=None):
        raise AssertionError("DDL must bypass PostgresConnection.execute()")


@pytest.mark.asyncio
async def test_postgres_schema_ddl_uses_raw_psycopg_connection(monkeypatch):
    events = []
    connection = _WrappedPostgresConnection(events)

    monkeypatch.setattr(compat.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(
        compat.db_backend,
        "connect",
        lambda: _ConnectionContext(connection),
    )

    await compat._execute_schema_ddl("CREATE TABLE example (id TEXT)")

    assert events == [
        ("raw_execute", "CREATE TABLE example (id TEXT)"),
        ("raw_commit", None),
    ]


@pytest.mark.asyncio
async def test_optional_index_failure_does_not_hide_table(monkeypatch):
    events = []

    async def execute_ddl(sql: str):
        normalized = " ".join(sql.split())
        events.append(("ddl", normalized))
        if normalized.startswith("CREATE UNIQUE INDEX"):
            raise compat.db_backend.OperationalError("concurrent index creation")

    async def verify_table():
        events.append(("verify", safety._BINDINGS_TABLE))

    monkeypatch.setattr(compat, "_execute_schema_ddl", execute_ddl)
    monkeypatch.setattr(compat, "_verify_bindings_table", verify_table)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_READY", False)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_LOCK", asyncio.Lock())

    await compat._ensure_bindings_table_postgres_safe()

    assert events[0][0] == "ddl"
    assert f"CREATE TABLE IF NOT EXISTS {safety._BINDINGS_TABLE}" in events[0][1]
    assert events[1][1].startswith("CREATE UNIQUE INDEX IF NOT EXISTS")
    assert events[2] == ("verify", safety._BINDINGS_TABLE)
    assert compat._BINDINGS_SCHEMA_READY is True


@pytest.mark.asyncio
async def test_schema_initializer_verifies_and_runs_only_once(monkeypatch):
    events = []

    async def execute_ddl(sql: str):
        events.append(("ddl", " ".join(sql.split())))

    async def verify_table():
        events.append(("verify", safety._BINDINGS_TABLE))

    monkeypatch.setattr(compat, "_execute_schema_ddl", execute_ddl)
    monkeypatch.setattr(compat, "_verify_bindings_table", verify_table)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_READY", False)
    monkeypatch.setattr(compat, "_BINDINGS_SCHEMA_LOCK", asyncio.Lock())

    await compat._ensure_bindings_table_postgres_safe()
    first_run_events = list(events)
    await compat._ensure_bindings_table_postgres_safe()

    assert events == first_run_events
    assert [event[0] for event in events] == ["ddl", "ddl", "verify"]


def test_install_replaces_safety_initializer(monkeypatch):
    original = safety._ensure_bindings_table
    monkeypatch.delattr(safety, compat._INSTALL_MARKER, raising=False)

    compat.install_lava_binding_schema_compat()

    assert safety._ensure_bindings_table is compat._ensure_bindings_table_postgres_safe

    safety._ensure_bindings_table = original
    monkeypatch.delattr(safety, compat._INSTALL_MARKER, raising=False)
