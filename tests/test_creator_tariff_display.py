"""Authenticated Mini App pricing stays per viewer and out of shared recipes."""
import inspect
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from bot import creator_tariff_display as display
from bot import miniapp
from bot.handlers import trends_compat


class Request:
    def __init__(self, body=None):
        self.app = {}
        self.body = body or {}

    async def json(self):
        return self.body


async def request_payload(request):
    return await request.json()


@pytest.fixture
def fake_quotes(monkeypatch):
    calls = []

    def quote(model, duration=5, quality=None, video_references=None, *, tariff="standard"):
        calls.append((model, duration, quality, bool(video_references), tariff))
        rate = {"standard": 4, "creator": 1, "admin": 4}[tariff]
        rate *= 2 if quality == "1080p" else 1
        return SimpleNamespace(cost=duration * rate * (2 if video_references else 1))

    monkeypatch.setattr(display, "resolve_video_quote", quote)
    monkeypatch.setattr(display, "video_quality_rates", lambda model, *, tariff="standard": {
        "480p": 0.5 if tariff == "creator" else 2,
        "720p": 1 if tariff == "creator" else 4,
        "1080p": 2 if tariff == "creator" else 8,
    })
    return calls


def test_model_metadata_is_per_viewer_without_mutating_shared_maps(fake_quotes):
    model = {"id": "seedance_2_5", "durations": [-1, 5, 10],
             "costs": {"5": 20}, "quality_costs": {"720p": 4, "1080p": 8}}
    before = deepcopy(model)
    creator = display.price_video_model_metadata(model, tariff="creator")
    ordinary = display.price_video_model_metadata(model)
    assert creator["costs"] == {"-1": 5, "5": 5, "10": 10}
    assert ordinary["costs"] == {"-1": 20, "5": 20, "10": 40}
    assert creator["quality_costs"]["1080p"] == 2
    assert model == before


def test_repeat_descriptor_requotes_viewer_and_preserves_actual_historical_cost(fake_quotes):
    card = {"id": 22, "model": "seedance_2_5", "gen_type": "video", "cost": 99,
            "repeat_reference_slots": {"version": 1, "available": True,
                "pricing_quality": "1080p", "duration_costs": {"5": 999},
                "cost_multiplier": 2,
                "images": [{"index": 0, "role": "reference", "binding": "fixed"}],
                "videos": [{"index": 0, "role": "reference", "binding": "upload"}]}}
    before = deepcopy(card)
    creator = display.price_feed_api_payload({"ok": True, "feed": [card]}, tariff="creator")
    ordinary = display.price_feed_api_payload({"ok": True, "feed_item": card})
    assert creator["feed"][0]["repeat_reference_slots"]["duration_costs"]["5"] == 20
    assert ordinary["feed_item"]["repeat_reference_slots"]["duration_costs"]["5"] == 80
    assert creator["feed"][0]["cost"] == 99
    assert card == before
    assert all(call[2:4] == ("1080p", True) for call in fake_quotes)


@pytest.mark.parametrize("route", ["miniapp_feed", "miniapp_feed_item", "miniapp_feed_like", "miniapp_feed_share"])
async def test_feed_routes_use_authenticated_viewer_not_body_profile(monkeypatch, route):
    card = {"id": 22, "model": "seedance_2_5", "gen_type": "video"}
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(side_effect=request_payload))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(101, {"user": SimpleNamespace(id=7)})))
    for name in ("get_profile_generation_card", "like_feed_generation", "increment_feed_share"):
        monkeypatch.setattr(miniapp, name, AsyncMock(return_value=card))
    monkeypatch.setattr(miniapp, "get_feed_generations", AsyncMock(return_value=[card]))
    from bot.handlers import feed_model_filter_compat
    monkeypatch.setattr(feed_model_filter_compat, "filter_feed_cards", AsyncMock(return_value=[card]))
    monkeypatch.setattr(feed_model_filter_compat, "_published_model_ids", AsyncMock(return_value=["seedance_2_5"]))
    tariff = AsyncMock(return_value="standard")
    monkeypatch.setattr(display, "get_actor_tariff", tariff)
    seen = []
    monkeypatch.setattr(display, "price_feed_api_payload", lambda payload, *, tariff="standard": seen.append(tariff) or payload)
    request = Request({"init_data": "signed", "gen_id": 22, "tariff": "creator", "telegram_id": 999, "pricing_profile": "admin"})
    request.app = {"bot": SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="example_bot")))}
    response = await inspect.unwrap(getattr(miniapp, route))(request)
    assert response.status == 200
    assert seen == ["standard"]
    tariff.assert_awaited_once_with(101)
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("route", ["miniapp_prompts", "miniapp_prompt_detail"])
async def test_trend_prices_use_authenticated_viewer_and_do_not_mutate_recipe(monkeypatch, route):
    from bot import creator_tariff, trend_api

    prompt = {"id": 22, "tags": ["trend"], "status": "approved", "is_public": True}
    monkeypatch.setattr(trends_compat.database, "get_prompts_by_tag", AsyncMock(return_value=[prompt]))
    monkeypatch.setattr(trends_compat.database, "get_prompt_by_id", AsyncMock(return_value=prompt))
    context = SimpleNamespace(
        _miniapp_payload=AsyncMock(side_effect=request_payload),
        _bounded_int=miniapp._bounded_int,
        _get_user_context=AsyncMock(return_value=(101, {"user": SimpleNamespace(id=7)})),
        _miniapp_error_response=miniapp._miniapp_error_response,
        web=web,
    )
    tariff = AsyncMock(return_value="creator")
    monkeypatch.setattr(creator_tariff, "get_actor_tariff", tariff)
    seen = []
    monkeypatch.setattr(trend_api, "with_trend_repeat_cost", lambda prompt, *, tariff="standard": seen.append(tariff) or {**prompt, "repeat_cost": 5})
    trends_compat._install_miniapp_trends(context)
    response = await getattr(context, route)(Request({"init_data": "signed", "prompt_id": 22, "tariff": "admin"}))
    assert response.status == 200
    assert seen == ["creator"]
    tariff.assert_awaited_once_with(101)
    assert "repeat_cost" not in prompt


