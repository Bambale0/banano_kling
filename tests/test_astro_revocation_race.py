"""Admin role revocation during asynchronous calculations must fail closed."""

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web

from bot import astro_api, miniapp


@pytest.mark.parametrize(
    ("handler", "builder", "body"),
    [
        ("astro_lunar_calendar", "build_lunar_calendar", {"period": "2024-03", "timezone": "UTC"}),
        ("astro_natal_facts", "build_natal_facts", {"date": "20.03.2000", "time": "12:00", "timezone": "UTC"}),
        ("astro_compatibility_facts", "build_compatibility_facts", {"person_a": {}, "person_b": {}}),
    ],
)
def test_revoked_while_calculating_never_receives_result(monkeypatch, handler, builder, body):
    current = {"admin": True}
    checks = []

    def is_admin(uid):
        checks.append((uid, current["admin"]))
        return uid == 101 and current["admin"]

    async def get_context(app, init_data):
        assert init_data == "signed-init-data"
        return 101, {"platform": "telegram"}

    def calculate(*args, **kwargs):
        # Simulate the role being revoked while awaiting a worker thread.
        current["admin"] = False
        return {"birth_time_known": True}

    monkeypatch.setattr(astro_api.config, "is_admin", is_admin)
    monkeypatch.setattr(miniapp, "_get_user_context", get_context)
    monkeypatch.setattr(astro_api, builder, calculate)

    async def payload():
        return {**body, "init_data": "signed-init-data"}

    request = SimpleNamespace(app={}, content_length=None, json=payload)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(getattr(astro_api, handler)(request))

    assert checks == [(101, True), (101, False)]
