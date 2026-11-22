"""Detached web-order regression suite; no production provider calls."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import web_auth, web_commerce
from bot.services.lava_service import lava_service
from bot.shared_accounts.wallet import WalletService


async def account(subject):
    flow = {"mode": "login", "source": None, "destination": "/login"}
    response = await web_auth._complete_identity(SimpleNamespace(), "yandex", subject, flow)
    cookie = response.cookies["nm_web_session"].value
    owner = await web_auth._session_account(SimpleNamespace(cookies={
        "nm_web_session": cookie,
    }))
    return owner, cookie


def auth(cookie):
    return {"Cookie": f"nm_web_session={cookie}", "Origin": "https://neuromixbot.com"}


@pytest.mark.asyncio
async def test_web_checkout_verified_credit_once_and_never_credits_other_account(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda package_id: (
        10000, "110", "offer-test", "Пакет тест",
    ))
    create = AsyncMock(return_value={
        "ok": True, "id": "invoice-test-1", "contractId": "contract-test-1",
        "paymentUrl": "https://gate.lava.top/payment/test",
    })
    invoice = {"ok": True, "id": "invoice-test-1", "contractId": "contract-test-1",
               "amount": "100.00", "currency": "RUB", "status": "created"}
    lookup = AsyncMock(return_value=invoice)
    monkeypatch.setattr(lava_service, "create_invoice", create)
    monkeypatch.setattr(lava_service, "get_invoice", lookup)

    user, cookie = await account("web-checkout-owner")
    another, other_cookie = await account("web-checkout-stranger")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    endpoint = "/mini-app/api/web-auth/web-payments/create"
    body = {"request_key": "checkout-unique-key-2026", "package_id": "p100",
            "email": "buyer@example.com"}
    async with TestClient(TestServer(app)) as client:
        anonymous = await client.post(endpoint, json=body)
        assert anonymous.status == 403  # Origin is not verified.
        attempts = await asyncio.gather(
            client.post(endpoint, json=body, headers=auth(cookie)),
            client.post(endpoint, json=body, headers=auth(cookie)),
        )
        assert all(response.status in (200, 202) for response in attempts)
        orders = [await response.json() for response in attempts]
        assert orders[0]["order_id"] == orders[1]["order_id"]
        assert create.await_count == 1
        assert (await WalletService("live").snapshot(user))["balance"]["available"] == "0.0000"
        inaccessible = await client.get(
            "/mini-app/api/web-auth/web-payments/status",
            params={"order_id": orders[0]["order_id"]},
            headers=auth(other_cookie),
        )
        assert inaccessible.status == 404
        invoice["status"] = "completed"
        callback = {"eventType": "payment.success", "status": "completed",
                    "contractId": "contract-test-1", "amount": "100.00",
                    "currency": "RUB"}
        first = await web_commerce.verified_webhook(callback, "contract-test-1", "payment.success")
        second = await web_commerce.verified_webhook(callback, "contract-test-1", "payment.success")
        assert first.status == second.status == 200
        assert (await WalletService("live").snapshot(user))["balance"]["available"] == "110.0000"
        assert (await WalletService("live").snapshot(another))["balance"]["available"] == "0.0000"
        paid = await client.get(
            "/mini-app/api/web-auth/web-payments/status",
            params={"order_id": orders[0]["order_id"]}, headers=auth(cookie),
        )
        assert (await paid.json())["status"] == "credited"
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_web_checkout_rejects_forged_amount_even_if_provider_reports_paid(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda key: (25000, "270", "offer", "Test"))
    monkeypatch.setattr(lava_service, "create_invoice", AsyncMock(return_value={
        "ok": True, "id": "invoice-2", "contractId": "contract-2",
        "paymentUrl": "https://gate.lava.top/pay/2",
    }))
    invoice = {"ok": True, "id": "invoice-2", "contractId": "contract-2",
               "status": "created", "currency": "RUB", "amount": "250.00"}
    monkeypatch.setattr(lava_service, "get_invoice", AsyncMock(return_value=invoice))
    owner, cookie = await account("forged-amount-owner")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.post(
            "/mini-app/api/web-auth/web-payments/create",
            json={"request_key": "second-checkout-key-2026", "package_id": "250",
                  "email": "buyer@example.com"}, headers=auth(cookie),
        )
        assert result.status == 200
        invoice["status"] = "completed"
        payload = {"eventType": "payment.success", "status": "completed",
                   "contractId": "contract-2", "amount": "1.00", "currency": "RUB"}
        forged = await web_commerce.verified_webhook(payload, "contract-2", "payment.success")
        assert forged.status == 409
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "0.0000"
        # Callback loss and provider proof now recover the valid paid amount.
        results = await web_commerce.reconcile_pending(limit=10)
        assert any(row["action"] == "credited" for row in results)
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "270.0000"


@pytest.mark.asyncio
async def test_payment_recovery_after_invoice_lookup_failure(monkeypatch):
    from bot.services.lava_service import LavaProviderUnavailable

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda key: (9900, "100", "offer", "Test"))
    monkeypatch.setattr(lava_service, "create_invoice", AsyncMock(return_value={
        "ok": True, "id": "invoice-recovery", "contractId": "contract-recovery",
        "paymentUrl": "https://gate.lava.top/pay/recovery",
    }))
    lookup = AsyncMock(side_effect=LavaProviderUnavailable(503))
    monkeypatch.setattr(lava_service, "get_invoice", lookup)
    owner, cookie = await account("web-reconcile-creating")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.post(
            "/mini-app/api/web-auth/web-payments/create",
            json={"request_key": "reconciliation-key-2026", "package_id": "p",
                  "email": "paid@example.com"}, headers=auth(cookie),
        )
        assert result.status == 503
        order_id = (await result.json())["order_id"]
        async with db_backend.connect() as db:
            row = await (await db.execute(
                "SELECT invoice_id,contract_id,status FROM web_payment_orders WHERE order_id=?",
                (order_id,),
            )).fetchone()
        assert tuple(row) == ("invoice-recovery", "contract-recovery", "creating")
        # A release rollback must disable NEW orders, not strand a customer
        # payment that the provider settles after that rollback.
        monkeypatch.setattr(web_commerce, "_enabled", lambda: False)
        lookup.side_effect = None
        lookup.return_value = {
            "ok": True, "id": "invoice-recovery", "contractId": "contract-recovery",
            "amount": "99.00", "currency": "RUB", "status": "created",
        }
        reconciled = await web_commerce.reconcile_pending()
        assert any(x["action"] == "invoice_confirmed" for x in reconciled)
        status = await client.get(
            "/mini-app/api/web-auth/web-payments/status",
            params={"order_id": order_id}, headers=auth(cookie),
        )
        assert (await status.json())["payment_url"] == "https://gate.lava.top/pay/recovery"
        lookup.return_value["status"] = "completed"
        assert any(x["action"] == "credited" for x in await web_commerce.reconcile_pending())
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "100.0000"



@pytest.mark.asyncio
async def test_web_checkout_accepts_invoice_only_response_and_credits_exactly_once(monkeypatch):
    """Real Lava v3 invoices can contain id/paymentUrl with no contractId."""
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "synthetic-test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda _: (
        10000, "110", "offer", "Test package",
    ))
    creation = AsyncMock(return_value={
        "ok": True, "id": "invoice-only-20261122",
        "paymentUrl": "https://gate.lava.top/payment/synthetic",
    })
    detail = {
        "id": "invoice-only-20261122", "status": "in_progress",
        "amount": "100.00", "currency": "RUB",
    }
    monkeypatch.setattr(lava_service, "create_invoice", creation)
    monkeypatch.setattr(lava_service, "get_invoice", AsyncMock(return_value=detail))

    owner, cookie = await account("web-invoice-only-owner-20261122")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        result = await client.post(
            "/mini-app/api/web-auth/web-payments/create",
            json={
                "request_key": "invoice-only-request-20261122",
                "package_id": "test", "email": "paid@example.com",
            },
            headers=auth(cookie),
        )
        payload = await result.json()
        assert result.status == 200, payload
        async with db_backend.connect() as db:
            saved = await (await db.execute(
                "SELECT invoice_id,contract_id,status FROM web_payment_orders "
                "WHERE order_id=?", (payload["order_id"],)
            )).fetchone()
        assert tuple(saved) == (
            "invoice-only-20261122", "invoice-only-20261122", "pending",
        )
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "0.0000"

        detail["status"] = "completed"
        event = {
            "eventType": "payment.success",
            "contractId": "invoice-only-20261122", "amount": "100.00",
            "currency": "RUB", "status": "completed",
        }
        for _ in range(2):
            response = await web_commerce.verified_webhook(
                event, "invoice-only-20261122", "payment.success",
            )
            assert response.status == 200
        assert creation.await_count == 1
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "110.0000"


@pytest.mark.asyncio
async def test_web_invoice_only_outage_persists_identity_for_idempotent_reconciliation(monkeypatch):
    from bot.services.lava_service import LavaProviderUnavailable

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "synthetic-test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda _: (
        9900, "100", "offer", "Test package",
    ))
    create = AsyncMock(return_value={
        "ok": True, "id": "invoice-only-recovery-20261122",
        "paymentUrl": "https://gate.lava.top/payment/synthetic-recovery",
    })
    lookup = AsyncMock(side_effect=LavaProviderUnavailable(503))
    monkeypatch.setattr(lava_service, "create_invoice", create)
    monkeypatch.setattr(lava_service, "get_invoice", lookup)

    owner, cookie = await account("web-invoice-only-recovery-20261122")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    endpoint = "/mini-app/api/web-auth/web-payments/create"
    body = {
        "request_key": "invoice-only-recovery-20261122",
        "package_id": "test", "email": "paid@example.com",
    }
    async with TestClient(TestServer(app)) as client:
        result = await client.post(endpoint, json=body, headers=auth(cookie))
        assert result.status == 503
        result_data = await result.json()
        order_id = result_data["order_id"]
        async with db_backend.connect() as db:
            stored = await (await db.execute(
                "SELECT invoice_id,contract_id,status FROM web_payment_orders "
                "WHERE order_id=?", (order_id,)
            )).fetchone()
        assert tuple(stored) == ("invoice-only-recovery-20261122", None, "creating")
        retry = await client.post(endpoint, json=body, headers=auth(cookie))
        assert retry.status == 202
        assert create.await_count == 1

        lookup.side_effect = None
        lookup.return_value = {
            "ok": True, "id": "invoice-only-recovery-20261122",
            "status": "in_progress", "amount": "99.00", "currency": "RUB",
        }
        reconciled = await web_commerce.reconcile_pending()
        assert any(x["order_id"] == order_id and x["action"] == "invoice_confirmed"
                   for x in reconciled)
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "0.0000"
        lookup.return_value["status"] = "completed"
        assert any(x["order_id"] == order_id and x["action"] == "credited"
                   for x in await web_commerce.reconcile_pending())
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "100.0000"
        assert create.await_count == 1


@pytest.mark.asyncio
async def test_web_invoice_only_rejects_provider_identity_mismatch(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "synthetic-test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda _: (
        10000, "110", "offer", "Test package",
    ))
    monkeypatch.setattr(lava_service, "create_invoice", AsyncMock(return_value={
        "ok": True, "id": "expected-invoice-only",
        "paymentUrl": "https://gate.lava.top/payment/expected",
    }))
    monkeypatch.setattr(lava_service, "get_invoice", AsyncMock(return_value={
        "ok": True, "id": "DIFFERENT-INVOICE", "status": "completed",
        "amount": "100.00", "currency": "RUB",
    }))
    owner, cookie = await account("web-invoice-only-mismatch-20261122")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-payments/create",
            json={
                "request_key": "invoice-only-mismatch-20261122",
                "package_id": "test", "email": "paid@example.com",
            }, headers=auth(cookie),
        )
        assert response.status == 503
    assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "0.0000"
