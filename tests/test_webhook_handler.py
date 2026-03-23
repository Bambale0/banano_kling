import asyncio
import hashlib
import hmac
import json

import pytest
from aiohttp import web

from bot.config import config
from bot.main import handle_kling_webhook


@pytest.mark.asyncio
async def test_handle_kling_webhook_signature_ok(monkeypatch):
    # Prepare a minimal successful payload
    payload = {
        "id": "task123",
        "status": "succeeded",
        "output": "https://x.example/out.mp4",
    }
    body = json.dumps(payload).encode("utf-8")

    secret = "testsecret"
    monkeypatch.setenv("REPLICATE_WEBHOOK_SECRET", secret)
    # monkeypatch config to pick up secret
    monkeypatch.setattr(config, "REPLICATE_WEBHOOK_SECRET", secret)

    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Build a lightweight fake request object with just the attributes the handler uses
    class FakeReq:
        def __init__(self, body, headers):
            self._body = body
            self.headers = headers

        async def read(self):
            return self._body

    req = FakeReq(body, {"x-replicate-signature": sig})

    resp = await handle_kling_webhook(req)
    assert resp.status == 200
