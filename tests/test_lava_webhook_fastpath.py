"""Regression tests for the *installed* Lava invoice verification handler.

bot.handlers installs lava_invoice_compat._provider_status_compatible over
the base safety helper. These tests intentionally call the active function;
none of them creates invoices or mutates payment balances.
"""
from types import SimpleNamespace

import pytest

from bot.services import lava_invoice_compat as compat
from bot.services.lava_service import LavaProviderUnavailable, lava_service


def _transaction(payment_id: str = "existing-invoice"):
    return SimpleNamespace(payment_id=payment_id)


@pytest.mark.asyncio
async def test_direct_invoice_get_precedes_account_catalog(monkeypatch):
    calls = []

    async def no_list(_transaction):
        pytest.fail("invoice catalog must not be fetched for an existing invoice")

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        return {"id": invoice_id, "status": "failed"}

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    result = await compat._provider_status_compatible(
        _transaction(), contract_id="existing-invoice", retry_delays=(0.0,)
    )
    assert result == ("failed", "existing-invoice")
    assert calls == ["existing-invoice"]


@pytest.mark.asyncio
async def test_missing_direct_invoice_falls_back_to_verified_legacy_list(monkeypatch):
    calls = []
    list_calls = []

    async def missing(invoice_id):
        calls.append(invoice_id)
        return None

    async def from_list(transaction):
        list_calls.append(transaction.payment_id)
        return {"id": transaction.payment_id, "status": "completed"}

    monkeypatch.setattr(lava_service, "get_invoice", missing)
    monkeypatch.setattr(compat, "_list_verified_invoice", from_list)

    result = await compat._provider_status_compatible(
        _transaction("legacy"), contract_id="legacy", retry_delays=(0.0,)
    )
    assert result == ("completed", "legacy")
    assert calls == ["legacy"]
    assert list_calls == ["legacy"]


@pytest.mark.asyncio
async def test_missing_invoice_scans_historical_list_only_once_across_retries(monkeypatch):
    calls = []
    list_calls = []

    async def missing(invoice_id):
        calls.append(invoice_id)
        return None

    async def from_list(transaction):
        list_calls.append(transaction.payment_id)
        return None

    async def no_binding(_contract):
        return None

    monkeypatch.setattr(lava_service, "get_invoice", missing)
    monkeypatch.setattr(compat, "_list_verified_invoice", from_list)
    monkeypatch.setattr(compat.safety, "_invoice_id_for_contract", no_binding)

    result = await compat._provider_status_compatible(
        _transaction("legacy"), contract_id="legacy",
        retry_delays=(0.0, 0.0),
    )
    assert result == ("", None)
    assert calls == ["legacy", "legacy"]
    assert list_calls == ["legacy"]


@pytest.mark.asyncio
async def test_upstream_outage_propagates_without_list_scan(monkeypatch):
    async def no_list(_transaction):
        pytest.fail("provider outage must never trigger catalog discovery")

    async def unavailable(_invoice_id):
        raise LavaProviderUnavailable(503)

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", unavailable)

    with pytest.raises(LavaProviderUnavailable):
        await compat._provider_status_compatible(
            _transaction(), contract_id="existing-invoice",
            retry_delays=(0.0,),
        )


@pytest.mark.asyncio
async def test_in_progress_invoice_retries_without_catalog_scan(monkeypatch):
    calls = []

    async def no_list(_transaction):
        pytest.fail("in-progress invoice must not be rediscovered")

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        return {
            "id": invoice_id,
            "status": "in_progress" if len(calls) == 1 else "completed",
        }

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    result = await compat._provider_status_compatible(
        _transaction(), contract_id="existing-invoice",
        retry_delays=(0.0, 0.0),
    )
    assert result == ("completed", "existing-invoice")
    assert calls == ["existing-invoice", "existing-invoice"]


@pytest.mark.asyncio
async def test_verified_direct_invoice_can_bind_a_distinct_legacy_contract(monkeypatch):
    bindings = []

    async def no_list(_transaction):
        pytest.fail("verified direct GET does not need list scanning")

    async def get_invoice(invoice_id):
        assert invoice_id == "stored-invoice"
        return {"id": invoice_id, "status": "paid"}

    async def save_binding(contract_id, invoice_id):
        bindings.append((contract_id, invoice_id))

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)
    monkeypatch.setattr(compat.safety, "_save_binding", save_binding)

    result = await compat._provider_status_compatible(
        _transaction("stored-invoice"), contract_id="legacy-contract",
        retry_delays=(0.0,),
    )
    assert result == ("paid", "stored-invoice")
    assert bindings == [("legacy-contract", "stored-invoice")]
