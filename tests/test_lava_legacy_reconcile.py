from __future__ import annotations

import pytest

from scripts import reconcile_lava_legacy_payments as reconcile


def _candidate(*, status: str = "pending") -> reconcile.Candidate:
    return reconcile.Candidate(
        order_id="123_456_start",
        payment_id="legacy-invoice-id",
        local_status=status,
        created_at="2026-07-24T10:00:00",
        amount_rub=250.0,
        credits=25,
    )


def test_normalize_statuses_deduplicates_and_rejects_unknown():
    assert reconcile.normalize_statuses(["Pending", "failed", "pending"]) == (
        "pending",
        "failed",
    )

    with pytest.raises(ValueError, match="Unsupported local statuses"):
        reconcile.normalize_statuses(["mystery"])


@pytest.mark.asyncio
async def test_dry_run_reports_contract_id_and_paid_action(monkeypatch):
    async def fake_get_invoice(payment_id: str):
        assert payment_id == "legacy-invoice-id"
        return {"contractId": "contract-123", "status": "completed"}

    monkeypatch.setattr(reconcile.lava_service, "get_invoice", fake_get_invoice)

    result = await reconcile.reconcile_candidate(
        _candidate(),
        apply=False,
        complete_paid=True,
    )

    assert result.contract_id == "contract-123"
    assert result.provider_status == "completed"
    assert result.action == "dry_run:update_payment_id+complete_paid"


@pytest.mark.asyncio
async def test_apply_updates_reference_and_completes_failed_payment(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_get_invoice(payment_id: str):
        return {"data": {"contractId": "contract-123", "status": "paid"}}

    async def fake_replace(candidate, contract_id: str):
        calls.append(("replace", contract_id))
        return True

    async def fake_restore(candidate):
        calls.append(("restore", candidate.local_status))
        return True

    async def fake_complete(order_id: str):
        calls.append(("complete", order_id))
        return {"ok": True, "already_completed": False}

    monkeypatch.setattr(reconcile.lava_service, "get_invoice", fake_get_invoice)
    monkeypatch.setattr(reconcile, "replace_payment_reference", fake_replace)
    monkeypatch.setattr(reconcile, "restore_failed_to_pending", fake_restore)
    monkeypatch.setattr(reconcile, "complete_payment_atomic", fake_complete)

    result = await reconcile.reconcile_candidate(
        _candidate(status="failed"),
        apply=True,
        complete_paid=True,
    )

    assert result.action == "completed"
    assert calls == [
        ("replace", "contract-123"),
        ("restore", "failed"),
        ("complete", "123_456_start"),
    ]


@pytest.mark.asyncio
async def test_unresolved_invoice_does_not_touch_database(monkeypatch):
    async def fake_get_invoice(payment_id: str):
        return None

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("database mutation must not run")

    monkeypatch.setattr(reconcile.lava_service, "get_invoice", fake_get_invoice)
    monkeypatch.setattr(reconcile, "replace_payment_reference", fail_if_called)
    monkeypatch.setattr(reconcile, "restore_failed_to_pending", fail_if_called)
    monkeypatch.setattr(reconcile, "complete_payment_atomic", fail_if_called)

    result = await reconcile.reconcile_candidate(
        _candidate(),
        apply=True,
        complete_paid=True,
    )

    assert result.action == "unresolved"
    assert result.provider_status == "lookup_failed"


@pytest.mark.asyncio
async def test_already_completed_atomic_result_is_idempotent(monkeypatch):
    async def fake_get_invoice(payment_id: str):
        return {"contractId": "contract-123", "status": "completed"}

    async def fake_replace(candidate, contract_id: str):
        return True

    async def fake_restore(candidate):
        return True

    async def fake_complete(order_id: str):
        return {"ok": True, "already_completed": True}

    monkeypatch.setattr(reconcile.lava_service, "get_invoice", fake_get_invoice)
    monkeypatch.setattr(reconcile, "replace_payment_reference", fake_replace)
    monkeypatch.setattr(reconcile, "restore_failed_to_pending", fake_restore)
    monkeypatch.setattr(reconcile, "complete_payment_atomic", fake_complete)

    result = await reconcile.reconcile_candidate(
        _candidate(),
        apply=True,
        complete_paid=True,
    )

    assert result.action == "already_completed"
