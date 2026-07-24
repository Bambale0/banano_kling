from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services import lava_invoice_compat as compat
from bot.services import lava_payment_safety as safety
from bot.services.lava_service import LavaService, lava_service


@pytest.mark.asyncio
async def test_create_invoice_accepts_id_without_contract_id(monkeypatch):
    async def fake_create(self, *args, **kwargs):
        return {
            "ok": True,
            "id": "invoice-1",
            "paymentUrl": "https://pay.example/invoice-1",
            "status": "new",
        }

    monkeypatch.setattr(LavaService, "create_invoice", fake_create)

    response = await compat._create_invoice_compatible(
        email="customer@example.org",
        offer_id="offer-1",
    )

    assert response["ok"] is True
    assert response["id"] == "invoice-1"
    assert "contractId" not in response


@pytest.mark.asyncio
async def test_create_invoice_saves_mapping_when_contract_id_is_present(monkeypatch):
    saved = []

    async def fake_create(self, *args, **kwargs):
        return {
            "ok": True,
            "id": "invoice-1",
            "contractId": "contract-1",
            "paymentUrl": "https://pay.example/invoice-1",
        }

    async def fake_save(contract_id, invoice_id):
        saved.append((contract_id, invoice_id))

    monkeypatch.setattr(LavaService, "create_invoice", fake_create)
    monkeypatch.setattr(safety, "_save_binding", fake_save)

    response = await compat._create_invoice_compatible(
        email="customer@example.org",
        offer_id="offer-1",
    )

    assert response["ok"] is True
    assert saved == [("contract-1", "invoice-1")]


@pytest.mark.asyncio
async def test_transaction_normalizer_replaces_contract_with_invoice(monkeypatch):
    async def original(*, payment_id, provider, order_id):
        return {
            "payment_id": payment_id,
            "provider": provider,
            "order_id": order_id,
        }

    async def fake_mapping(identifier):
        return "invoice-1" if identifier == "contract-1" else None

    monkeypatch.setattr(safety, "_invoice_id_for_contract", fake_mapping)
    wrapped = compat._make_transaction_normalizer(original)

    result = await wrapped(
        payment_id="contract-1",
        provider="lava",
        order_id="order-1",
    )

    assert result["payment_id"] == "invoice-1"


@pytest.mark.asyncio
async def test_lookup_discovers_invoice_id_before_retrying(monkeypatch):
    transaction = SimpleNamespace(order_id="order-1")
    calls = []

    async def original_lookup(*, contract_id, order_id):
        calls.append((contract_id, order_id))
        return transaction if len(calls) == 2 else None

    async def fake_discover(contract_id):
        assert contract_id == "contract-1"
        return "invoice-1"

    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", fake_discover)
    wrapped = compat._make_lookup_with_discovery(original_lookup)

    result = await wrapped(contract_id="contract-1", order_id=None)

    assert result is transaction
    assert calls == [("contract-1", None), ("contract-1", None)]


@pytest.mark.asyncio
async def test_provider_status_queries_invoice_id_before_webhook_contract(monkeypatch):
    requested = []
    saved = []

    async def fake_get_invoice(identifier):
        requested.append(identifier)
        return {
            "ok": True,
            "id": "invoice-1",
            "contractId": "contract-1",
            "status": "completed",
        }

    async def fake_save(contract_id, invoice_id):
        saved.append((contract_id, invoice_id))

    monkeypatch.setattr(lava_service, "get_invoice", fake_get_invoice)
    monkeypatch.setattr(safety, "_save_binding", fake_save)

    transaction = SimpleNamespace(payment_id="invoice-1")
    status, invoice_id = await compat._provider_status_compatible(
        transaction,
        contract_id="contract-1",
        retry_delays=(0.0,),
    )

    assert status == "completed"
    assert invoice_id == "invoice-1"
    assert requested == ["invoice-1"]
    assert saved == [("contract-1", "invoice-1")]
