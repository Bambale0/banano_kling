"""The web catalog is an honest projection of the actual Mini App catalog."""

import pytest

from bot import miniapp, web_generation


def test_every_miniapp_model_is_visible_in_browser_catalog():
    original = {
        item["id"] for item in (*miniapp.IMAGE_MODELS, *miniapp.VIDEO_MODELS)
    }
    browser = {item["id"] for item in web_generation._models()}
    # Public Seedance 2.5 is registered via a Mini App bootstrap extension,
    # not the static VIDEO_MODELS tuple. Include that real provider capability.
    assert browser == original | {"seedance_2_5"}


def test_catalog_does_not_sell_models_without_implemented_provider_adapter():
    for entry in web_generation._models():
        assert isinstance(entry.get("enabled"), bool), entry["id"]
        if not entry["enabled"]:
            assert entry.get("unavailable_reason"), entry["id"]
        else:
            assert entry.get("price") is not None, entry["id"]
            assert entry.get("ratios"), entry["id"]


def test_catalog_reflects_true_model_specific_duration_and_reference_contract():
    by_id = {entry["id"]: entry for entry in web_generation._models()}
    assert 15 in by_id["v3_pro"]["durations"]
    assert 6 in by_id["grok_imagine"]["durations"]
    assert by_id["seedream_55"]["qualities"] == ["1K", "1.5K", "2K"]
    assert by_id["seedream_55"]["max_references"] == 10
    assert by_id["avatar_std"]["requires_audio"] is True


@pytest.mark.parametrize("model_id", [
    "wan_3_prime", "wan_3", "gemini_omni", "avatar_std", "motion_control_v30",
])
def test_complex_model_never_charges_with_wrong_generic_price(model_id):
    # A model without full validation/quote/lifecycle is visible but not
    # purchasable. This is safer than falsely asserting 100% support.
    meta = next(item for item in web_generation._models() if item["id"] == model_id)
    if not meta["enabled"]:
        with pytest.raises(ValueError):
            web_generation._normalize_request({
                "model": model_id, "prompt": "A test prompt",
                "request_key": "sufficiently-unique-123456",
            })


@pytest.mark.asyncio
async def test_server_quote_includes_reference_count_and_rejects_stale_client_price(monkeypatch):
    from types import SimpleNamespace

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import db as db_backend
    from bot import web_auth
    from bot.shared_accounts.wallet import WalletService

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(
        web_generation, "_price",
        lambda media, model, duration, quality=None, reference_count=0: (
            "6.0000" if reference_count else "4.0000"
        ),
    )
    result = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "quote-tested-identity",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = result.cookies["nm_web_session"].value
    owner = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": cookie,
    }))
    await WalletService("live").apply(owner, "credit", "12.0000", "price-quote-credit")
    payload = {"model": "flux_pro", "prompt": "A landscape with mountains",
               "aspect_ratio": "1:1", "request_key": "quote-key-future-2026"}
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    headers = {"Origin": "https://neuromixbot.com",
               "Cookie": "nm_web_session=" + cookie}
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(
            "/mini-app/api/web-auth/web-generation/quote",
            headers=headers, json={key: val for key, val in payload.items() if key != "request_key"},
        )
        assert quote.status == 200
        assert (await quote.json())["price"] == "4.0000"

        changed = await client.post(
            "/mini-app/api/web-auth/web-generation/create", headers=headers,
            json={**payload, "expected_price": "3.0000"},
        )
        assert changed.status == 409
        assert (await changed.json())["code"] == "price_changed"

        accepted = await client.post(
            "/mini-app/api/web-auth/web-generation/create", headers=headers,
            json={**payload, "expected_price": "4.0000"},
        )
        assert accepted.status == 202
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "4.0000"
        async with db_backend.connect() as db:
            row = await (await db.execute(
                "SELECT COUNT(*) FROM web_generation_tasks WHERE account_id=?",
                (owner,),
            )).fetchone()
        assert int(row[0]) == 1


@pytest.mark.asyncio
async def test_unsupported_model_fails_quote_before_money_reservation(monkeypatch):
    from types import SimpleNamespace

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot import web_auth
    from bot.shared_accounts.wallet import WalletService

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    response = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "unsupported-price-test",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = response.cookies["nm_web_session"].value
    owner = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": cookie,
    }))
    await WalletService("live").apply(owner, "credit", "9.0000", "unsupported-credit")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        quote = await client.post(
            "/mini-app/api/web-auth/web-generation/quote",
            headers={"Origin": "https://neuromixbot.com", "Cookie": "nm_web_session=" + cookie},
            json={"model": "wan_3_prime", "prompt": "Some new visual recipe"},
        )
        assert quote.status == 400
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "0.0000"


def test_public_seedance25_extension_is_visible_without_unsafe_web_purchases():
    from bot.model_capabilities import VIDEO_MODEL_CAPABILITIES

    capability = VIDEO_MODEL_CAPABILITIES["seedance_2_5"]
    catalog = {entry["id"]: entry for entry in web_generation._models()}
    exposed = catalog["seedance_2_5"]
    assert exposed["label"] == capability.label
    assert exposed["durations"] == list(capability.durations)
    assert exposed["ratios"] == list(capability.aspect_ratios)
    assert exposed["qualities"] == list(capability.resolutions)
    assert exposed["max_references"] == capability.max_reference_images
    assert exposed["max_video_references"] == capability.max_reference_videos
    assert exposed["max_audio_references"] == capability.max_reference_audio
    assert exposed["enabled"] is False
    assert "Seedance" in exposed["unavailable_reason"]
    with pytest.raises(ValueError, match="Unknown model"):
        web_generation._model_meta("seedance_2_5")
