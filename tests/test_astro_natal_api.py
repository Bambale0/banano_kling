"""HTTP natal auth and failure semantics with no fake or paid results."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_api, miniapp


def _request(body, *, content_length=None):
    async def read():
        return body

    return SimpleNamespace(app={}, content_length=content_length, json=read)


def _invoke(body, **kw):
    return asyncio.run(astro_api.astro_natal_facts(_request(body, **kw)))


@pytest.mark.parametrize("auth", ["", None, "vk_session:" + "a" * 43])
def test_unsigned_or_vk_rejected_before_actor_lookup(monkeypatch, auth):
    async def rejected(*args):
        raise AssertionError("session must not be read for unsigned requests")

    monkeypatch.setattr(miniapp, "_get_user_context", rejected)
    with pytest.raises(web.HTTPUnauthorized):
        _invoke({"init_data": auth, "date": "20.03.2024", "timezone": "UTC"})


def test_role_is_checked_on_every_request_even_if_client_claims_admin(monkeypatch):
    async def actor(*args):
        return 42, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    allowed = {"status": True}
    monkeypatch.setattr(astro_api.config, "is_admin", lambda user_id: allowed["status"] and user_id == 42)

    def fake_facts(**data):
        return {"schema_version": "astro.natal.facts.v1", "birth_time_known": True}

    monkeypatch.setattr(astro_api, "build_natal_facts", fake_facts)
    body = {"init_data": "valid", "date": "20.03.2024", "time": "12:00", "timezone": "UTC", "is_admin": True}
    response = _invoke(body)
    assert response.status == 200
    assert json.loads(response.text)["result"]["schema_version"] == "astro.natal.facts.v1"

    allowed["status"] = False
    with pytest.raises(web.HTTPForbidden):
        _invoke(body)


def test_invalid_date_returns_400_before_calculation(monkeypatch):
    async def actor(*args):
        return 42, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor_id: True)
    response = _invoke({"init_data": "valid", "date": "31.02.2000", "timezone": "Europe/Moscow"})
    assert response.status == 400
    assert json.loads(response.text)["error"] == "invalid_input"


def test_wrong_payload_is_rejected(monkeypatch):
    async def actor(*args):
        return 42, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor_id: True)
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        _invoke({"init_data": "valid"}, content_length=5000)
    response = _invoke([], content_length=1)
    assert response.status == 400


def test_engine_unavailable_returns_service_unavailable(monkeypatch):
    async def actor(*args):
        return 42, {"platform": "telegram"}

    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor_id: True)

    def unavailable(**kwargs):
        raise astro_api.AstroEngineUnavailable("missing kernels")

    monkeypatch.setattr(astro_api, "build_natal_facts", unavailable)
    response = _invoke({"init_data": "valid", "date": "20.03.2024", "timezone": "UTC"})
    assert response.status == 503
    assert json.loads(response.text)["error"] == "engine_unavailable"
