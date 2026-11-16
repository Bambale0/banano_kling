#!/usr/bin/env python3
"""Offline aiohttp integration smoke with genuine GeoNames and JPL DE440.

Only identity and admin authorization are replaced with an ephemeral test actor.
The chart engine, JSON encoder, routes and city lookup are the actual app code.
No Telegram token, real user account, DB write, or payment is used.
"""

import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import astro_api, miniapp
from bot.config import config


async def main() -> None:
    async def demo_actor(_app, init_data):
        if init_data != "test-only-signed-fixture":
            raise ValueError("Invalid fixture")
        return 101, {"platform": "telegram"}

    app = web.Application()
    astro_api.setup_astro_routes(app, "/mini-app")
    with (
        patch.object(miniapp, "_get_user_context", demo_actor),
        patch.object(config, "is_admin", lambda actor: actor == 101),
    ):
        async with TestClient(TestServer(app)) as client:
            path = "/mini-app/api/astro/natal/full"
            anonymous = await client.post(path, json={
                "date": "29.02.2000", "time": "13:45", "place_id": 498817,
            })
            assert anonymous.status == 401
            await anonymous.release()

            response = await client.post(path, json={
                "init_data": "test-only-signed-fixture",
                "date": "29.02.2000",
                "time": "13:45",
                "place_id": 498817,
                # Deliberately malicious client fields: must be ignored.
                "latitude": 0,
                "longitude": 0,
                "timezone": "UTC",
                "is_admin": True,
            })
            result = await response.json()
            assert response.status == 200, (response.status, result.get("error"))
            assert result["ok"] is True
            assert response.headers["Cache-Control"] == "no-store"
            facts = result["result"]
            assert facts["schema_version"] == "astro.natal-facts.v1"
            chart = facts["chart"]
            assert len(chart["cusps"]) == 12
            assert chart["angles"] and len(chart["bodies"]) == 12
            assert result["place"]["timezone"] == "Europe/Moscow"
            assert chart["tz"] == "Europe/Moscow"
            assert all(type(item.get("applying")) is bool for item in chart["aspects"]
                       if "applying" in item)
            print(
                "ASTRO_FULL_NATAL_HTTP_SMOKE_OK "
                "anonymous=401 test_admin=200 houses=12 json=valid "
                "timezone=Europe/Moscow forged_coords=ignored",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
