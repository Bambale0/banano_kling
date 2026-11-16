"""Placidus route cannot trust client-supplied coordinates or role."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_api, miniapp
from bot.services.astro_chart_core import AstroChartInputError, AstroChartUnavailable
from bot.services.astro_places import AstroPlacesUnavailable


def _request(body, size=None):
    async def load():
        return body

    return SimpleNamespace(app={}, json=load, content_length=size)


def _call(body, size=None):
    return asyncio.run(astro_api.astro_full_natal_facts(_request(body, size=size)))


def _signed_actor(monkeypatch, *, platform="telegram", active=True):
    async def context(*_):
        return 101, {"platform": platform}

    monkeypatch.setattr(miniapp, "_get_user_context", context)
    current = {"active": active}
    monkeypatch.setattr(astro_api.config, "is_admin", lambda actor: actor == 101 and current["active"])
    return current


@pytest.mark.parametrize("init_data", [None, "", "vk_session:" + "a" * 43])
def test_unsigned_requests_fail_before_actor_lookup(monkeypatch, init_data):
    async def forbidden(*_):
        raise AssertionError("Unexpected context check")

    monkeypatch.setattr(miniapp, "_get_user_context", forbidden)
    with pytest.raises(web.HTTPUnauthorized):
        _call({"init_data": init_data, "place_id": 498817})


def test_natal_requires_actual_telegram_admin_and_rejects_vk(monkeypatch):
    _signed_actor(monkeypatch, platform="vk")
    with pytest.raises(web.HTTPForbidden):
        _call({"init_data": "signed", "place_id": 498817})
    _signed_actor(monkeypatch, active=False)
    with pytest.raises(web.HTTPForbidden):
        _call({"init_data": "signed", "place_id": 498817})


def test_server_resolves_coordinates_timezone_and_ignores_forged_client_fields(monkeypatch):
    _signed_actor(monkeypatch)
    seen = {}

    def place(identifier):
        assert identifier == 498817
        return {
            "place_id": 498817, "name": "Saint Petersburg", "country_code": "RU",
            "latitude": 59.93863, "longitude": 30.31413, "timezone": "Europe/Moscow",
        }

    def compute(profile):
        seen.update(profile)
        return {
            "schema_version": "astro.natal-facts.v1",
            "chart": {
                "angles": {"asc": 118.2, "mc": 349.3},
                "cusps": [30.0 * i for i in range(12)],
                "bodies": {"Sun": {"lon": 340.1, "retro": False}},
                "aspects": [],
            },
            "accuracy": {"birth_time_known": True, "houses_available": True},
        }

    monkeypatch.setattr(astro_api, "get_place", place)
    monkeypatch.setattr(astro_api, "build_full_natal_facts", compute)
    response = _call({
        "init_data": "signed", "place_id": 498817, "date": "29.02.2000",
        "time": "13:45", "latitude": 0.0, "longitude": 0.0, "timezone": "UTC",
        "is_admin": True, "fold": 0,
    })
    result = json.loads(response.text)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert result["result"]["chart"]["angles"]["asc"] == 118.2
    assert result["place"]["country_code"] == "RU"
    assert seen == {
        "date": "29.02.2000", "time": "13:45", "fold": 0,
        "latitude": 59.93863, "longitude": 30.31413,
        "timezone": "Europe/Moscow",
    }


def test_revocation_during_computation_does_not_leak_facts(monkeypatch):
    current = _signed_actor(monkeypatch)
    monkeypatch.setattr(
        astro_api, "get_place", lambda _: {
            "place_id": 498817, "name": "Saint Petersburg", "country_code": "RU",
            "latitude": 59.93863, "longitude": 30.31413, "timezone": "Europe/Moscow",
        },
    )

    def compute(_):
        current["active"] = False
        return {"schema_version": "astro.natal-facts.v1", "chart": {}}

    monkeypatch.setattr(astro_api, "build_full_natal_facts", compute)
    with pytest.raises(web.HTTPForbidden):
        _call({"init_data": "signed", "place_id": 498817, "date": "29.02.2000"})


@pytest.mark.parametrize("place_id", [None, "498817", 0, True, -8])
def test_invalid_place_id_is_rejected_before_computation(monkeypatch, place_id):
    _signed_actor(monkeypatch)
    resp = _call({"init_data": "signed", "place_id": place_id, "date": "29.02.2000"})
    assert resp.status == 400
    assert json.loads(resp.text)["error"] == "invalid_input"


def test_unavailable_geo_db_or_ephemeris_fails_closed(monkeypatch):
    _signed_actor(monkeypatch)

    def no_city(_):
        raise AstroPlacesUnavailable("db missing")

    monkeypatch.setattr(astro_api, "get_place", no_city)
    resp = _call({"init_data": "signed", "place_id": 498817, "date": "29.02.2000"})
    assert resp.status == 503
    assert json.loads(resp.text)["error"] == "engine_unavailable"

    monkeypatch.setattr(astro_api, "get_place", lambda _: {
        "latitude": 59.9, "longitude": 30.3, "timezone": "Europe/Moscow",
    })

    def no_ephem(_):
        raise AstroChartUnavailable("JPL confidential file path")

    monkeypatch.setattr(astro_api, "build_full_natal_facts", no_ephem)
    resp = _call({"init_data": "signed", "place_id": 498817, "date": "29.02.2000"})
    assert resp.status == 503
    assert "confidential" not in resp.text
    assert json.loads(resp.text)["error"] == "engine_unavailable"


def test_invalid_birth_time_and_oversized_body(monkeypatch):
    _signed_actor(monkeypatch)
    monkeypatch.setattr(astro_api, "get_place", lambda _: {
        "latitude": 59.9, "longitude": 30.3, "timezone": "Europe/Moscow",
    })

    def invalid(_):
        raise AstroChartInputError("Укажите существующую дату рождения.")

    monkeypatch.setattr(astro_api, "build_full_natal_facts", invalid)
    resp = _call({"init_data": "signed", "place_id": 498817, "date": "31.02.2000"})
    assert resp.status == 400
    assert json.loads(resp.text)["error"] == "invalid_input"
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        _call({"init_data": "signed"}, size=9000)


def test_route_is_admin_post_only():
    app = web.Application()
    astro_api.setup_astro_routes(app, "/mini-app")
    matches = [
        route for route in app.router.routes()
        if route.resource.canonical == "/mini-app/api/astro/natal/full"
    ]
    assert len(matches) == 1
    assert matches[0].method == "POST"
