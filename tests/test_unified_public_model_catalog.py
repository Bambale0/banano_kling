"""Independent browser catalogue is a read-only projection of native models.

No duplicate provider list, no fake Telegram ID and no price authority.
"""
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import miniapp, web_auth
from bot.handlers import generation
from bot.model_catalog_service import native_model_metadata, public_browser_catalog


def test_native_catalog_builder_is_source_based_and_preserves_live_inputs(monkeypatch):
    monkeypatch.setattr(
        miniapp.creator_tariff_display, "price_image_model_metadata",
        lambda item, *, tariff: {**item, "tariff": tariff},
    )
    monkeypatch.setattr(
        miniapp.creator_tariff_display, "price_video_model_metadata",
        lambda item, *, tariff: {**item, "tariff": tariff},
    )
    models = native_model_metadata(tariff="standard", is_admin=False)
    assert {v["id"] for v in models["image_models"]} == {
        v["id"] for v in miniapp.IMAGE_MODELS
    }
    assert {v["id"] for v in models["video_models"]} == {
        v["id"] for v in miniapp.VIDEO_MODELS
    } | ({"kling_4"} if native_model_metadata.__globals__["kling4_public_enabled"]() else set())
    assert all(v["tariff"] == "standard" for v in models["image_models"])
    assert all(v["tariff"] == "standard" for v in models["video_models"]
               if v["id"] != "kling_4")


def test_public_catalog_resolves_public_seedance25_extension_from_real_registration(monkeypatch):
    from bot.handlers import seedance_25_fullstack

    monkeypatch.setattr(generation, "_seedance_25_public_release_installed", True,
                        raising=False)
    if not hasattr(seedance_25_fullstack, "_seedance25_model_meta_original"):
        monkeypatch.setattr(seedance_25_fullstack,
                            "_seedance25_model_meta_original",
                            seedance_25_fullstack._seedance25_model_meta,
                            raising=False)
    catalog = public_browser_catalog()
    images = {v["id"] for v in catalog["image_models"]}
    videos = {v["id"]: v for v in catalog["video_models"]}
    assert images == {v["id"] for v in miniapp.IMAGE_MODELS}
    assert set(videos) >= {v["id"] for v in miniapp.VIDEO_MODELS}
    entry = videos["seedance_2_5"]
    assert entry["label"].find("Seedance 2.5") >= 0
    assert entry["durations"][0] == -1
    assert entry["max_image_references"] == 30
    assert entry["max_video_references"] == 10
    assert entry["max_audio_references"] == 10
    assert entry["seedance25_resolutions"] == ["480p", "720p"]
    assert entry["web_generate_enabled"] is False
    assert entry["available_in_telegram"] is True
    for v in catalog["image_models"] + catalog["video_models"]:
        assert "cost" not in v
        assert "costs" not in v
        assert "quality_costs" not in v
        assert "omni_audio_cost" not in v
        assert "telegram_id" not in v
        assert v["web_generate_enabled"] is False


def test_public_catalog_excludes_admin_only_dynamic_models(monkeypatch):
    from bot import model_catalog_service
    monkeypatch.setattr(model_catalog_service, "kling4_public_enabled", lambda: False)
    catalog = public_browser_catalog()
    assert "kling_4" not in {v["id"] for v in catalog["video_models"]}
    monkeypatch.setattr(model_catalog_service, "kling4_public_enabled", lambda: True)
    catalog = public_browser_catalog()
    assert "kling_4" in {v["id"] for v in catalog["video_models"]}


@pytest.mark.asyncio
async def test_browser_catalog_route_requires_verified_unrevoked_web_session(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    session = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "model-catalog-web-only",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = session.cookies["nm_web_session"].value
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.get("/mini-app/api/web-auth/catalog")
        assert anonymous.status == 401
        ready = await client.get("/mini-app/api/web-auth/catalog", headers={
            "Cookie": "nm_web_session=" + cookie,
        })
        assert ready.status == 200, await ready.text()
        payload = await ready.json()
        assert payload["ok"] is True
        assert payload["catalog_scope"] == "read_only"
        assert payload["web_generate_enabled"] is False
        assert len(payload["image_models"]) == len(miniapp.IMAGE_MODELS)
        assert ready.headers["Cache-Control"] == "no-store"
        logout = await client.post("/mini-app/api/web-auth/logout", headers={
            "Cookie": "nm_web_session=" + cookie,
            "Origin": "https://neuromixbot.com",
        })
        assert logout.status == 200
        revoked = await client.get("/mini-app/api/web-auth/catalog", headers={
            "Cookie": "nm_web_session=" + cookie,
        })
        assert revoked.status == 401


def test_shared_native_catalog_remains_byte_for_byte_equal_to_prior_model_metadata(monkeypatch):
    from bot.creator_tariff_display import (
        price_image_model_metadata,
        price_video_model_metadata,
    )

    native = native_model_metadata(tariff="standard", is_admin=False)
    images = [
        price_image_model_metadata(miniapp._runtime_image_model_metadata(item),
                                   tariff="standard")
        for item in miniapp.IMAGE_MODELS
    ]
    videos = [
        price_video_model_metadata({
            **item,
            "costs": {
                str(duration): miniapp.preset_manager.get_video_cost(
                    item["id"], duration,
                ) for duration in item["durations"]
            },
            "quality_costs": miniapp.preset_manager.get_video_quality_costs(item["id"]),
            **({
                "omni_audio_cost": miniapp.preset_manager.get_video_cost("gemini_omni_audio", 6),
                "omni_character_cost": miniapp.preset_manager.get_video_cost(
                    "gemini_omni_character", 6,
                ),
            } if item["id"] == "gemini_omni" else {}),
        }, tariff="standard")
        for item in miniapp.VIDEO_MODELS
    ]
    assert native["image_models"] == images
    assert native["video_models"][:len(videos)] == videos
