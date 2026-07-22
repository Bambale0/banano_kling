import pytest
from aiohttp import web

from bot import internal_admin_command_schema as command_schema
from bot import internal_admin_dispatch as dispatch


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_command_schema_requires_postgresql(monkeypatch):
    monkeypatch.setattr(command_schema, "_SCHEMA_READY", False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        await command_schema.ensure_internal_admin_command_schema()


@pytest.mark.asyncio
async def test_command_schema_creates_idempotency_ledger(monkeypatch):
    connection = FakeConnection()

    async def fake_connect(_database_url: str):
        return connection

    monkeypatch.setattr(command_schema, "_SCHEMA_READY", False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost/database")
    monkeypatch.setattr(command_schema.psycopg.AsyncConnection, "connect", fake_connect)

    await command_schema.ensure_internal_admin_command_schema()

    statements = "\n".join(connection.cursor_instance.statements)
    assert "CREATE TABLE IF NOT EXISTS internal_admin_commands" in statements
    assert "idx_internal_admin_commands_request_id" in statements
    assert "idx_internal_admin_commands_target" in statements
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True


@pytest.mark.asyncio
async def test_dispatch_does_not_touch_schema_before_authorization(monkeypatch):
    request = object()
    schema_called = False

    async def reject_request(_request):
        return b"", web.json_response({"error": "unauthorized"}, status=401)

    async def unexpected_schema_call():
        nonlocal schema_called
        schema_called = True

    monkeypatch.setattr(dispatch, "_authorize_request", reject_request)
    monkeypatch.setattr(dispatch, "ensure_internal_admin_command_schema", unexpected_schema_call)

    response = await dispatch._authenticate_and_prepare(request)  # type: ignore[arg-type]

    assert response.status == 401
    assert schema_called is False
