import json
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_api as base_api
from bot import internal_admin_operation_actions as actions
from bot import internal_admin_operations as operations
from bot.internal_admin_dispatch import _AuthenticatedBody


class FakeCursor:
    def __init__(self, row: dict[str, Any] | None = None, *, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False
        self.rolled_back = False
        self.row_factory = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, parameters: tuple[Any, ...] = ()):
        self.calls.append((sql, tuple(parameters)))
        if "SELECT credits FROM users" in sql:
            return FakeCursor({"credits": 37})
        return FakeCursor()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def operation_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 7,
        "task_id": "task-7",
        "user_id": 3,
        "telegram_id": 123456,
        "username": "igor",
        "first_name": "Igor",
        "last_name": None,
        "type": "image",
        "preset_id": "new",
        "model": "banana_2",
        "status": "failed",
        "cost": 10,
        "duration": None,
        "aspect_ratio": "1:1",
        "prompt": "portrait",
        "result_url": None,
        "result_urls": None,
        "request_data": json.dumps(
            {
                "prompt": "portrait",
                "api_key": "do-not-leak",
                "callback_url": "https://private.invalid",
            }
        ),
        "parent_generation_id": None,
        "action_type": None,
        "created_at": "2026-07-11T10:00:00",
        "completed_at": "2026-07-11T10:01:00",
        "updated_at": "2026-07-11T10:01:00",
        "refunded_credits": 0,
    }
    row.update(overrides)
    return row


def command_request(path: str, payload: dict[str, Any]):
    request = make_mocked_request(
        "POST",
        path,
        headers={
            "Idempotency-Key": "idempotency-operation-7",
            "X-Admin-User-Id": "admin-user-123",
            "X-Request-Id": "request-operation-7",
        },
    )
    request.match_info["operation_id"] = "7"
    request["internal_body"] = _AuthenticatedBody(
        json.dumps(payload, separators=(",", ":")).encode()
    )
    return request


def test_authenticated_body_is_bytes_and_exact_json_text() -> None:
    body = _AuthenticatedBody(b'{"confirmation":"REPLAY 7"}')

    assert body.decode() == '{"confirmation":"REPLAY 7"}'
    assert str(body) == '{"confirmation":"REPLAY 7"}'
    assert operations._parse_request_data(body)["confirmation"] == "REPLAY 7"


def test_operation_details_redact_sensitive_snapshot() -> None:
    item = operations._operation_from_row(operation_row(), include_details=True)

    assert item["request"]["prompt"] == "portrait"
    assert item["request"]["api_key"] == "[redacted]"
    assert item["request"]["callback_url"] == "[redacted]"
    assert item["refundable_credits"] == 10


@pytest.mark.asyncio
async def test_operations_list_builds_parameterized_filters(monkeypatch) -> None:
    request = make_mocked_request(
        "GET",
        "/internal/admin/operations?limit=2&query=igor&status=failed&type=image&user_id=3",
    )
    captured: dict[str, Any] = {}

    async def fake_fetch_all(sql: str, parameters: tuple[Any, ...] = ()):
        captured["sql"] = sql
        captured["parameters"] = parameters
        return [operation_row()]

    monkeypatch.setattr(base_api, "_fetch_all", fake_fetch_all)
    response = await operations.operations_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["items"][0]["id"] == 7
    assert "LOWER(gt.status) = ?" in captured["sql"]
    assert "LOWER(gt.type) = ?" in captured["sql"]
    assert captured["parameters"][-4:] == ("failed", "image", 3, 3)


@pytest.mark.asyncio
async def test_refund_is_capped_and_persisted_atomically(monkeypatch) -> None:
    request = command_request(
        "/internal/admin/operations/7/refund",
        {
            "amount": 4,
            "reason": "provider failure refund",
            "comment": "support ticket 55",
            "confirmation": "REFUND 4",
        },
    )
    connection = FakeConnection()
    recorded: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []

    async def reserve(*_args, **_kwargs):
        return None

    async def fetch_operation(*_args, **_kwargs):
        return operation_row(refunded_credits=2)

    async def record(*_args, **kwargs):
        recorded.append(kwargs)

    async def complete(*_args, **kwargs):
        completed.append(kwargs)

    monkeypatch.setattr(operations.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(operations, "_reserve_command", reserve)
    monkeypatch.setattr(operations, "_fetch_operation_in_connection", fetch_operation)
    monkeypatch.setattr(operations, "_record_event", record)
    monkeypatch.setattr(operations, "_complete_command", complete)

    response = await operations.refund_operation_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["data"]["amount"] == 4
    assert payload["data"]["refunded_total"] == 6
    assert payload["data"]["refundable_remaining"] == 4
    assert recorded[0]["event_type"] == "credits.refund"
    assert recorded[0]["amount"] == 4
    assert completed
    assert connection.committed is True
    assert any("UPDATE users" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_refund_rejects_amount_above_remaining(monkeypatch) -> None:
    request = command_request(
        "/internal/admin/operations/7/refund",
        {
            "amount": 5,
            "reason": "provider failure refund",
            "confirmation": "REFUND 5",
        },
    )
    connection = FakeConnection()

    async def reserve(*_args, **_kwargs):
        return None

    async def fetch_operation(*_args, **_kwargs):
        return operation_row(cost=10, refunded_credits=8)

    monkeypatch.setattr(operations.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(operations, "_reserve_command", reserve)
    monkeypatch.setattr(operations, "_fetch_operation_in_connection", fetch_operation)

    with pytest.raises(operations.CommandConflictError, match="remaining refundable credits"):
        await operations.refund_operation_handler.__wrapped__(request)


@pytest.mark.asyncio
async def test_replay_returns_saved_idempotent_response(monkeypatch) -> None:
    request = command_request(
        "/internal/admin/operations/7/replay",
        {
            "reason": "retry after provider outage",
            "confirmation": "REPLAY 7",
        },
    )
    connection = FakeConnection()
    saved = {
        "channel": "telegram",
        "api_version": "1",
        "data": {"id": 8, "task_id": "child-8"},
    }

    async def fetch_operation(_operation_id: int):
        return operation_row()

    async def reserve(*_args, **_kwargs):
        return saved

    monkeypatch.setattr(actions.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(actions.operations, "_fetch_operation", fetch_operation)
    monkeypatch.setattr(actions, "_reserve_command", reserve)

    response = await actions.replay_operation_handler.__wrapped__(request)

    assert response.status == 200
    assert json.loads(response.text) == saved
    assert connection.rolled_back is True
