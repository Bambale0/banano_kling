import json
import time
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_api as base_api
from bot import internal_admin_user_commands as commands


class FakeRequest:
    def __init__(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.method = method
        self.path = path
        self.raw_path = path
        self.headers = headers
        self.transport = None
        self.remote = "127.0.0.1"
        self._body = body

    async def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_post_authorization_requires_command_headers(monkeypatch):
    secret = "test-secret"
    body = b'{"reason":"manual review"}'
    timestamp = str(int(time.time()))
    signature = base_api.build_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="POST",
        request_path="/internal/admin/users/12/block",
        body=body,
    )
    request = FakeRequest(
        method="POST",
        path="/internal/admin/users/12/block",
        body=body,
        headers={
            "X-Internal-Timestamp": timestamp,
            "X-Internal-Signature": signature,
        },
    )
    monkeypatch.setattr(base_api, "INTERNAL_API_SECRET", secret)
    monkeypatch.setattr(base_api, "_request_peer_ip", lambda _request: "127.0.0.1")

    _, response = await commands._authorize_request(request)  # type: ignore[arg-type]

    assert response is not None
    assert response.status == 400
    assert "idempotency-key" in json.loads(response.text)["error"]


@pytest.mark.asyncio
async def test_search_users_builds_parameterized_filters(monkeypatch):
    request = make_mocked_request(
        "GET",
        "/internal/admin/users?limit=2&query=igor&is_banned=false",
    )
    captured: dict[str, Any] = {}

    async def fake_fetch_all(sql: str, parameters: tuple[Any, ...] = ()):
        captured["sql"] = sql
        captured["parameters"] = parameters
        return [
            {
                "id": 4,
                "telegram_id": 339795159,
                "username": "igor",
                "first_name": "Igor",
                "last_name": None,
                "credits": 42,
                "has_paid": True,
                "is_banned": 0,
                "created_at": "2026-07-11T10:00:00",
                "updated_at": "2026-07-11T10:00:00",
            }
        ]

    monkeypatch.setattr(base_api, "_fetch_all", fake_fetch_all)

    response = await commands.search_users_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["items"][0]["telegram_id"] == 339795159
    assert payload["items"][0]["is_banned"] is False
    assert "LOWER(COALESCE(username" in captured["sql"]
    assert captured["parameters"][-2:] == (0, 3)


def test_balance_payload_rejects_zero_amount():
    request = make_mocked_request("POST", "/internal/admin/users/1/balance-adjustments")
    request["internal_body"] = json.dumps(
        {"amount": 0, "reason": "manual correction"}
    ).encode()

    with pytest.raises(commands.CommandValidationError, match="outside the allowed range"):
        commands._parse_command_payload(request, require_amount=True)


class FakeCursor:
    def __init__(self, *, rowcount: int = 0, row: dict[str, Any] | None = None) -> None:
        self.rowcount = rowcount
        self._row = row

    async def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, parameters: tuple[Any, ...] = ()):
        self.calls.append((sql, parameters))
        if "INSERT INTO internal_admin_commands" in sql:
            return FakeCursor(rowcount=0)
        if "SELECT action, target_user_id" in sql:
            return FakeCursor(
                row={
                    "action": "user.block",
                    "target_user_id": 12,
                    "status": "completed",
                    "response_payload": {
                        "channel": "telegram",
                        "api_version": "1",
                        "data": {"id": 12, "is_banned": True},
                    },
                }
            )
        return FakeCursor(rowcount=0)


@pytest.mark.asyncio
async def test_completed_idempotent_command_returns_previous_response(monkeypatch):
    connection = FakeConnection()

    async def skip_schema(_connection):
        return None

    monkeypatch.setattr(commands, "_ensure_command_table", skip_schema)
    response = await commands._reserve_command(
        connection,  # type: ignore[arg-type]
        idempotency_key="same-command-key",
        action="user.block",
        user_id=12,
        admin_user_id="admin-user-id",
        request_id="request-id-123",
        payload={"reason": "manual review"},
    )

    assert response is not None
    assert response["data"]["is_banned"] is True
