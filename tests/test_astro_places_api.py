"""Signed admin-only place search API: role, revocation, privacy and failures."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_api, miniapp
from bot.services.astro_lunar import AstroInputError
from bot.services.astro_places import AstroPlacesUnavailable


def request(body, *, content_length=None):
    async def load():
        return body
    return SimpleNamespace(app={}, content_length=content_length, json=load)


def call(body, **kwargs):
    return asyncio.run(astro_api.astro_search_places(request(body, **kwargs)))


@pytest.mark.parametrize("init", [None, "", "vk_session:" + "a" * 43])
def test_unauthenticated_cannot_search_or_invoke_user_context(monkeypatch, init):
    async def unexpected(*args):
        raise AssertionError("Untrusted caller reached actor context")
    monkeypatch.setattr(miniapp, "_get_user_context", unexpected)
    with pytest.raises(web.HTTPUnauthorized):
        call({"init_data": init, "query": "Tallinn"})


def test_valid_admin_receives_verified_results_without_raw_query_in_response(monkeypatch):
    async def actor(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor_id: actor_id == 101)
    seen = []

    def search(query, *, limit):
        seen.append((query, limit))
        return [{
            "place_id": 588409, "name": "Tallinn", "country_code": "EE",
            "latitude": 59.43696, "longitude": 24.75353,
            "timezone": "Europe/Tallinn", "source": "GeoNames",
        }]

    monkeypatch.setattr(astro_api, "search_places", search)
    response = call({"init_data": "signed", "query": "Tallinn", "is_admin": False})
    assert response.status == 200
    data = json.loads(response.text)
    assert data["results"][0]["place_id"] == 588409
    assert data["attribution"] == "© GeoNames (CC BY 4.0)"
    assert "query" not in data
    assert response.headers["Cache-Control"] == "no-store"
    assert seen == [("Tallinn", 10)]


def test_vktoken_and_revoked_admin_rejected(monkeypatch):
    async def vk_actor(*args):
        return 101, {"platform": "vk"}
    monkeypatch.setattr(miniapp, "_get_user_context", vk_actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda _: True)
    with pytest.raises(web.HTTPForbidden):
        call({"init_data": "signed", "query": "Moscow"})

    async def tg_actor(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", tg_actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda _: False)
    with pytest.raises(web.HTTPForbidden):
        call({"init_data": "signed", "query": "Moscow"})


def test_revocation_during_search_fails_closed(monkeypatch):
    async def actor(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    current = {"admin": True}
    monkeypatch.setattr(astro_api.config, "is_admin", lambda _: current["admin"])

    def slow_search(query, *, limit):
        current["admin"] = False
        return [{"place_id": 123, "name": "Hidden"}]

    monkeypatch.setattr(astro_api, "search_places", slow_search)
    with pytest.raises(web.HTTPForbidden):
        call({"init_data": "signed", "query": "Moscow"})


def test_places_missing_returns_503_without_fabrication(monkeypatch):
    async def actor(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda _: True)

    def missing(*args, **kwargs):
        raise AstroPlacesUnavailable("no DB")

    monkeypatch.setattr(astro_api, "search_places", missing)
    response = call({"init_data": "signed", "query": "Tallinn"})
    assert response.status == 503
    assert json.loads(response.text)["error"] == "places_unavailable"


def test_invalid_input_is_400_not_unsanitized_exception(monkeypatch):
    async def actor(*args):
        return 101, {"platform": "telegram"}
    monkeypatch.setattr(miniapp, "_get_user_context", actor)
    monkeypatch.setattr(astro_api.config, "is_admin", lambda _: True)

    def reject(*args, **kwargs):
        raise AstroInputError("Введите корректное название города.")

    monkeypatch.setattr(astro_api, "search_places", reject)
    response = call({"init_data": "signed", "query": "../etc/passwd"})
    assert response.status == 400
    assert json.loads(response.text)["error"] == "invalid_input"


def test_oversize_body_is_rejected_before_processing():
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        call({"init_data": "signed", "query": "Tallinn"}, content_length=10000)


def test_route_registry_uses_post_only():
    app = web.Application()
    astro_api.setup_astro_routes(app, "/mini-app")
    match = [r for r in app.router.routes() if r.resource.canonical == "/mini-app/api/astro/places"]
    assert len(match) == 1
    assert match[0].method == "POST"
