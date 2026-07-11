import ipaddress
import json
import time

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_api as api
from bot.internal_admin_dispatch import dispatch_internal_admin_request


def test_signature_covers_method_path_query_and_body():
    secret = "test-secret"
    timestamp = "1720000000"
    path = "/internal/admin/users?limit=50&cursor=abc%2F123"

    signature = api.build_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="GET",
        request_path=path,
    )

    assert api.verify_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="GET",
        request_path=path,
        signature=signature,
        now=1720000000,
        max_clock_skew_seconds=60,
    )
    assert not api.verify_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="POST",
        request_path=path,
        signature=signature,
        now=1720000000,
        max_clock_skew_seconds=60,
    )
    assert not api.verify_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="GET",
        request_path="/internal/admin/users?limit=10&cursor=abc%2F123",
        signature=signature,
        now=1720000000,
        max_clock_skew_seconds=60,
    )


def test_signature_rejects_stale_timestamp():
    signature = api.build_internal_signature(
        secret="test-secret",
        timestamp="100",
        method="GET",
        request_path="/internal/admin/health",
    )

    assert not api.verify_internal_signature(
        secret="test-secret",
        timestamp="100",
        method="GET",
        request_path="/internal/admin/health",
        signature=signature,
        now=200,
        max_clock_skew_seconds=60,
    )


def test_cursor_round_trip_and_invalid_values():
    cursor = api.encode_cursor(987654)

    assert api.decode_cursor(cursor) == 987654
    assert api.decode_cursor(None) is None
    assert api.decode_cursor("") is None

    with pytest.raises(api.InvalidCursorError):
        api.decode_cursor("not-a-valid-cursor")
    with pytest.raises(api.InvalidCursorError):
        api.encode_cursor(0)


def test_internal_peer_allowlist_supports_loopback_and_private_networks():
    networks = (
        ipaddress.ip_network("127.0.0.1/32"),
        ipaddress.ip_network("10.20.0.0/16"),
        ipaddress.ip_network("::1/128"),
    )

    assert api.is_allowed_internal_peer("127.0.0.1", networks)
    assert api.is_allowed_internal_peer("10.20.4.8", networks)
    assert api.is_allowed_internal_peer("::1", networks)
    assert not api.is_allowed_internal_peer("203.0.113.20", networks)
    assert not api.is_allowed_internal_peer("invalid", networks)


@pytest.mark.asyncio
async def test_health_endpoint_accepts_valid_hmac(monkeypatch):
    secret = "test-secret"
    timestamp = str(int(time.time()))
    path = "/internal/admin/health"
    signature = api.build_internal_signature(
        secret=secret,
        timestamp=timestamp,
        method="GET",
        request_path=path,
    )
    request = make_mocked_request(
        "GET",
        path,
        headers={
            "X-Internal-Timestamp": timestamp,
            "X-Internal-Signature": signature,
        },
    )

    async def fake_fetch_one(_sql, _parameters=()):
        return {"ok": 1}

    monkeypatch.setattr(api, "INTERNAL_API_SECRET", secret)
    monkeypatch.setattr(api, "_request_peer_ip", lambda _request: "127.0.0.1")
    monkeypatch.setattr(api, "_fetch_one", fake_fetch_one)

    response = await api.health_handler(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {
        "status": "ok",
        "channel": "telegram",
        "api_version": "1",
        "service_version": api.INTERNAL_API_SERVICE_VERSION,
    }


@pytest.mark.asyncio
async def test_health_endpoint_rejects_invalid_hmac_before_database(monkeypatch):
    request = make_mocked_request(
        "GET",
        "/internal/admin/health",
        headers={
            "X-Internal-Timestamp": str(int(time.time())),
            "X-Internal-Signature": "wrong",
        },
    )

    async def unexpected_fetch_one(_sql, _parameters=()):
        raise AssertionError("database must not be queried")

    monkeypatch.setattr(api, "INTERNAL_API_SECRET", "test-secret")
    monkeypatch.setattr(api, "_request_peer_ip", lambda _request: "127.0.0.1")
    monkeypatch.setattr(api, "_fetch_one", unexpected_fetch_one)

    response = await api.health_handler(request)

    assert response.status == 401
    assert json.loads(response.text) == {"error": "unauthorized"}


@pytest.mark.asyncio
async def test_paginated_rows_uses_descending_id_cursor(monkeypatch):
    request = make_mocked_request("GET", "/internal/admin/users?limit=2")
    captured = {}

    async def fake_fetch_all(sql, parameters=()):
        captured["sql"] = sql
        captured["parameters"] = parameters
        return [
            {"id": 10, "telegram_id": 100},
            {"id": 9, "telegram_id": 90},
            {"id": 8, "telegram_id": 80},
        ]

    monkeypatch.setattr(api, "_fetch_all", fake_fetch_all)

    items, next_cursor = await api._paginated_rows(
        request=request,
        select_sql="SELECT id, telegram_id FROM users",
    )

    assert captured["parameters"] == (3,)
    assert "ORDER BY id DESC LIMIT ?" in captured["sql"]
    assert items == [
        {"id": 10, "telegram_id": 100},
        {"id": 9, "telegram_id": 90},
    ]
    assert api.decode_cursor(next_cursor) == 9


@pytest.mark.asyncio
async def test_dispatcher_returns_json_404_for_unknown_internal_path():
    request = make_mocked_request("GET", "/internal/admin/unknown")

    response = await dispatch_internal_admin_request(request)

    assert response.status == 404
    assert json.loads(response.text) == {"error": "not_found"}
