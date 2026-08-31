import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_lava_foreign_usd_packages_are_configured() -> None:
    config = json.loads(_read("data/price.json"))
    packages = {item["credits"]: item for item in config["packages"]}
    expected = {
        50: (
            "639bf625-d76d-41a2-8e10-c66613d20ee1",
            "61c4022f-18e5-4d8c-bda4-6d3659d77b9d",
        ),
        100: (
            "9df9801c-5c2a-4721-94b4-10651ad7124f",
            "17040120-096e-4d54-807e-1e997854258c",
        ),
        200: (
            "94feb699-912e-4d45-b1ed-e7790e8a8d1a",
            "49e4d77f-6391-438a-b01c-bf70b5d7184e",
        ),
        500: (
            "cb5e3be8-2f65-4730-b3ba-67b7aee65601",
            "faaa883c-a03b-4c00-9c19-e87620eda155",
        ),
    }

    for credits, (product_id, offer_id) in expected.items():
        package = packages[credits]
        assert package["lava_foreign_product_id"] == product_id
        assert package["lava_foreign_offer_id"] == offer_id
        assert package["lava_foreign_currency"] == "USD"
        assert package["price_usd"] > 0


@pytest.mark.asyncio
async def test_dynamic_product_lookup_includes_hidden_lava_products(monkeypatch) -> None:
    from bot.services.lava_service import LavaService

    service = LavaService("test-key")
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_request(method, path, payload=None, params=None):
        calls.append((method, path, params))
        return {
            "ok": True,
            "items": [
                {
                    "data": {
                        "id": "dynamic-product",
                        "offers": [
                            {
                                "id": "rub-offer",
                                "prices": [{"currency": "RUB"}],
                            }
                        ],
                    }
                }
            ],
        }

    monkeypatch.setattr(service, "_request", fake_request)

    resolved = await service.resolve_offer_id_from_product_id(
        product_id="dynamic-product",
        currency="RUB",
    )

    assert resolved == "rub-offer"
    assert calls == [("GET", "/api/v2/products", {"feedVisibility": "ALL"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_method", ["CARD", "SBP"])
async def test_lava_service_can_forward_optional_provider_fields(
    monkeypatch,
    payment_method: str,
) -> None:
    from bot.services.lava_service import LavaService

    service = LavaService("test-key")
    captured: dict = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update(
            {"method": method, "path": path, "payload": payload, "params": params}
        )
        return {"ok": True, "id": "invoice-1", "paymentUrl": "https://pay.lava.test/1"}

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="buyer@gmail.com",
        offer_id="rub-offer",
        currency="RUB",
        amount=100,
        payment_provider="PAY2ME",
        payment_method=payment_method,
        buyer_language="RU",
    )

    assert result["ok"] is True
    assert captured["payload"]["currency"] == "RUB"
    assert captured["payload"]["amount"] == 100.0
    assert captured["payload"]["paymentProvider"] == "PAY2ME"
    assert captured["payload"]["paymentMethod"] == payment_method


@pytest.mark.asyncio
async def test_lava_service_omits_payment_selectors_for_unrestricted_checkout(
    monkeypatch,
) -> None:
    from bot.services.lava_service import LavaService

    service = LavaService("test-key")
    captured: dict = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update(
            {"method": method, "path": path, "payload": payload, "params": params}
        )
        return {"ok": True, "id": "invoice-all", "paymentUrl": "https://pay.lava.test/all"}

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        email="buyer@gmail.com",
        offer_id="rub-offer",
        currency="RUB",
        amount=100,
        buyer_language="RU",
    )

    assert result["ok"] is True
    assert captured["payload"]["currency"] == "RUB"
    assert captured["payload"]["amount"] == 100.0
    assert "paymentProvider" not in captured["payload"]
    assert "paymentMethod" not in captured["payload"]


@pytest.mark.asyncio
async def test_lava_recovers_dynamic_rub_amount_from_miniapp_package_context(
    monkeypatch,
) -> None:
    from bot.services.lava_service import LavaService

    service = LavaService("test-key")
    captured: dict = {}

    async def fake_request(method, path, payload=None, params=None):
        captured.update({"payload": payload})
        return {"ok": True, "id": "invoice-2", "paymentUrl": "https://pay.lava.test/2"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(
        "bot.services.preset_manager.preset_manager.get_package",
        lambda package_id: {"id": package_id, "price_rub": 250},
    )

    result = await service.create_invoice(
        email="buyer@gmail.com",
        offer_id="dynamic-product",
        currency="RUB",
        client_utm={"package_id": "pack_250"},
    )

    assert result["ok"] is True
    assert captured["payload"]["amount"] == 250.0


def test_miniapp_legacy_lava_actions_use_unrestricted_rub_checkout() -> None:
    source = _read("bot/handlers/miniapp_lava_payment_methods_compat.py")
    handlers = _read("bot/handlers/__init__.py")

    assert '"lava_card": ("rub", None, None)' in source
    assert '"lava_sbp": ("rub", None, None)' in source
    assert '"lava_foreign": ("foreign", None, None)' in source
    assert '"lava_foreign_card": ("foreign", "UNLIMIT", "CARD")' in source
    assert '"lava_foreign_paypal": ("foreign", "PAYPAL", None)' in source
    assert "_miniapp_package_lava_foreign_offer_config(package)" in source
    assert '"requested_payment_method": payment_method' in source
    assert "payment_provider=payment_provider" in source
    assert "payment_method=payment_method" in source
    assert "_allow_amount_fallback=False" in source
    assert 'provider="lava"' in source
    assert "freekassa_service.create_payment" not in source
    assert "install_miniapp_lava_payment_methods()" in handlers


def test_miniapp_payment_ui_uses_single_unrestricted_lava_action() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")
    types_source = _read("frontend/miniapp-v0/lib/types.ts")

    assert "handleTopup(pkg.id, 'lava')" in source
    assert "handleTopup(pkg.id, 'lava_card')" not in source
    assert "handleTopup(pkg.id, 'lava_sbp')" not in source
    assert "handleTopup(pkg.id, 'lava_foreign')" in source
    assert "Lava — карта / СБП" in source
    assert "На странице Lava будут показаны доступные способы оплаты" in source
    assert "USD" in source
    assert "PayPal" in source
    assert "'lava'" in types_source
    assert "'lava_card'" in types_source
    assert "'lava_sbp'" in types_source
    assert "'lava_foreign'" in types_source
    assert "'lava_foreign_card'" in types_source
    assert "'lava_foreign_paypal'" in types_source


def test_text_bot_rub_uses_single_unrestricted_lava_checkout() -> None:
    source = _read("bot/handlers/lava_checkout.py")

    assert 'callback_data=f"buy_lava_rub_{package_id}"' in source
    assert 'callback_data=f"buy_lava_sbp_{package_id}"' not in source
    assert 'callback_data=f"buy_lava_card_{package_id}"' not in source
    assert 'return None, "", "Lava — все способы"' in source
    assert 'callback_data=f"buy_lava_foreign_{package_id}"' in source
    assert "Зарубежная оплата и СНГ" in source
    assert "🌍 USD" in source
    assert "PayPal" in source
    assert "_package_lava_foreign_offer_config(package)" in source
    assert 'expected_currency = "USD" if mode in LAVA_CHECKOUT_FOREIGN_MODES else "RUB"' in source
    assert 'callback_data=f"freekassa_sbp_{package_id}"' not in source
    assert "freekassa_service" not in source
    assert "СБП теперь оформляется через KASSA" not in source
    assert "payment_provider=payment_provider" in source
    assert "payment_method=payment_method" in source
    assert "_allow_amount_fallback=False" in source


def test_old_freekassa_callbacks_are_routed_to_lava_checkout() -> None:
    source = _read("bot/handlers/freekassa_payments.py")
    callback_block = source.split(
        "async def initiate_freekassa_payment", 1
    )[1].split("@router.callback_query(F.data.startswith(\"check_freekassa_\"))", 1)[0]

    assert (
        'proxy = _CallbackDataProxy(callback, f"buy_lava_{target_mode}_{package_id}")'
        in callback_block
    )
    assert "await handle_lava_checkout_entry(proxy, state)" in callback_block
    assert "freekassa_service.create_payment" not in callback_block
    assert "provider=\"freekassa\"" not in callback_block
    assert "_checkout_url(" not in callback_block


def test_freekassa_checkout_endpoint_no_longer_creates_payments() -> None:
    source = _read("bot/handlers/freekassa_payments.py")
    checkout_block = source.split("async def handle_freekassa_checkout", 1)[1].split(
        "def _payment_return_page", 1
    )[0]

    assert "status=410" in checkout_block
    assert "freekassa_service.create_payment" not in checkout_block
    assert "HTTPSeeOther" not in checkout_block
    assert "Этот способ оплаты больше не используется" in checkout_block


def test_miniapp_ios_payment_uses_same_window_navigation() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")

    assert "webApp?.platform?.toLowerCase() === 'ios'" in source
    assert "navigator.maxTouchPoints > 1" in source
    ios_branch = source.split("if (isIOSPaymentWebView())", 1)[1].split(
        "const webApp = getTelegramPaymentBridge()", 1
    )[0]
    assert "window.location.assign(url)" in ios_branch
    assert "window.open" not in ios_branch


def test_legacy_lava_route_still_preserves_dynamic_package_context() -> None:
    source = _read("bot/miniapp.py")
    lava_block = source.split('if provider == "lava":', 1)[1].split(
        'if provider != "yookassa":', 1
    )[0]

    assert '"package_id": str(package_id)' in lava_block
    assert "currency=lava_currency" in lava_block
