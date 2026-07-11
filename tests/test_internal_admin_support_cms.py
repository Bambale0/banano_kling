import json
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_api as base_api
from bot import internal_admin_cms as cms
from bot import internal_admin_dispatch as dispatcher
from bot import internal_admin_support as support
from bot.handlers.support import SupportStates
from bot.internal_admin_user_commands import CommandValidationError


def ticket_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 17,
        "user_id": 4,
        "telegram_id": 123456789,
        "username": "igor",
        "first_name": "Igor",
        "last_name": None,
        "subject": "Payment is missing",
        "status": "new",
        "priority": "high",
        "assigned_admin_id": None,
        "linked_payment_id": 9,
        "linked_operation_id": None,
        "source": "telegram",
        "created_at": "2026-07-11T10:00:00",
        "updated_at": "2026-07-11T10:10:00",
        "last_user_message_at": "2026-07-11T10:10:00",
        "last_admin_message_at": None,
        "closed_at": None,
        "messages_count": 2,
        "attachments_count": 1,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_ticket_list_uses_parameterized_filters(monkeypatch) -> None:
    request = make_mocked_request(
        "GET",
        "/internal/admin/tickets?limit=2&query=igor&status=new&priority=high&assigned_admin_id=admin-1",
    )
    captured: dict[str, Any] = {}

    async def fake_fetch_all(sql: str, parameters: tuple[Any, ...] = ()):
        captured["sql"] = sql
        captured["parameters"] = parameters
        return [ticket_row()]

    monkeypatch.setattr(base_api, "_fetch_all", fake_fetch_all)
    response = await support.tickets_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["items"][0]["id"] == 17
    assert "st.status = ?" in captured["sql"]
    assert "st.priority = ?" in captured["sql"]
    assert "st.assigned_admin_id = ?" in captured["sql"]
    assert captured["parameters"][-4:] == ("new", "high", "admin-1", 3)


def test_cms_content_validation_keeps_only_published_contract() -> None:
    content = cms._normalize_content(
        {
            "text": "Support message",
            "button_label": "Open",
            "button_url": "https://example.com/help",
            "locale": "ru-RU",
            "metadata": {"placement": "support"},
        }
    )

    assert content["text"] == "Support message"
    assert content["button_url"] == "https://example.com/help"


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"text": "hello", "secret": "must-not-exist"}, "unsupported content keys"),
        ({"text": "hello", "button_url": "javascript:alert(1)"}, "button_url"),
        ({"metadata": {"only": "metadata"}}, "text or caption"),
    ],
)
def test_cms_content_validation_rejects_unsafe_payloads(
    payload: dict[str, Any],
    match: str,
) -> None:
    with pytest.raises(CommandValidationError, match=match):
        cms._normalize_content(payload)


def test_support_fsm_has_separate_new_and_followup_states() -> None:
    assert SupportStates.waiting_new_message.state != SupportStates.waiting_followup.state


@pytest.mark.asyncio
async def test_dispatch_routes_ticket_with_support_schema(monkeypatch) -> None:
    request = make_mocked_request("GET", "/internal/admin/tickets/17")
    captured: dict[str, Any] = {}

    async def prepared(_request: web.Request, **kwargs: Any) -> None:
        captured.update(kwargs)
        return None

    async def fake_detail(inner_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ticket_id": inner_request.match_info["ticket_id"],
            }
        )

    monkeypatch.setattr(dispatcher, "_authenticate_and_prepare", prepared)
    monkeypatch.setitem(dispatcher._TICKET_HANDLERS, "detail", fake_detail)

    response = await dispatcher.dispatch_internal_admin_request(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {"ticket_id": "17"}
    assert captured["support_schema"] is True


@pytest.mark.asyncio
async def test_dispatch_routes_cms_save_with_support_schema(monkeypatch) -> None:
    request = make_mocked_request("POST", "/internal/admin/cms/documents")
    captured: dict[str, Any] = {}

    async def prepared(_request: web.Request, **kwargs: Any) -> None:
        captured.update(kwargs)
        return None

    async def fake_save(_request: web.Request) -> web.Response:
        return web.json_response({"saved": True})

    monkeypatch.setattr(dispatcher, "_authenticate_and_prepare", prepared)
    monkeypatch.setattr(dispatcher, "save_cms_document_handler", fake_save)

    response = await dispatcher.dispatch_internal_admin_request(request)

    assert response.status == 200
    assert json.loads(response.text) == {"saved": True}
    assert captured["support_schema"] is True
