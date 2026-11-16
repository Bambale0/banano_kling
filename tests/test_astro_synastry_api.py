"""Synastry endpoint authorization and real API contract."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_api, miniapp


def request(body):
    async def load():
        return body
    return SimpleNamespace(app={}, content_length=None, json=load)


def call(body):
    return asyncio.run(astro_api.astro_compatibility_facts(request(body)))


@pytest.mark.parametrize("init", [None, "", "vk_session:" + "a" * 43])
def test_unsigned_requests_never_call_auth_context(monkeypatch, init):
    async def should_not_call(*args):
        raise AssertionError("Untrusted caller reached actor context")
    monkeypatch.setattr(miniapp, "_get_user_context", should_not_call)
    with pytest.raises(web.HTTPUnauthorized):
        call({"init_data": init, "person_a": {}, "person_b": {}})


def test_role_revocation_blocks_even_client_claims_admin(monkeypatch):
    async def get_context(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", get_context)
    current = {"is_admin": True}
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor: actor == 101 and current["is_admin"])
    mock = lambda a, b: {"schema_version": "astro.synastry.facts.v1", "cross_aspects": []}
    monkeypatch.setattr(astro_api, "build_compatibility_facts", mock)
    body = {"init_data": "signed", "is_admin": True, "person_a": {}, "person_b": {}}
    assert json.loads(call(body).text)["result"]["schema_version"] == "astro.synastry.facts.v1"
    current["is_admin"] = False
    with pytest.raises(web.HTTPForbidden):
        call(body)


def test_invalid_second_person_is_400(monkeypatch):
    async def get_context(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", get_context)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda uid: True)
    response = call({
        "init_data": "signed",
        "person_a": {"date": "20.03.2024", "time": "12:00", "timezone": "UTC"},
        "person_b": None,
    })
    assert response.status == 400
    assert json.loads(response.text)["error"] == "invalid_input"
