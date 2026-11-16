"""Signed admin-only facts for karma, annual/monthly transits and solar return."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_extended_api, miniapp
from bot.services.astro_chart_core import AstroChartInputError, AstroChartUnavailable
from bot.services.astro_places import AstroPlacesUnavailable


def request(body, *, kind="karma", length=None):
    async def payload():
        return body

    return SimpleNamespace(
        app={}, match_info={"kind": kind}, json=payload,
        content_length=length,
    )


def run(body, kind="karma", length=None):
    return asyncio.run(astro_extended_api.astro_extended_facts(
        request(body, kind=kind, length=length)
    ))


@pytest.fixture()
def actor(monkeypatch):
    active = {"allowed": True, "platform": "telegram"}

    async def context(*args):
        return 101, {"platform": active["platform"]}

    monkeypatch.setattr(miniapp, "_get_user_context", context)
    monkeypatch.setattr(
        astro_extended_api.config,
        "is_admin",
        lambda user_id: user_id == 101 and active["allowed"],
    )
    return active


@pytest.fixture()
def place(monkeypatch):
    places = {
        498817: {
            "place_id": 498817, "name": "Saint Petersburg", "country_code": "RU",
            "latitude": 59.9386, "longitude": 30.3141, "timezone": "Europe/Moscow",
        },
        2950159: {
            "place_id": 2950159, "name": "Berlin", "country_code": "DE",
            "latitude": 52.52, "longitude": 13.40, "timezone": "Europe/Berlin",
        },
    }
    seen = []

    def lookup(place_id):
        seen.append(place_id)
        return places[place_id]

    monkeypatch.setattr(astro_extended_api, "get_place", lookup)
    return seen


def payload(**extra):
    return {
        "init_data": "telegram-signed",
        "place_id": 498817,
        "date": "29.02.2000",
        "time": "13:45",
        **extra,
    }


@pytest.mark.parametrize("kind", ["karma", "year", "month", "solar"])
def test_routes_registered_as_post_only(kind):
    app = web.Application()
    astro_extended_api.setup_astro_extended_routes(app, "/mini-app")
    routes = list(app.router.routes())
    match = [r for r in routes if r.resource.canonical == "/mini-app/api/astro/" + kind]
    assert len(match) == 1
    assert match[0].method == "POST"


@pytest.mark.parametrize("bad", [None, "", "vk_session:" + "a" * 43])
def test_reject_unsigned_before_facts(actor, bad):
    with pytest.raises(web.HTTPUnauthorized):
        run(payload(init_data=bad))


def test_reject_non_admin_and_vk(actor):
    actor["platform"] = "vk"
    with pytest.raises(web.HTTPForbidden):
        run(payload())
    actor["platform"] = "telegram"
    actor["allowed"] = False
    with pytest.raises(web.HTTPForbidden):
        run(payload())


def test_karma_uses_server_coordinates_and_node_indicators(monkeypatch, actor, place):
    seen = []

    def compute(birth):
        seen.append(birth)
        return {
            "schema_version": "astro.karma-indicators.v1",
            "chart": {"bodies": {"TrueNode": {"lon": 200}}},
            "indicators": {"TrueNode": {"lon": 200}},
            "aspects": [],
        }

    monkeypatch.setattr(astro_extended_api, "build_karma_indicators", compute)
    response = run(payload(latitude=0, longitude=0, timezone="UTC"))
    result = json.loads(response.text)
    assert result["result"]["indicators"]["TrueNode"]["lon"] == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert place == [498817]
    assert seen[0] == {
        "date": "29.02.2000", "time": "13:45",
        "latitude": 59.9386, "longitude": 30.3141,
        "timezone": "Europe/Moscow",
    }


@pytest.mark.parametrize("kind,period,expected", [
    ("year", "2028", {"year": 2028, "month": None}),
    ("month", "2028-02", {"year": 2028, "month": 2}),
])
def test_transits_have_explicit_month_or_year(monkeypatch, actor, place, kind, period, expected):
    seen = []

    def compute(birth, **kwargs):
        seen.append((birth, kwargs))
        return {"schema_version": "astro.transit-snapshots.v1", "samples": []}

    monkeypatch.setattr(astro_extended_api, "build_transit_snapshots", compute)
    result = run(payload(period=period), kind=kind)
    assert result.status == 200
    assert seen[0][1] == expected
    assert seen[0][0]["timezone"] == "Europe/Moscow"


@pytest.mark.parametrize("kind,period", [
    ("year", "2028-02"), ("year", 2028), ("year", "2800"),
    ("month", "2028"), ("month", "2028-13"), ("month", "00-01"),
])
def test_bad_period_rejected_without_computation(actor, place, kind, period):
    response = run(payload(period=period), kind=kind)
    assert response.status == 400
    assert json.loads(response.text)["error"] == "invalid_input"
    assert place == []


def test_solar_uses_independent_server_resolved_return_location(monkeypatch, actor, place):
    seen = []

    def compute(birth, *, target_year, return_location):
        seen.append((birth, target_year, return_location))
        return {"schema_version": "astro.solar-facts.v1", "solar_chart": {"cusps": [1] * 12}}

    monkeypatch.setattr(astro_extended_api, "build_solar_return_facts", compute)
    response = run(payload(period="2028", return_place_id=2950159,
                           return_timezone="UTC", return_latitude=0), kind="solar")
    assert response.status == 200
    assert seen[0][1] == 2028
    assert seen[0][2] == {
        "latitude": 52.52, "longitude": 13.40, "timezone": "Europe/Berlin",
    }
    assert place == [498817, 2950159]


def test_solar_requires_return_place_id(actor, place):
    response = run(payload(period="2028"), kind="solar")
    assert response.status == 400
    assert place == []


def test_revoked_while_computing_never_returns_result(monkeypatch, actor, place):
    def compute(_):
        actor["allowed"] = False
        return {"schema_version": "astro.karma-indicators.v1", "indicators": {}}

    monkeypatch.setattr(astro_extended_api, "build_karma_indicators", compute)
    with pytest.raises(web.HTTPForbidden):
        run(payload())


def test_unavailable_engines_or_places_return_sanitized_503(monkeypatch, actor, place):
    def missing(_):
        raise AstroChartUnavailable("secret /root/private/path")

    monkeypatch.setattr(astro_extended_api, "build_karma_indicators", missing)
    response = run(payload())
    assert response.status == 503
    assert "private" not in response.text

    def missing_db(_):
        raise AstroPlacesUnavailable("secret /root/private/path")

    monkeypatch.setattr(astro_extended_api, "get_place", missing_db)
    response = run(payload())
    assert response.status == 503
    assert "private" not in response.text


def test_invalid_profile_and_oversized_body(monkeypatch, actor, place):
    def invalid(_):
        raise AstroChartInputError("Дата рождения не существует.")

    monkeypatch.setattr(astro_extended_api, "build_karma_indicators", invalid)
    response = run(payload())
    assert response.status == 400
    assert json.loads(response.text)["error"] == "invalid_input"
    with pytest.raises(web.HTTPRequestEntityTooLarge):
        run(payload(), length=9000)


@pytest.mark.parametrize("kind", ["unknown", "../karma", "lunar"])
def test_unknown_services_are_never_executable(actor, place, kind):
    with pytest.raises(web.HTTPNotFound):
        run(payload(), kind=kind)


def test_extended_services_reachable_from_main_astro_route_setup():
    from bot.astro_api import setup_astro_routes

    app = web.Application()
    setup_astro_routes(app, '/mini-app')
    paths = {(r.method, r.resource.canonical) for r in app.router.routes()}
    for kind in ('karma', 'year', 'month', 'solar'):
        assert ('POST', '/mini-app/api/astro/' + kind) in paths
