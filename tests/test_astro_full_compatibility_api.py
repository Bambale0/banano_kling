"""Full synastry must use signed admin and two independently verified GeoNames IDs."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_full_compatibility_api as api
from bot import miniapp
from bot.services.astro_chart_core import AstroChartUnavailable
from bot.services.astro_places import AstroPlacesUnavailable


def request(body):
    async def read_json():
        return body
    return SimpleNamespace(app={}, json=read_json, content_length=None)


def call(body):
    return asyncio.run(api.astro_full_compatibility_facts(request(body)))


def body():
    return {"init_data": "test-signed", "person_a": {
        "date": "29.02.2000", "time": "13:45", "place_id": 498817,
    }, "person_b": {
        "date": "02.06.2001", "time": "11:30", "place_id": 2950159,
    }}


def auth(monkeypatch, *, platform="telegram", enabled=True):
    async def context(*_):
        return 911, {"platform": platform}
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    status = {"enabled": enabled}
    monkeypatch.setattr(api.config, "is_admin", lambda actor: actor == 911 and status["enabled"])
    return status


def places(monkeypatch):
    seen = []
    def resolver(place_id):
        seen.append(place_id)
        place = {498817: (59.94, 30.31, "Europe/Moscow"),
                 2950159: (52.52, 13.40, "Europe/Berlin")}[place_id]
        return {"place_id": place_id, "latitude": place[0],
                "longitude": place[1], "timezone": place[2]}
    monkeypatch.setattr(api, "get_place", resolver)
    return seen


def test_real_distinct_geo_ids_are_authoritative(monkeypatch):
    auth(monkeypatch)
    found = places(monkeypatch)
    computed = []
    def compute(first, second):
        computed.extend([first, second])
        return {"schema_version": "astro.synastry-facts.v1", "first": {},
                "second": {}, "aspects": [],
                "house_overlays": {"first_in_second": {"Sun": 2},
                                   "second_in_first": {"Moon": 10}}}
    monkeypatch.setattr(api, "build_full_synastry_facts", compute)
    payload = body()
    payload["person_a"].update({"latitude": 0, "longitude": 0,
                                 "timezone": "UTC", "is_admin": True})
    response = call(payload)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert json.loads(response.text)["result"]["house_overlays"]["first_in_second"]["Sun"] == 2
    assert sorted(found) == [498817, 2950159]
    assert computed[0] == {"date": "29.02.2000", "time": "13:45",
                           "latitude": 59.94, "longitude": 30.31, "timezone": "Europe/Moscow"}
    assert computed[1]["timezone"] == "Europe/Berlin"


@pytest.mark.parametrize("init_data", [None, "", "vk_session:invalid"])
def test_unsigned_requests_are_denied_before_lookup(monkeypatch, init_data):
    async def forbidden(*_):
        raise AssertionError("identity should not be checked")
    monkeypatch.setattr(miniapp, "_get_user_context", forbidden)
    with pytest.raises(web.HTTPUnauthorized):
        call({**body(), "init_data": init_data})


@pytest.mark.parametrize("platform,enabled", [("vk", True), ("telegram", False)])
def test_foreign_platform_or_nonadmin_is_denied(monkeypatch, platform, enabled):
    auth(monkeypatch, platform=platform, enabled=enabled)
    with pytest.raises(web.HTTPForbidden):
        call(body())


@pytest.mark.parametrize("invalid", [None, "498817", True, 0, -1, 2**40])
def test_both_people_require_valid_numeric_place_ids(monkeypatch, invalid):
    auth(monkeypatch)
    for person in ("person_a", "person_b"):
        payload = body()
        payload[person]["place_id"] = invalid
        response = call(payload)
        assert response.status == 400
        assert json.loads(response.text)["error"] == "invalid_input"


def test_role_revocation_mid_compute_cannot_leak_partner_chart(monkeypatch):
    role = auth(monkeypatch)
    places(monkeypatch)
    def revoke(first, second):
        role["enabled"] = False
        return {"schema_version": "astro.synastry-facts.v1", "aspects": []}
    monkeypatch.setattr(api, "build_full_synastry_facts", revoke)
    with pytest.raises(web.HTTPForbidden):
        call(body())


def test_missing_geo_db_or_jpl_fails_closed(monkeypatch):
    auth(monkeypatch)
    monkeypatch.setattr(api, "get_place", lambda _: (_ for _ in ()).throw(
        AstroPlacesUnavailable("private db")))
    response = call(body())
    assert response.status == 503
    assert "private" not in response.text
    places(monkeypatch)
    monkeypatch.setattr(api, "build_full_synastry_facts", lambda *_: (
        _ for _ in ()).throw(AstroChartUnavailable("secret kernel path")))
    response = call(body())
    assert response.status == 503
    assert "secret" not in response.text


def test_full_synastry_route_exists_without_affecting_legacy_compatibility():
    from bot.astro_api import setup_astro_routes
    app = web.Application()
    setup_astro_routes(app, "/mini-app")
    routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
    assert ("POST", "/mini-app/api/astro/compatibility/full") in routes
    assert ("POST", "/mini-app/api/astro/compatibility") in routes
