"""The quote and launch handshake must validate the same complete references."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from bot import miniapp, trend_api
from bot.creator_tariff import resolve_video_quote


@pytest.mark.asyncio
@pytest.mark.parametrize("quote_only", [True, False])
@pytest.mark.parametrize("missing", ["fixed", "user"])
async def test_trend_missing_media_blocks_before_quote_or_debit(
    tmp_path, monkeypatch, quote_only, missing, caplog
):
    monkeypatch.chdir(tmp_path)
    user_url = "/uploads/refs/image/3210/identity.png"
    fixed_url = "/uploads/trend-assets/image/hidden-template.png"
    for key, url in (("user", user_url), ("fixed", fixed_url)):
        if key != missing:
            path = Path("static" + url)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"valid-local-file")
    prompt = {
        "id": 77,
        "status": "approved",
        "is_public": True,
        "tags": ["trend"],
        "model": "seedance_2_5",
        "prompt_text": "Use @Image1 with @Image2.",
        "generation_settings": {
            "kind": "video",
            "user_input": "photo",
            "model": "seedance_2_5",
            "ratio": "9:16",
            "duration": 8,
            "seedance25_resolution": "720p",
            "reference_contract": "seedance_identity_first",
            "reference_plan_version": 2,
            "reference_slots": [
                {"media_type": "image", "position": 1, "label": "Your photo"}
            ],
            "fixed_image_reference_count": 1,
        },
    }
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(3210, {"user": SimpleNamespace(id=9, credits=500)})),
    )
    monkeypatch.setattr(trend_api, "get_prompt_by_id", AsyncMock(return_value=prompt))
    monkeypatch.setattr(
        trend_api,
        "list_trend_reference_assets",
        AsyncMock(
            return_value=[
                {
                    "media_type": "image",
                    "position": 2,
                    "file_url": fixed_url,
                }
            ]
        ),
    )
    quote = AsyncMock(return_value=resolve_video_quote("seedance_2_5", 8, "720p", []))
    debit = AsyncMock()
    launch = AsyncMock(
        return_value=web.json_response({"ok": True, "task_id": "synthetic"})
    )
    monkeypatch.setattr(trend_api, "_quote_trend_video", quote)
    monkeypatch.setattr(trend_api, "_debit_for_generation", debit)
    monkeypatch.setattr(trend_api, "_run_video_trend", launch)

    class Request:
        def __init__(self):
            self.app = {}

        async def json(self):
            return {
                "init_data": "synthetic",
                "trend_id": 77,
                "pricing_quote_only": quote_only,
                "reference_urls": [user_url],
                "reference_inputs": [
                    {"media_type": "image", "position": 1, "url": user_url}
                ],
            }

    response = await trend_api.miniapp_run_trend(Request())
    assert response.status == 400, response.text
    payload = json.loads(response.text)
    assert payload["code"] == (
        "missing_trend_reference" if missing == "fixed" else "missing_user_reference"
    )
    assert user_url not in response.text
    assert fixed_url not in response.text
    assert "77" in caplog.text
    assert fixed_url not in caplog.text
    quote.assert_not_awaited()
    debit.assert_not_awaited()
    launch.assert_not_awaited()
