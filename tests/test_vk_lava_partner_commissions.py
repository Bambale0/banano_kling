"""VK Lava: linked public checkout settles the intended partner exactly once."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, db as db_backend, miniapp
from bot.handlers import payments, miniapp_regression_safety
from bot.handlers.miniapp_lava_payment_methods_compat import install_miniapp_lava_payment_methods
from bot.partner_commission_settings import set_partner_commission_percent
from bot.services import lava_payment_safety, lava_invoice_compat
from bot.shared_accounts.auth import VerifiedIdentity
from bot.shared_accounts.policy import save_policy
from bot.shared_accounts.store import create_session


class FakeLava:
    enabled = True

    async def create_invoice(self, **kwargs):
        return {"ok": True, "invoiceId": "vk-invoice-one",
                "paymentUrl": "https://example.test/pay"}

    def extract_invoice_id(self, payload):
        return payload.get("invoiceId")

    def extract_payment_url(self, payload):
        return payload.get("paymentUrl")

    def webhook_event_type(self, payload):
        return payload.get("eventType")

    def webhook_status(self, payload):
        return payload.get("status")

    def webhook_contract_id(self, payload):
        return payload.get("contractId")

    async def get_invoice(self, invoice_id):
        assert invoice_id == "vk-invoice-one"
        return {"invoiceId": invoice_id, "status": "paid"}


async def _linked_token(telegram_id, vk_id):
    policy = await save_policy(
        999999999, {"enabled": True, "vk_app_id": 54880352, "vk_admin_ids": []}, 0
    )
    tg, _, _ = await create_session(
        VerifiedIdentity("telegram", telegram_id), 3600, policy.revision
    )
    vk, _, _ = await create_session(
        VerifiedIdentity("vk", vk_id), 3600, policy.revision
    )
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE shared_account_identities SET account_id = ? "
            "WHERE platform = 'vk' AND external_id = ?",
            (tg.id, vk_id),
        )
        await db.execute(
            "UPDATE shared_accounts SET status = 'merged', merged_into = ? WHERE id = ?",
            (tg.id, vk.id),
        )
        await db.commit()
    _, token, _ = await create_session(
        VerifiedIdentity("vk", vk_id), 3600, policy.revision
    )
    return token


@pytest.mark.asyncio
async def test_verified_vk_lava_credits_existing_partner_once(isolated_database, monkeypatch):
    partner = await database.get_or_create_user(910011)
    buyer = await database.get_or_create_user(910012)
    async with db_backend.connect() as db:
        await db.execute(
            "UPDATE users SET referred_by = ? WHERE id = ?", (partner.id, buyer.id)
        )
        await db.commit()
    await set_partner_commission_percent(
        999999999, partner.telegram_id, 40, expected_revision=0
    )
    token = await _linked_token(buyer.telegram_id, 8877123)

    fake = FakeLava()
    monkeypatch.setattr(miniapp, "lava_service", fake)
    monkeypatch.setattr(lava_payment_safety, "lava_service", fake)
    monkeypatch.setattr(lava_invoice_compat, "lava_service", fake)
    monkeypatch.setattr(miniapp, "_miniapp_package_lava_offer_config",
                        lambda _: ("offer-one", "RUB"))
    monkeypatch.setattr(miniapp.preset_manager, "get_package",
                        lambda _: {"id": "vk-test", "credits": 100,
                                   "name": "Test", "price_rub": 1000})
    monkeypatch.setattr(
        miniapp_regression_safety, "_save_payment_email",
        AsyncMock(return_value="buyer@example.test")
    )
    install_miniapp_lava_payment_methods()

    request = SimpleNamespace(
        json=AsyncMock(return_value={
            "provider": "lava_card", "package_id": "vk-test",
            "init_data": "vk_session:" + token,
            "customer_email": "buyer@example.test",
        }),
        app={},
    )
    response = await miniapp.miniapp_create_payment(request)
    data = json.loads(response.text)
    assert response.status == 200, data
    assert data["provider"] == "lava_card"

    async with db_backend.connect() as db:
        row = await (await db.execute(
            "SELECT level1_overrides_json FROM partner_payment_terms WHERE order_id = ?",
            (data["order_id"],)
        )).fetchone()
        assert row and json.loads(row[0])[str(partner.telegram_id)] == 40

    # The mocked provider confirms success; endpoint authorization has
    # separate regression coverage. No real Lava charge is performed.
    await lava_payment_safety._save_binding(data["payment_id"], data["payment_id"])
    assert await lava_payment_safety._invoice_id_for_contract(data["payment_id"]) == data["payment_id"]
    monkeypatch.setattr(lava_payment_safety, "_auth_configuration_present",
                        lambda: True)
    monkeypatch.setattr(lava_payment_safety, "_verify_configured_auth",
                        lambda _: True)
    event = {
        "eventType": "payment.success",
        "contractId": data["payment_id"],
        "status": "paid",
        "amount": 1000,
        "currency": "RUB",
    }
    callback = SimpleNamespace(
        read=AsyncMock(return_value=json.dumps(event).encode()),
        headers={}, remote="127.0.0.1", app={},
    )
    first = await lava_payment_safety.safe_handle_lava_webhook(
        callback, payments_module=payments
    )
    second = await lava_payment_safety.safe_handle_lava_webhook(
        callback, payments_module=payments
    )
    assert first.status == second.status == 200

    final_partner = await database.get_or_create_user(partner.telegram_id)
    final_buyer = await database.get_or_create_user(buyer.telegram_id)
    assert final_partner.partner_balance_rub == 400
    assert final_buyer.credits == buyer.credits + 100
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT amount_rub, percent, level FROM partner_commissions "
            "WHERE order_id = ?", (data["order_id"],)
        )).fetchall()
        assert len(rows) == 1
        assert float(rows[0][0]) == 400
        assert float(rows[0][1]) == 40
        assert int(rows[0][2]) == 1



@pytest.mark.asyncio
async def test_two_vk_lava_checkout_requests_same_millisecond_create_distinct_orders(
    isolated_database, monkeypatch
):
    """Two paid invoices must never share one local order/partner payout."""
    buyer = await database.get_or_create_user(920012)
    token = await _linked_token(buyer.telegram_id, 8877456)
    fake = FakeLava()
    fake.create_invoice = AsyncMock(side_effect=[
        {"ok": True, "invoiceId": "invoice-A", "paymentUrl": "https://example.test/a"},
        {"ok": True, "invoiceId": "invoice-B", "paymentUrl": "https://example.test/b"},
    ])
    monkeypatch.setattr(miniapp, "lava_service", fake)
    monkeypatch.setattr(miniapp, "_miniapp_package_lava_offer_config",
                        lambda _: ("offer-one", "RUB"))
    monkeypatch.setattr(miniapp.preset_manager, "get_package",
                        lambda _: {"id": "vk-test", "credits": 100,
                                   "name": "Test", "price_rub": 1000})
    monkeypatch.setattr(
        miniapp_regression_safety, "_save_payment_email",
        AsyncMock(return_value="buyer@example.test")
    )
    monkeypatch.setattr(miniapp.time, "time", lambda: 1234567.0)
    install_miniapp_lava_payment_methods()

    req = SimpleNamespace(
        json=AsyncMock(return_value={
            "provider": "lava_card",
            "package_id": "vk-test",
            "init_data": "vk_session:" + token,
            "customer_email": "buyer@example.test",
        }),
        app={},
    )
    first = await miniapp.miniapp_create_payment(req)
    second = await miniapp.miniapp_create_payment(req)
    data1, data2 = json.loads(first.text), json.loads(second.text)
    assert first.status == second.status == 200, (data1, data2)
    assert data1["order_id"] != data2["order_id"]
    async with db_backend.connect() as db:
        rows = await (await db.execute(
            "SELECT order_id FROM transactions WHERE payment_id IN (?, ?)",
            ("invoice-A", "invoice-B")
        )).fetchall()
        assert len(rows) == 2
