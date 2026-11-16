"""Real offline GeoNames/JPL synastry HTTP smoke with a synthetic admin actor."""

import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import miniapp
from bot.astro_api import setup_astro_routes
from bot.config import config


async def main():
    async def test_actor(app, init_data):
        assert init_data == "synthetic-signed-fixture"
        return 101, {"platform": "telegram"}

    app = web.Application()
    setup_astro_routes(app, "/mini-app")
    url = "/mini-app/api/astro/compatibility/full"
    payload = {"person_a": {"date": "29.02.2000", "time": "13:45", "place_id": 498817},
               "person_b": {"date": "02.06.2001", "time": "11:30", "place_id": 2950159}}
    with (patch.object(miniapp, "_get_user_context", test_actor),
          patch.object(config, "is_admin", lambda user: user == 101)):
        async with TestClient(TestServer(app)) as client:
            anon = await client.post(url, json=payload)
            assert anon.status == 401
            await anon.release()
            result = await client.post(url, json={
                **payload, "init_data": "synthetic-signed-fixture",
                "latitude": 0, "timezone": "UTC", "is_admin": True,
            })
            facts = await result.json()
            assert result.status == 200, (result.status, facts.get("error"))
            assert facts["result"]["schema_version"] == "astro.synastry-facts.v1"
            assert len(facts["result"]["house_overlays"]["first_in_second"]) == 12
            assert len(facts["result"]["house_overlays"]["second_in_first"]) == 12
            assert result.headers["Cache-Control"] == "no-store"
    print("ASTRO_FULL_SYNASTRY_HTTP_OK anon=401 admin=200 overlays=12x2")


if __name__ == "__main__":
    asyncio.run(main())
