"""Exercise Astro HTTP boundary: real request auth each time, never client role."""

import asyncio
import json

import pytest
from aiohttp import web

from bot import astro_api, miniapp


class Request:
    def __init__(self, body):
        self.body = body
        self.app = {}

    async def json(self):
        return self.body


def invoke(body):
    return asyncio.run(astro_api.astro_lunar_calendar(Request(body)))


@pytest.mark.parametrize("init_data", ["", None, "vk_session:" + "a" * 43])
def test_unsigned_and_vk_sessions_blocked_before_context(monkeypatch, init_data):
    async def should_not_be_called(*args, **kwargs):
        raise AssertionError("unauthenticated request touched actor state")

    monkeypatch.setattr(miniapp, "_get_user_context", should_not_be_called)
    with pytest.raises(web.HTTPUnauthorized):
        invoke({"init_data": init_data, "period": "2024-03", "timezone": "UTC"})


def test_server_role_not_client_flag_and_revocation(monkeypatch):
    calls = []

    async def actor(app, init_data):
        calls.append(init_data)
        return 123, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    allowed = {"value": True}
    monkeypatch.setattr(astro_api.config, "is_admin", lambda uid: uid == 123 and allowed["value"])
    monkeypatch.setattr(
        astro_api, "build_lunar_calendar",
        lambda period, zone: {"schema_version": "astro.lunar.v1", "period": period, "days": []},
    )
    payload = {
        "init_data": "valid-signed-mock",
        "is_admin": True,  # ignored: bootstrap/client fields are not authoritative
        "period": "2024-03",
        "timezone": "UTC",
    }
    response = invoke(payload)
    assert response.status == 200
    assert json.loads(response.text)["result"]["period"] == "2024-03"

    allowed["value"] = False
    with pytest.raises(web.HTTPForbidden):
        invoke(payload)
    assert calls == ["valid-signed-mock", "valid-signed-mock"]


def test_malformed_period_and_timezone_are_400_without_calculation(monkeypatch):
    async def actor(app, init_data):
        return 123, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda uid: True)

    def should_not_calculate(*args):
        raise AssertionError("invalid data reached expensive ephemerides")

    monkeypatch.setattr(astro_api, "build_lunar_calendar", should_not_calculate)
    for period, zone in [("2024-13", "UTC"), ("2024-03", "../etc/passwd")]:
        response = invoke({"init_data": "valid", "period": period, "timezone": zone})
        assert response.status == 400
        assert json.loads(response.text)["error"] == "invalid_input"


def test_unsupported_ephemeris_returns_503_not_fake_calendar(monkeypatch):
    async def actor(app, init_data):
        return 123, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda uid: True)

    def unavailable(*args):
        raise astro_api.AstroEngineUnavailable("no ephemeris")

    monkeypatch.setattr(astro_api, "build_lunar_calendar", unavailable)
    response = invoke({"init_data": "valid", "period": "2024-03", "timezone": "UTC"})
    assert response.status == 503
    assert json.loads(response.text)["error"] == "engine_unavailable"
