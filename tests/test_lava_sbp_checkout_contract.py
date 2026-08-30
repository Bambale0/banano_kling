from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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


def test_miniapp_legacy_lava_actions_route_to_freekassa_checkout() -> None:
    source = _read("bot/handlers/miniapp_lava_payment_methods_compat.py")
    handlers = _read("bot/handlers/__init__.py")

    assert '"lava_card": FREEKASSA_CARD_RUB_METHOD_ID' in source
    assert '"lava_sbp": FREEKASSA_SBP_METHOD_ID' in source
    assert "freekassa_service.create_payment" in source
    assert 'provider="freekassa"' in source
    assert "miniapp_module.lava_service.create_invoice" not in source
    assert "install_miniapp_lava_payment_methods()" in handlers


def test_miniapp_payment_ui_has_separate_card_and_sbp_actions() -> None:
    source = _read("frontend/miniapp-v0/components/balance-sheet.tsx")
    types_source = _read("frontend/miniapp-v0/lib/types.ts")

    assert "handleTopup(pkg.id, 'lava_card')" in source
    assert "handleTopup(pkg.id, 'lava_sbp')" in source
    assert "Картой" in source
    assert "СБП" in source
    assert "Карта / СБП" not in source
    assert "'lava_card'" in types_source
    assert "'lava_sbp'" in types_source


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
