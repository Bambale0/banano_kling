from __future__ import annotations

import pytest
from aiohttp import web

from bot import wan3_prime_api
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor


class Request:
    def __init__(self, body):
        self._body = body
        self.headers = {}
        self.app = web.Application()

    async def json(self):
        return dict(self._body)


class Quote:
    quote_hash = "quotehash"
    reserve_credits = 4
    requested_output_seconds = 5
    billable_seconds_reserved = 5
    input_video_seconds = 0
    price_configured = True
    admin_free = False

    def as_response(self):
        return {"quotehash": self.quote_hash, "reserve_amount": 4}


class Lifecycle:
    def __init__(self):
        self.launch_calls = 0

    async def quote(self, actor, body):
        self.actor = actor
        self.body = body
        return Quote()

    async def launch(self, actor, body, quote, idempotency_key):
        self.launch_calls += 1
        self.idempotency_key = idempotency_key
        return {
            "task_id": "wan3_abc",
            "internal_task_id": "wan3_abc",
            "status": "submitted",
            "reserve_amount": 4,
        }


def test_setup_wan3_prime_routes_registers_owned_paths():
    app = web.Application()
    wan3_prime_api.setup_wan3_prime_routes(app, "/mini-app")

    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/mini-app/api/wan3/quote" in paths
    assert "/mini-app/api/wan3/generate" in paths
    assert "/mini-app/api/wan3/recipe" in paths
    assert "/mini-app/api/wan3/callback" in paths
    assert "/mini-app/api/wan3/upload/complete" in paths


@pytest.mark.asyncio
async def test_miniapp_generate_wan_quoteonly_and_launch_use_owned_lifecycle(monkeypatch):
    lifecycle = Lifecycle()
    monkeypatch.setattr(wan3_prime_api, "wan3_prime_lifecycle", lifecycle)

    async def actor_from_request(request, body):
        return Wan3PrimeActor(user_id=7, telegram_id=77, is_admin=False)

    monkeypatch.setattr(wan3_prime_api, "_actor_from_request", actor_from_request)

    quote_response = await wan3_prime_api.miniapp_generate_wan(
        Request({"quoteOnly": True, "recipe": {"prompt": "x", "scenario": "text"}})
    )
    assert quote_response.status == 200
    assert lifecycle.launch_calls == 0

    launch_response = await wan3_prime_api.miniapp_generate_wan(
        Request({"idempotency_key": "idem", "quote_hash": "quotehash", "recipe": {"prompt": "x", "scenario": "text"}})
    )
    assert launch_response.status == 200
    assert lifecycle.launch_calls == 1
    assert lifecycle.idempotency_key == "idem"
