#!/usr/bin/env python3
"""Seven-service HTTP contract smoke using real GeoNames + JPL data.

Only signed Telegram identity is substituted with an ephemeral in-process
test principal, never a production token/user. All 7 handlers, routing, location
lookup, time calculation, JSON response and status codes are exercised unchanged.
"""

import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import astro_api, miniapp
from bot.config import config


async def main() -> None:
    async def test_actor(_app, init_data):
        if init_data != "fixture-signed-test-only":
            raise ValueError("invalid signature fixture")
        return 10000001, {"platform": "telegram"}

    app = web.Application()
    astro_api.setup_astro_routes(app, "/mini-app")
    common = {
        "date": "29.02.2000",
        "time": "13:45",
        "place_id": 498817,
    }
    examples = {
        "natal/full": {**common},
        "compatibility": {
            "person_a": {"date": "29.02.2000", "time": "13:45", "timezone": "Europe/Moscow"},
            "person_b": {"date": "02.06.2001", "time": "11:30", "timezone": "Europe/Berlin"},
        },
        "karma": {**common},
        "year": {**common, "period": "2028"},
        "month": {**common, "period": "2028-02"},
        "solar": {**common, "period": "2028", "return_place_id": 2950159},
        "lunar": {"period": "2028-02", "timezone": "Europe/Moscow"},
    }
    expected_schema = {
        "natal/full": "astro.natal-facts.v1",
        "compatibility": "astro.synastry.facts.v1",
        "karma": "astro.karma-indicators.v1",
        "year": "astro.transit-snapshots.v1",
        "month": "astro.transit-snapshots.v1",
        "solar": "astro.solar-facts.v1",
    }
    with (
        patch.object(miniapp, "_get_user_context", test_actor),
        patch.object(config, "is_admin", lambda actor: actor == 10000001),
    ):
        async with TestClient(TestServer(app)) as client:
            for service, payload in examples.items():
                url = "/mini-app/api/astro/" + service
                anonymous = await client.post(url, json=payload)
                assert anonymous.status == 401, (
                    "Anonymous access", service, anonymous.status,
                )
                await anonymous.release()

                result = await client.post(url, json={
                    **payload, "init_data": "fixture-signed-test-only",
                    "is_admin": True, "latitude": 0.0, "longitude": 0.0,
                })
                data = await result.json()
                assert result.status == 200, (
                    service, result.status, data.get("error"), data.get("message"),
                )
                assert data["ok"] is True, (service, data)
                assert result.headers.get("Cache-Control") == "no-store"
                facts = data.get("result")
                if service in expected_schema:
                    assert facts["schema_version"] == expected_schema[service], service
                if service == "natal/full":
                    assert len(facts["chart"]["cusps"]) == 12
                    assert data["place"]["timezone"] == "Europe/Moscow"
                if service == "karma":
                    assert len(facts["indicators"]) == 4
                if service == "year":
                    assert len(facts["samples"]) == 12
                if service == "month":
                    assert len(facts["samples"]) == 29
                if service == "solar":
                    assert len(facts["solar_chart"]["cusps"]) == 12
                    assert facts["return_location"]["timezone"] == "Europe/Berlin"
                if service == "lunar":
                    assert len(data["days"]) == 29 if "days" in data else len(facts["days"]) == 29
                print("ASTRO_HTTP_SERVICE_OK", service, flush=True)
    print("ASTRO_ALL_SEVEN_SERVICE_HTTP_SMOKE_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
