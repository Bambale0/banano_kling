import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_dispatch as dispatcher
from bot import internal_admin_payment_actions as actions
from bot.internal_admin_dispatch import _AuthenticatedBody
from bot.internal_admin_user_commands import CommandValidationError


@pytest.mark.asyncio
async def test_payment_action_rejects_malformed_signed_json() -> None:
    request = make_mocked_request("POST", "/internal/admin/payments/9/recheck")
    request["internal_body"] = _AuthenticatedBody(b"{not-json")

    with pytest.raises(CommandValidationError, match="valid JSON"):
        await actions.recheck_payment_handler.__wrapped__(request)


@pytest.mark.asyncio
async def test_saved_tariff_failure_preserves_http_status(monkeypatch) -> None:
    request = make_mocked_request("POST", "/internal/admin/tariffs/publish")
    request["internal_body"] = _AuthenticatedBody(
        b'{"reason":"restore old prices","confirmation":"PUBLISH TARIFFS","config":{}}'
    )

    async def saved_failure(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "channel": "telegram",
                "api_version": "1",
                "error": "tariff_publish_failed",
                "detail": "disk failure",
                "_http_status": 502,
            }
        )

    monkeypatch.setattr(
        actions.tariffs.publish_tariffs_handler,
        "__wrapped__",
        saved_failure,
    )
    response = await actions.publish_tariffs_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 502
    assert payload["error"] == "tariff_publish_failed"
    assert "_http_status" not in payload


@pytest.mark.asyncio
async def test_authenticated_dispatch_maps_validation_to_400(monkeypatch) -> None:
    request = make_mocked_request("POST", "/internal/admin/payments/9/recheck")

    async def prepared(_request: web.Request, **_kwargs) -> None:
        return None

    async def invalid_handler(_request: web.Request) -> web.Response:
        raise CommandValidationError("request body must be valid JSON")

    monkeypatch.setattr(dispatcher, "_authenticate_and_prepare", prepared)
    response = await dispatcher._dispatch_authenticated(request, invalid_handler)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload == {
        "error": "invalid_command",
        "detail": "request body must be valid JSON",
    }
