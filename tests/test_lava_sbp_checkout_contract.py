from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.lava_service import LavaService


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_dynamic_product_lookup_includes_hidden_lava_products(monkeypatch) -> None:
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
async def test_lava_rub_invoice_keeps_dynamic_amount_and_hosted_checkout(monkeypatch) -> None:
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
        buyer_language="RU",
    )

    assert result["ok"] is True
    assert captured["payload"]["currency"] == "RUB"
    assert captured["payload"]["amount"] == 100.0
    # Lava hosted checkout chooses Card / SBP for RUB; forcing a provider here
    # would remove that choice and can make SBP disappear.
    assert "paymentMethod" not in captured["payload"]
    assert "paymentProvider" not in captured["payload"]


@pytest.mark.asyncio
async def test_lava_recovers_dynamic_rub_amount_from_miniapp_package_context(
    monkeypatch,
) -> None:
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


def test_miniapp_preserves_package_context_for_lava_dynamic_price() -> None:
    source = _read("bot/miniapp.py")
    lava_block = source.split('if provider == "lava":', 1)[1].split(
        'if provider != "yookassa":', 1
    )[0]

    assert '"package_id": str(package_id)' in lava_block
    assert "currency=lava_currency" in lava_block
