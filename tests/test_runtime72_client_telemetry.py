import json

import pytest

from bot import miniapp


class ClientLogRequest:
    remote = "127.0.0.1"

    def __init__(self, payload):
        self.headers = {"User-Agent": "telemetry-regression"}
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "https://app.example.test"])
async def test_client_log_removes_launch_credentials_and_url_queries(monkeypatch, prefix):
    captured = []
    monkeypatch.setattr(miniapp.logger, "warning", lambda _message, data: captured.append(data))
    response = await miniapp.miniapp_client_log(ClientLogRequest({
        "event": "react-error-boundary",
        "href": prefix + "/mini-app/?tgWebAppData=SECRET_LAUNCH#SECRET_FRAGMENT",
        "search": "?init_data=SECRET_SEARCH",
        "source": prefix + "/mini-app/_next/static/chunk.js?token=SECRET_SOURCE#SECRET_HASH",
        "message": "Loading chunk failed (error: " + prefix + "/mini-app/_next/static/chunk.js?signature=SECRET_MESSAGE)",
        "init_data_len": 123,
        "hash_len": 42,
    }))

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True}
    assert len(captured) == 1
    assert "SECRET_" not in json.dumps(captured)
    event = captured[0]
    assert event["href"] == prefix + "/mini-app/"
    assert event["source"] == prefix + "/mini-app/_next/static/chunk.js"
    assert "search" not in event
    assert "Loading chunk failed" in event["message"]
    assert "/mini-app/_next/static/chunk.js" in event["message"]
    assert event["init_data_len"] == 123


@pytest.mark.asyncio
async def test_client_log_removes_plain_auth_assignments_from_error_message(monkeypatch):
    captured = []
    monkeypatch.setattr(miniapp.logger, "warning", lambda _message, data: captured.append(data))
    await miniapp.miniapp_client_log(ClientLogRequest({
        "event": "window-error",
        "message": "request rejected: init_data=SECRET_INIT&hash=SECRET_SIGNATURE; tgWebAppData=SECRET_TG",
    }))

    assert "SECRET_" not in json.dumps(captured)
    assert "request rejected:" in captured[0]["message"]


@pytest.mark.asyncio
async def test_client_log_preserves_chunk_failure_diagnostics(monkeypatch):
    captured = []
    monkeypatch.setattr(miniapp.logger, "warning", lambda _message, data: captured.append(data))
    message = "Loading chunk 278 failed. (error: https://app.example.test/mini-app/_next/static/chunks/278.hash.js)"
    await miniapp.miniapp_client_log(ClientLogRequest({
        "event": "react-error-boundary", "message": message, "status": 404,
    }))

    assert captured[0]["event"] == "react-error-boundary"
    assert captured[0]["message"] == message
    assert captured[0]["status"] == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_text", [
    "Authorization: Bearer SECRET_BEARER",
    '{"token":"SECRET_JSON"}',
    "https://user:SECRET_USERINFO@app.example.test/chunk.js",
    "https://api.telegram.org/bot123456:SECRET_BOT_TOKEN/getMe",
])
async def test_client_log_sanitizes_credentials_in_all_text_fields(monkeypatch, credential_text):
    captured = []
    monkeypatch.setattr(miniapp.logger, "warning", lambda _message, data: captured.append(data))
    request = ClientLogRequest(dict.fromkeys(
        ("event", "href", "source", "message", "file_kind", "file_name", "file_type"),
        credential_text,
    ))
    request.headers = {"User-Agent": credential_text, "X-Forwarded-For": credential_text}

    response = await miniapp.miniapp_client_log(request)

    assert response.status == 200
    assert len(captured) == 1
    assert "SECRET_" not in json.dumps(captured)


@pytest.mark.asyncio
async def test_client_log_numeric_fields_cannot_leak_text_or_raise_logged_exception(monkeypatch):
    captured = []
    exceptions = []
    monkeypatch.setattr(miniapp.logger, "warning", lambda _message, data: captured.append(data))
    monkeypatch.setattr(miniapp.logger, "exception", lambda *args: exceptions.append(args))
    response = await miniapp.miniapp_client_log(ClientLogRequest(dict.fromkeys(
        ("lineno", "colno", "hash_len", "init_data_len", "file_size", "duration_ms", "status"),
        "SECRET_INVALID_INTEGER",
    )))

    assert response.status == 200
    assert len(captured) == 1
    assert "SECRET_" not in json.dumps(captured)
    assert exceptions == []
