"""Regression for Lava's invoice-list fallback when detail lookup returns 404."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot.services import lava_invoice_compat as compat
from bot.services.lava_service import LavaProviderUnavailable, lava_service


INV1 = "11111111-1111-4111-8111-111111111111"
INV2 = "22222222-2222-4222-8222-222222222222"


def tx(payment_id=INV1, amount_rub=500):
    return SimpleNamespace(
        payment_id=payment_id,
        amount_rub=amount_rub,
        order_id="order-1",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_reconciles_verified_completed_from_list_without_detail_404(monkeypatch):
    calls = []

    async def provider(method, path, params=None):
        calls.append((method, path, params))
        return {
            "ok": True, "total": 1, "items": [
                {"id": INV1, "status": "COMPLETED",
                 "receipt": {"amount": 500, "currency": "RUB"}}
            ],
        }

    async def broken_detail(identifier):
        pytest.fail("Verified listing must avoid broken detail endpoint")

    monkeypatch.setattr(lava_service, "_request", provider)
    monkeypatch.setattr(lava_service, "get_invoice", broken_detail)
    compat._clear_lava_invoice_list_cache()
    status, resolved = await compat._provider_status_compatible(
        tx(), contract_id=INV1, retry_delays=(0.0,)
    )
    assert (status, resolved) == ("completed", INV1)
    assert len(calls) == 1
    assert calls[0][1] == "/api/v2/invoices"
    assert calls[0][2]["page"] == 1


@pytest.mark.asyncio
async def test_mismatched_amount_never_confirms_invoice(monkeypatch):
    async def provider(method, path, params=None):
        return {"ok": True, "total": 1, "items": [
            {"id": INV1, "status": "COMPLETED",
             "receipt": {"amount": 499, "currency": "RUB"}},
        ]}

    async def detail(identifier):
        return None

    monkeypatch.setattr(lava_service, "_request", provider)
    monkeypatch.setattr(lava_service, "get_invoice", detail)
    compat._clear_lava_invoice_list_cache()
    status, _ = await compat._provider_status_compatible(
        tx(), contract_id=INV1, retry_delays=(0.0,)
    )
    assert status == ""


@pytest.mark.asyncio
async def test_bounded_paginated_list_is_cached_across_transactions(monkeypatch):
    calls = []

    async def provider(method, path, params=None):
        calls.append(params["page"])
        if params["page"] == 1:
            return {"ok": True, "total": 2, "items": [
                {"id": INV1, "status": "IN_PROGRESS",
                 "receipt": {"amount": 500, "currency": "RUB"}},
                {"id": INV2, "status": "FAILED",
                 "receipt": {"amount": 500, "currency": "RUB"}},
            ]}
        pytest.fail("Unexpected extra API page")

    monkeypatch.setattr(lava_service, "_request", provider)
    compat._clear_lava_invoice_list_cache()
    first = await compat._list_verified_invoice(tx(INV1))
    second = await compat._list_verified_invoice(tx(INV2))
    assert first["status"] == "in_progress"
    assert second["status"] == "failed"
    assert calls == [1]


@pytest.mark.asyncio
async def test_network_failure_fails_closed_without_partial_cache(monkeypatch):
    async def provider(method, path, params=None):
        return {"ok": False, "status": 503, "error": "provider outage"}

    monkeypatch.setattr(lava_service, "_request", provider)
    compat._clear_lava_invoice_list_cache()
    with pytest.raises(LavaProviderUnavailable):
        await compat._list_verified_invoice(tx())


@pytest.mark.asyncio
async def test_legacy_transaction_skips_new_list_strategy(monkeypatch):
    calls = []

    async def provider(method, path, params=None):
        calls.append(path)
        return {"ok": True, "total": 0, "items": []}

    monkeypatch.setattr(lava_service, "_request", provider)
    compat._clear_lava_invoice_list_cache()
    old = tx()
    old.created_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert await compat._list_verified_invoice(old) is None
    assert calls == []
