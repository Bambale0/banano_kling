"""Seedream 5.5 Layers uses one owned input, maximum reserve, settled actual output."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import web_auth, web_generation
from bot.services.seedream55_pricing import image_generation_cost, price_cells
from bot.services.seedream55_service import seedream55_service
from bot.shared_accounts.wallet import WalletService


def test_layers_normalization_and_quote_binds_all_paid_options():
    ref = "wr_" + "a" * 32
    base = {"model": "seedream_55_layers", "request_key": "layer-work-2026-12345",
            "prompt": "Separate the foreground and text",
            "reference_ids": [ref], "quality": "2K",
            "max_images": 5, "output_format": "png", "text_recognition": True}
    normalized = web_generation._normalize_request(base)
    assert normalized["max_images"] == 5
    assert normalized["text_recognition"] is True
    assert normalized["output_format"] == "png"
    assert web_generation._price("image", "seedream_55_layers", 5, "2K", 1, 5) == str(
        Decimal(str(image_generation_cost(
            "seedream_55_layers", "2K", reference_count=1, max_images=5,
        )))
    )
    for changed in (
        {"reference_ids": []}, {"max_images": 101}, {"max_images": 1},
        {"max_images": True}, {"text_recognition": "true"},
        {"output_format": "pdf"}, {"quality": "Ultra"},
    ):
        with pytest.raises(ValueError):
            web_generation._normalize_request({**base, **changed})
    with pytest.raises(ValueError):
        web_generation._normalize_request({**base, "model": "seedream_55"})


@pytest.mark.asyncio
async def test_layers_provider_uses_exact_reserved_output_cap(monkeypatch):
    submit = AsyncMock(return_value={"task_id": "kie-layers-created"})
    monkeypatch.setattr(seedream55_service, "generate_layers", submit)
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "1" * 32,
        {"model": "seedream_55_layers", "prompt": "Separate the character",
         "aspect_ratio": "1:1", "duration": 5,
         "quality": "auto", "max_images": 7, "text_recognition": True,
         "output_format": "png",
         "reference_urls": ["https://neuromixbot.com/uploads/web_refs/verified.png"]},
    )
    assert (task, rejected) == ("kie-layers-created", False)
    assert submit.await_args.kwargs["size"] == "auto"
    assert submit.await_args.kwargs["max_images"] == 7
    assert submit.await_args.kwargs["text_recognition"] is True


@pytest.mark.asyncio
async def test_web_layers_capture_only_actual_outputs_refund_unused_and_replay(monkeypatch):
    from bot import web_layers, web_references

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_references, "owned_reference_urls", AsyncMock(
        return_value=["https://neuromixbot.com/uploads/web_refs/input.png"],
    ))
    provider = AsyncMock(return_value=("kie-layers-id", False))
    monkeypatch.setattr(web_generation, "_submit_to_provider", provider)
    upstream = [
        "https://cdn.kie.ai/layer-1.png",
        "https://cdn.kie.ai/layer-2.png",
        "https://cdn.kie.ai/layer-3.png",
    ]
    monkeypatch.setattr(web_generation, "_provider_check", AsyncMock(
        return_value=("success", upstream),
    ))
    durable = [
        "https://neuromixbot.com/uploads/web_results/layer-1.png",
        "https://neuromixbot.com/uploads/web_results/layer-2.png",
        "https://neuromixbot.com/uploads/web_results/layer-3.png",
    ]
    zip_url = "https://neuromixbot.com/uploads/web_results/all-layers.zip"
    persist = AsyncMock(return_value=(durable, zip_url))
    monkeypatch.setattr(web_layers, "archive_web_layers", persist)
    response = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "layer-refund-test",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = response.cookies["nm_web_session"].value
    account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    await WalletService("live").apply(
        account, "credit", "50", "layers-test-starting-balance",
    )
    original = price_cells()
    reserve = image_generation_cost(
        "seedream_55_layers", "2K", reference_count=1, max_images=5,
    )
    actual = 3 * original["seedream_55_2k"] + original["seedream_55_ref"]
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    headers = {"Origin": "https://neuromixbot.com",
               "Cookie": "nm_web_session=" + cookie}
    async with TestClient(TestServer(app)) as client:
        payload = {
            "model": "seedream_55_layers", "prompt": "Separate characters",
            "reference_ids": ["wr_" + "a" * 32],
            "request_key": "layers-refund-web-2026",
            "quality": "2K", "max_images": 5,
            "output_format": "png", "text_recognition": True,
            "expected_price": str(reserve),
        }
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json=payload, headers=headers,
        )
        assert response.status == 202, await response.text()
        task_id = (await response.json())["task_id"]
        assert (await web_generation.run_worker_tick()) == [task_id]
        async with db_backend.connect() as db:
            await db.execute("UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?", (task_id,))
            await db.commit()
        assert (await web_generation.run_worker_tick()) == [task_id]
        snapshot = await WalletService("live").snapshot(account)
        assert float(snapshot["balance"]["available"]) == pytest.approx(50 - actual)
        assert float(snapshot["balance"]["reserved"]) == 0
        assert len([x for x in snapshot["entries"] if x["kind"] == "capture"]) == 1
        assert len([x for x in snapshot["entries"] if x["kind"] == "release"]) == 1
        task_response = await client.get(
            "/mini-app/api/web-auth/task/" + task_id, headers=headers,
        )
        task = (await task_response.json())["task"]
        assert task["status"] == "completed"
        assert task["bundle_url"] == zip_url
        assert task["output_count"] == 3
        assert float(task["cost"]) == pytest.approx(actual)
        assert len(task["outputs"]) == 3
        assert await web_generation.run_worker_tick() == []
        persist.assert_awaited_once()
