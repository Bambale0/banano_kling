import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from bot.handlers import robokassa_payments as handlers
from bot.services.robokassa_service import RobokassaService


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("ROBOKASSA_MERCHANT_LOGIN", "test-shop")
    monkeypatch.setenv("ROBOKASSA_PASSWORD1", "synthetic-password-1")
    monkeypatch.setenv("ROBOKASSA_PASSWORD2", "synthetic-password-2")
    monkeypatch.setenv("ROBOKASSA_RECEIPT_TAX", "none")
    result = RobokassaService()
    monkeypatch.setattr(handlers, "robokassa_service", result)
    return result


def decoded_receipt(url):
    query = parse_qs(urlparse(url).query)
    return json.loads(unquote(query["Receipt"][0]))


@pytest.mark.parametrize("tax", ["none", ""])
async def test_miniapp_receipt_and_config_guard(service, tax):
    service.receipt_tax = tax
    module = SimpleNamespace(
        _get_user_context=AsyncMock(return_value=(1, {"user": SimpleNamespace(id=7)})),
        preset_manager=SimpleNamespace(get_package=Mock(return_value={
            "name": "Старт", "credits": 25, "price_rub": "250.01",
        })),
        total_package_credits=Mock(return_value=30),
        create_transaction=AsyncMock(return_value=True),
    )
    response = await handlers._create_robokassa_miniapp_checkout(
        SimpleNamespace(app={}), {"package_id": "start"}, module,
    )
    if not tax:
        assert response.status == 503
        module.create_transaction.assert_not_awaited()
        return
    assert response.status == 200
    body = json.loads(response.text)
    item = decoded_receipt(body["payment_url"])["items"][0]
    assert item == {
        "name": "Пополнение баланса NEUROMIX для генерации изображений и видео, 30 кредитов",
        "quantity": 1, "sum": 250.01, "tax": "none",
    }
    assert module.create_transaction.await_args.kwargs["credits"] == 30


@pytest.mark.parametrize("tax", ["none", ""])
async def test_telegram_receipt_and_config_guard(monkeypatch, service, tax):
    service.receipt_tax = tax
    callback = SimpleNamespace(
        data="buy_robokassa_start", from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(edit_text=AsyncMock()), answer=AsyncMock(),
    )
    monkeypatch.setattr(handlers.preset_manager, "get_package", Mock(return_value={
        "name": "Старт", "credits": 25, "price_rub": "250.01",
    }))
    monkeypatch.setattr(handlers, "_get_selected_promo", AsyncMock(return_value=None))
    monkeypatch.setattr(handlers, "package_bonus_credits", Mock(return_value=5))
    monkeypatch.setattr(handlers, "_promo_bonus_for_package", Mock(return_value=0))
    monkeypatch.setattr(handlers, "total_package_credits", Mock(return_value=30))
    monkeypatch.setattr(handlers, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=7)))
    create = AsyncMock(return_value=True)
    monkeypatch.setattr(handlers, "create_transaction", create)
    await handlers.initiate_robokassa_payment(callback, SimpleNamespace())
    if not tax:
        create.assert_not_awaited()
        callback.answer.assert_awaited_once()
        return
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    urls = [button.url for row in markup.inline_keyboard for button in row if button.url]
    item = decoded_receipt(urls[0])["items"][0]
    assert item["name"].endswith("30 кредитов")
    assert item["sum"] == 250.01
    assert item["quantity"] == 1
