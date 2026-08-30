from bot.handlers.miniapp_lava_payment_methods_compat import _payment_error_message
from bot.services.lava_service import LavaService


def test_payment_error_message_extracts_nested_lava_error() -> None:
    assert (
        _payment_error_message(
            {
                "ok": False,
                "error": {
                    "message": "Lava rejected payment creation",
                },
            }
        )
        == "Lava rejected payment creation"
    )


def test_payment_error_message_falls_back_to_plain_text() -> None:
    assert _payment_error_message(None) == "Failed to create payment"


async def test_lava_invoice_retries_fixed_price_offer_without_amount(monkeypatch) -> None:
    service = LavaService(api_key="test_key", base_url="https://test.lava.top")
    calls = []

    monkeypatch.setattr(
        "bot.services.preset_manager.preset_manager.get_package",
        lambda package_id: {"price_rub": 150} if package_id == "mini" else None,
    )

    async def fake_request(method, path, payload=None, params=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "params": params,
            }
        )
        if len(calls) == 1:
            return {
                "ok": False,
                "status": 400,
                "error": {
                    "message": "Product with offer id = 'offer_1' is not dynamic price"
                },
            }
        return {"ok": True, "id": "inv_1"}

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.create_invoice(
        "test@test.com",
        "offer_1",
        client_utm={"package_id": "mini"},
    )

    assert calls[0]["payload"]["amount"] == 150.0
    assert "amount" not in calls[1]["payload"]
    assert result["id"] == "inv_1"
