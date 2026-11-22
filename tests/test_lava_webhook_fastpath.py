"""Regression coverage for Lava webhook invoice lookup latency.

Provider lookup by the persisted payment ID is the fast path. Historical
contract-only identifiers still use invoice-list discovery after a true 404.
None of these tests changes payment state or credits.
"""
from types import SimpleNamespace

import pytest

from bot.services import lava_payment_safety as safety
from bot.services.lava_service import LavaProviderUnavailable, lava_service


def _transaction(payment_id: str = "existing-invoice"):
    return SimpleNamespace(payment_id=payment_id)


@pytest.mark.asyncio
async def test_webhook_checks_existing_invoice_before_any_paginated_discovery(monkeypatch):
    calls = []

    async def no_binding(_contract):
        return None

    async def no_discovery(_contract):
        pytest.fail("invoice list must not be scanned when direct GET succeeds")

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        return {"id": invoice_id, "status": "failed"}

    monkeypatch.setattr(safety, "_invoice_id_for_contract", no_binding)
    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", no_discovery)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    status, bound_id = await safety._provider_status(
        _transaction(), contract_id="existing-invoice", retry_delays=(0.0,)
    )
    assert (status, bound_id) == ("failed", None)
    assert calls == ["existing-invoice"]


@pytest.mark.asyncio
async def test_missing_direct_invoice_falls_back_once_to_legacy_list_discovery(monkeypatch):
    calls = []
    discoveries = []

    async def no_binding(_contract):
        return None

    async def discover(contract):
        discoveries.append(contract)
        return "resolved-invoice"

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        if invoice_id == "legacy-contract":
            return None  # provider GET /invoices/{contract} returned 404
        assert invoice_id == "resolved-invoice"
        return {"id": invoice_id, "status": "completed"}

    monkeypatch.setattr(safety, "_invoice_id_for_contract", no_binding)
    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", discover)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    status, bound_id = await safety._provider_status(
        _transaction("legacy-contract"),
        contract_id="legacy-contract",
        retry_delays=(0.0, 0.0),
    )
    assert (status, bound_id) == ("completed", "resolved-invoice")
    assert calls == ["legacy-contract", "resolved-invoice"]
    assert discoveries == ["legacy-contract"]


@pytest.mark.asyncio
async def test_known_binding_prevents_extra_catalog_lookup(monkeypatch):
    calls = []

    async def bound(_contract):
        return "stored-invoice"

    async def no_discovery(_contract):
        pytest.fail("stored invoice does not require paginated discovery")

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        return {"id": invoice_id, "status": "paid"}

    monkeypatch.setattr(safety, "_invoice_id_for_contract", bound)
    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", no_discovery)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    assert await safety._provider_status(
        _transaction("legacy-contract"),
        contract_id="legacy-contract",
        retry_delays=(0.0,),
    ) == ("paid", "stored-invoice")
    assert calls == ["stored-invoice"]


@pytest.mark.asyncio
async def test_provider_outage_does_not_become_missing_invoice_or_discovery(monkeypatch):
    async def no_binding(_contract):
        return None

    async def no_discovery(_contract):
        pytest.fail("provider outage is not evidence of missing invoice")

    async def unavailable(_invoice_id):
        raise LavaProviderUnavailable(503)

    monkeypatch.setattr(safety, "_invoice_id_for_contract", no_binding)
    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", no_discovery)
    monkeypatch.setattr(lava_service, "get_invoice", unavailable)

    with pytest.raises(LavaProviderUnavailable):
        await safety._provider_status(
            _transaction(), contract_id="existing-invoice", retry_delays=(0.0,)
        )