async def test_installed_bootstrap_prices_both_models_per_actor_without_global_leak(monkeypatch, fake_quotes):
    user = SimpleNamespace(id=7, credits=100, referral_code="SYNTHETIC", channel_url=None)
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(side_effect=request_payload))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(101, {"user": user, "payload": {"user": {"id": 101}}})))
    monkeypatch.setattr(miniapp, "_cached_bot_me", AsyncMock(return_value=SimpleNamespace(username="synthetic_bot")))
    for name in ("_fetch_recent_tasks", "list_saved_references", "get_and_clear_miniapp_notifications"):
        monkeypatch.setattr(miniapp, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(miniapp, "get_partner_overview", AsyncMock(return_value={}))
    monkeypatch.setattr(miniapp, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, "needs_telegram_bot_start", AsyncMock(return_value=False))
    tariff = AsyncMock(side_effect=["creator", "standard"])
    monkeypatch.setattr(display, "get_actor_tariff", tariff)
    shared_before = deepcopy(miniapp.VIDEO_MODELS)

    responses = []
    for _ in range(2):
        response = await miniapp.miniapp_bootstrap(Request({"init_data": "signed", "tariff": "admin", "telegram_id": 999}))
        assert response.status == 200
        assert "no-store" in response.headers["Cache-Control"]
        responses.append(json.loads(response.text))
    for index, rate in enumerate((1, 4)):
        models = {model["id"]: model for model in responses[index]["video_models"]}
        for key in ("seedance_2", "seedance_2_5"):
            assert models[key]["costs"]["5"] == rate * 5
            assert models[key]["quality_duration_costs"]["1080p"]["5"] == rate * 10
        assert responses[index]["is_admin"] is False
    assert miniapp.VIDEO_MODELS == shared_before
    assert [call.args for call in tariff.await_args_list] == [(101,), (101,)]


def test_fractional_rates_keep_exact_server_rounding_and_all_configured_qualities(monkeypatch):
    from bot.services.preset_manager import preset_manager

    config = deepcopy(preset_manager.get_price_config())
    config["costs_reference"]["video_models"]["seedance_2_5"]["quality_costs"]["1080p"] = 9
    config["creator_tariff"] = {"enabled": True, "video_models": {
        "seedance_2": {"quality_costs": {"720p": 1.25}},
        "seedance_2_5": {"quality_costs": {"480p": 1.25, "720p": 1.25, "1080p": 2.25}},
    }}
    monkeypatch.setattr(preset_manager, "_price_config", config)
    result = display.price_video_model_metadata({"id": "seedance_2_5", "durations": [5, 10]}, tariff="creator")
    assert result["quality_costs"]["720p"] == 1.25
    assert result["quality_duration_costs"]["720p"]["5"] == 6
    assert result["quality_duration_costs"]["1080p"]["5"] == 11


async def test_feed_detail_reprices_same_cached_source_for_each_viewer(monkeypatch, fake_quotes):
    source = {"id": 22, "model": "seedance_2_5", "gen_type": "video", "cost": 45,
              "repeat_reference_slots": {"version": 1, "available": True, "cost_multiplier": 2,
                                         "pricing_quality": "720p", "duration_costs": {"5": 40},
                                         "images": [], "videos": [{"index": 0, "role": "reference", "binding": "fixed"}]}}
    before = deepcopy(source)
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(side_effect=request_payload))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(101, {"user": SimpleNamespace(id=7)})))
    monkeypatch.setattr(miniapp, "get_profile_generation_card", AsyncMock(return_value=source))
    monkeypatch.setattr(display, "get_actor_tariff", AsyncMock(side_effect=["creator", "standard"]))
    for expected in (10, 40):
        response = await miniapp.miniapp_feed_item(Request({"gen_id": 22, "tariff": "admin"}))
        card = json.loads(response.text)["feed_item"]
        assert card["repeat_reference_slots"]["duration_costs"]["5"] == expected
        assert card["cost"] == 45
    assert source == before


async def test_unauthenticated_feed_detail_never_resolves_personal_prices(monkeypatch):
    monkeypatch.setattr(miniapp, "_miniapp_payload", AsyncMock(side_effect=request_payload))
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(side_effect=web.HTTPUnauthorized()))
    tariff = AsyncMock(return_value="creator")
    monkeypatch.setattr(display, "get_actor_tariff", tariff)
    response = await miniapp.miniapp_feed_item(Request({"gen_id": 22, "telegram_id": 101, "tariff": "creator"}))
    assert response.status == 401
    tariff.assert_not_awaited()