@pytest.mark.asyncio
async def test_in_progress_provider_status_retries_with_no_invoice_list_scan(monkeypatch):
    calls = []

    async def no_binding(_contract):
        return None

    async def no_discovery(_contract):
        pytest.fail("pending invoice must not trigger catalogue search")

    async def get_invoice(invoice_id):
        calls.append(invoice_id)
        return {"id": invoice_id, "status": (
            "in_progress" if len(calls) == 1 else "completed"
        )}

    monkeypatch.setattr(safety, "_invoice_id_for_contract", no_binding)
    monkeypatch.setattr(safety, "_discover_invoice_id_by_contract", no_discovery)
    monkeypatch.setattr(lava_service, "get_invoice", get_invoice)

    assert await safety._provider_status(
        _transaction(), contract_id="existing-invoice",
        retry_delays=(0.0, 0.0),
    ) == ("completed", None)
    assert calls == ["existing-invoice", "existing-invoice"]


# In production bot.handlers installs lava_invoice_compat, replacing safety's
# provider-status function. Exercise that actual callback implementation too.

@pytest.mark.asyncio
async def test_active_compat_uses_direct_invoice_before_catalog(monkeypatch):
    from bot.services import lava_invoice_compat as compat

    calls = []

    async def no_list(_transaction):
        pytest.fail("active compatibility handler must not scan invoice list")

    async def direct(invoice_id):
        calls.append(invoice_id)
        return {"id": invoice_id, "status": "failed"}

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", direct)

    status, invoice_id = await compat._provider_status_compatible(
        _transaction("real-invoice"), contract_id="real-invoice",
        retry_delays=(0.0,),
    )
    assert (status, invoice_id) == ("failed", "real-invoice")
    assert calls == ["real-invoice"]


@pytest.mark.asyncio
async def test_active_compat_falls_back_to_list_only_after_direct_404(monkeypatch):
    from bot.services import lava_invoice_compat as compat

    calls = []
    scanned = []

    async def missing(invoice_id):
        calls.append(invoice_id)
        return None

    async def from_catalog(transaction):
        scanned.append(transaction.payment_id)
        return {"id": transaction.payment_id, "status": "completed"}

    monkeypatch.setattr(compat, "_list_verified_invoice", from_catalog)
    monkeypatch.setattr(lava_service, "get_invoice", missing)

    assert await compat._provider_status_compatible(
        _transaction("missing-details"), contract_id="missing-details",
        retry_delays=(0.0,),
    ) == ("completed", "missing-details")
    assert calls == ["missing-details"]
    assert scanned == ["missing-details"]


@pytest.mark.asyncio
async def test_active_compat_never_rescans_list_on_retries(monkeypatch):
    from bot.services import lava_invoice_compat as compat

    calls = []
    scans = []

    async def missing(invoice_id):
        calls.append(invoice_id)
        return None

    async def not_in_catalog(transaction):
        scans.append(transaction.payment_id)
        return None

    async def no_binding(_contract):
        return None

    monkeypatch.setattr(compat, "_list_verified_invoice", not_in_catalog)
    monkeypatch.setattr(compat.safety, "_invoice_id_for_contract", no_binding)
    monkeypatch.setattr(lava_service, "get_invoice", missing)

    assert await compat._provider_status_compatible(
        _transaction("missing-details"), contract_id="missing-details",
        retry_delays=(0.0, 0.0),
    ) == ("", None)
    assert calls == ["missing-details", "missing-details"]
    assert scans == ["missing-details"]


@pytest.mark.asyncio
async def test_active_compat_outage_does_not_scan_catalog_or_settle(monkeypatch):
    from bot.services import lava_invoice_compat as compat

    async def no_list(_transaction):
        pytest.fail("HTTP 503 is not a missing invoice")

    async def outage(_invoice_id):
        raise LavaProviderUnavailable(503)

    monkeypatch.setattr(compat, "_list_verified_invoice", no_list)
    monkeypatch.setattr(lava_service, "get_invoice", outage)

    with pytest.raises(LavaProviderUnavailable):
        await compat._provider_status_compatible(
            _transaction("real-invoice"), contract_id="real-invoice",
            retry_delays=(0.0,),
        )
