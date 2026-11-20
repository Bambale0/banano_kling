"""Native web checkout and generation lifecycle safety regressions."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot import db as db_backend
from bot import web_auth, web_commerce, web_generation, web_tasks
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
async def test_native_generation_reserves_atomically_captures_after_delivery(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "4.0000")
    owner, cookie = await account("web-task-paid-owner")
    await WalletService("live").apply(owner, "credit", "9", "web-test-credit-1")
    submit = AsyncMock(return_value=("provider-paid-1", False))
    monkeypatch.setattr(web_generation, "_submit_to_provider", submit)
    check = AsyncMock(return_value=("success", "https://cdn.kie.ai/file.png"))
    monkeypatch.setattr(web_generation, "_provider_check", check)
    from bot import web_media_delivery
    archive = AsyncMock(return_value="https://neuromixbot.com/uploads/web_results/stored.png")
    monkeypatch.setattr(web_media_delivery, "archive_web_result", archive)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    payload = {"model": "flux_pro", "prompt": "A tree in front of mountains",
               "aspect_ratio": "1:1", "request_key": "web-generations-key-2026"}
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json=payload, headers=auth(cookie),
        )
        assert response.status == 202
        result = await response.json()
        repeated = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json=payload, headers=auth(cookie),
        )
        assert repeated.status == 200
        assert (await repeated.json())["task_id"] == result["task_id"]
        assert (await WalletService("live").snapshot(owner))["balance"] == {
            "available": "5.0000", "reserved": "4.0000", "revision": 2,
        }
        assert (await web_generation.run_worker_tick()) == [result["task_id"]]
        assert submit.await_count == 1
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?",
                (result["task_id"],),
            )
            await db.commit()
        assert (await web_generation.run_worker_tick()) == [result["task_id"]]
        assert archive.await_count == 1
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "5.0000"
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "0.0000"
        detail = await client.get(
            "/mini-app/api/web-auth/task/" + result["task_id"], headers=auth(cookie),
        )
        task = (await detail.json())["task"]
        assert task["status"] == "completed"
        assert task["result_url"].endswith("/web_results/stored.png")
        assert await web_generation.run_worker_tick() == []


@pytest.mark.asyncio
async def test_native_generation_failure_returns_reservation_and_never_retries_uncertain_submission(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "5.0000")
    owner, cookie = await account("web-task-failure-owner")
    await WalletService("live").apply(owner, "credit", "6", "web-test-credit-2")
    submit = AsyncMock(return_value=(None, False))
    monkeypatch.setattr(web_generation, "_submit_to_provider", submit)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Another creative prompt",
                  "request_key": "web-uncertain-key-2026"}, headers=auth(cookie),
        )
        assert response.status == 202
        task_id = (await response.json())["task_id"]
        assert await web_generation.run_worker_tick() == [task_id]
        async with db_backend.connect() as db:
            await db.execute(
                "UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?", (task_id,),
            )
            await db.commit()
        assert await web_generation.run_worker_tick() == [task_id]
        assert submit.await_count == 1
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "6.0000"
        assert (await WalletService("live").snapshot(owner))["balance"]["reserved"] == "0.0000"
        detail = await client.get("/mini-app/api/web-auth/task/" + task_id, headers=auth(cookie))
        assert (await detail.json())["task"]["status"] == "failed"


@pytest.mark.asyncio
async def test_native_generation_is_not_authenticatable_by_forged_account_id(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "2.0000")
    owner, cookie = await account("web-forgery-owner")
    await WalletService("live").apply(owner, "credit", "4", "web-test-credit-3")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        unsigned = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Scene", "request_key": "another-web-unique-2026"},
            headers={"Origin": "https://neuromixbot.com"},
        )
        assert unsigned.status == 401
        forged = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Scene", "request_key": "another-web-unique-2026",
                  "telegram_id": 12345, "account_id": "0" * 32},
            headers=auth(cookie),
        )
        assert forged.status == 400
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "4.0000"
        await web_tasks.ensure_web_tasks_schema()
        async with db_backend.connect() as db:
            count = await (await db.execute(
                "SELECT COUNT(*) FROM web_generation_tasks WHERE account_id=?",
                (owner,),
            )).fetchone()
        assert int(count[0]) == 0


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
async def test_native_provider_failure_releases_reservation(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "3.0000")
    owner, cookie = await account("web-native-provider-fail")
    await WalletService("live").apply(owner, "credit", "4", "web-provider-fail-initial")
    monkeypatch.setattr(web_generation, "_submit_to_provider", AsyncMock(
        return_value=("provider-failed-1", False),
    ))
    monkeypatch.setattr(web_generation, "_provider_check", AsyncMock(
        return_value=("fail", None),
    ))
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "v3_std", "prompt": "Moving city scene",
                  "duration": 5, "request_key": "provider-failure-2026"},
            headers=auth(cookie),
        )
        assert response.status == 202
        task_id = (await response.json())["task_id"]
        assert await web_generation.run_worker_tick() == [task_id]
        async with db_backend.connect() as db:
            await db.execute("UPDATE web_generation_tasks SET lease_until_epoch=0 WHERE task_id=?",
                             (task_id,))
            await db.commit()
        assert await web_generation.run_worker_tick() == [task_id]
        balance = (await WalletService("live").snapshot(owner))["balance"]
        assert balance["available"] == "4.0000" and balance["reserved"] == "0.0000"
        task = await client.get("/mini-app/api/web-auth/task/" + task_id, headers=auth(cookie))
        assert (await task.json())["task"]["status"] == "failed"


@pytest.mark.asyncio
async def test_native_capture_recovery_after_crash_is_idempotent(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "5.0000")
    owner, cookie = await account("web-task-capture-crash")
    await WalletService("live").apply(owner, "credit", "7", "web-test-credit-for-crash")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Starlit ocean",
                  "request_key": "recovery-settlement-2026"}, headers=auth(cookie),
        )
        assert response.status == 202
        task_id = (await response.json())["task_id"]
        async with db_backend.connect() as db:
            await db.execute(
                """UPDATE web_generation_tasks SET phase='settling',lease_until_epoch=0,
                   result_url='https://neuromixbot.com/uploads/web_results/recovered.png'
                   WHERE task_id=?""", (task_id,),
            )
            await db.commit()
        # Provider result was durably saved, then ledger captured and process
        # crashed before marking the task completed.
        await WalletService("live").apply(
            owner, "capture", "5.0000", "web:capture:" + task_id,
            reference_key="web:reserve:" + task_id,
        )
        assert await web_generation.run_worker_tick() == [task_id]
        assert await web_generation.run_worker_tick() == []
        detail = await client.get("/mini-app/api/web-auth/task/" + task_id, headers=auth(cookie))
        assert (await detail.json())["task"]["status"] == "completed"
        snapshot = await WalletService("live").snapshot(owner)
        assert snapshot["balance"]["available"] == "2.0000"
        assert snapshot["balance"]["reserved"] == "0.0000"
        captures = [item for item in snapshot["entries"] if item["kind"] == "capture"]
        assert len(captures) == 1


@pytest.mark.asyncio
async def test_web_provider_callback_never_trusts_forged_success(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "2.0000")
    owner, cookie = await account("callback-web-owner")
    await WalletService("live").apply(owner, "credit", "3", "callback-init-credit")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        created = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "A real test picture",
                  "request_key": "callback-test-id-2026"}, headers=auth(cookie),
        )
        task_id = (await created.json())["task_id"]
        async with db_backend.connect() as db:
            await db.execute(
                """UPDATE web_generation_tasks SET phase='provider',
                   provider_task_id='genuine-kie-task',lease_until_epoch=100000
                   WHERE task_id=?""", (task_id,),
            )
            await db.commit()
        uri = "/mini-app/api/web-auth/web-generation/callback"
        rejected = await client.post(uri, params={
            "task_id": task_id, "signature": "0" * 64,
        }, json={"status": "completed", "resultUrl": "https://attacker.com/fake.png"})
        assert rejected.status == 401
        signed = await client.post(uri, params={
            "task_id": task_id, "signature": web_generation._callback_signature(task_id),
        }, json={"status": "completed", "resultUrl": "https://attacker.com/fake.png"})
        assert signed.status == 202
        detail = await client.get("/mini-app/api/web-auth/task/" + task_id, headers=auth(cookie))
        assert (await detail.json())["task"]["status"] == "pending"
        balance = (await WalletService("live").snapshot(owner))["balance"]
        assert balance["available"] == "1.0000" and balance["reserved"] == "2.0000"


def test_web_result_ssrf_and_format_guard(monkeypatch):
    from bot import web_media_delivery

    monkeypatch.setenv("WEB_GENERATION_RESULT_HOSTS", "kie.ai,aiquickdraw.com")
    assert web_media_delivery._trusted_result_url("https://cdn.kie.ai/task.png")
    assert not web_media_delivery._trusted_result_url("https://kie.ai.evil.example/task.png")
    assert not web_media_delivery._trusted_result_url("http://cdn.kie.ai/task.png")
    assert not web_media_delivery._trusted_result_url("https://user@cdn.kie.ai/task.png")
    assert not web_media_delivery._trusted_result_url("https://cdn.kie.ai:abc/task.png")
    assert not web_media_delivery._trusted_result_url("https://127.0.0.1/task.png")
    assert web_media_delivery._media_type(b"\x89PNG\r\n\x1a\n" + b"x" * 16, "image") == (
        "png", "image/png",
    )
    with pytest.raises(ValueError):
        web_media_delivery._media_type(b"<html>bad output</html>", "image")


@pytest.mark.asyncio
async def test_web_reference_upload_is_private_and_snapshotted_before_charge(monkeypatch):
    from aiohttp import FormData

    from bot import web_references

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "is_s3_enabled", lambda: True)
    uploaded = []
    def fake_upload(path, data, *, content_type=None, cache_control=None):
        uploaded.append((path, bytes(data), content_type))
        return "https://neuromixbot.com/uploads/" + path
    monkeypatch.setattr(web_references, "persist_upload_bytes", fake_upload)
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "2.0000")
    owner, cookie = await account("ref-owning-web-account")
    intruder, intruder_cookie = await account("ref-other-web-account")
    await WalletService("live").apply(owner, "credit", "4", "web-ref-test-credit")
    png = b"\x89PNG\r\n\x1a\n" + b"fake-image-content"
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("image", png, filename="photo.png", content_type="image/png")
        created = await client.post(
            "/mini-app/api/web-auth/web-generation/reference",
            data=form, headers=auth(cookie),
        )
        assert created.status == 200, await created.text()
        ref = (await created.json())["reference_id"]
        assert ref.startswith("wr_")
        assert uploaded[0][2] == "image/png"

        # Duplicate upload reuses the same immutable content-owned reference.
        same = FormData()
        same.add_field("image", png, filename="again.png", content_type="image/png")
        duplicate = await client.post(
            "/mini-app/api/web-auth/web-generation/reference", data=same, headers=auth(cookie),
        )
        assert (await duplicate.json())["reference_id"] == ref
        assert len(uploaded) == 1

        exploit = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Portrait on a mountain",
                  "request_key": "stranger-owned-ref-2026", "reference_ids": [ref]},
            headers=auth(intruder_cookie),
        )
        assert exploit.status == 403
        assert (await WalletService("live").snapshot(intruder))["balance"]["reserved"] == "0.0000"
        valid = await client.post(
            "/mini-app/api/web-auth/web-generation/create",
            json={"model": "flux_pro", "prompt": "Portrait on a mountain",
                  "request_key": "own-ref-generation-2026", "reference_ids": [ref]},
            headers=auth(cookie),
        )
        assert valid.status == 202
        task_id = (await valid.json())["task_id"]
        async with db_backend.connect() as db:
            row = await (await db.execute(
                "SELECT request_json FROM web_generation_tasks WHERE task_id=?", (task_id,),
            )).fetchone()
        frozen = json.loads(row[0])
        assert frozen["reference_ids"] == [ref]
        assert frozen["reference_urls"][0].startswith("https://neuromixbot.com/uploads/web_refs/")
        balance = (await WalletService("live").snapshot(owner))["balance"]
        assert balance["available"] == "2.0000" and balance["reserved"] == "2.0000"


@pytest.mark.asyncio
async def test_web_reference_upload_rejects_html_and_unsigned_login(monkeypatch):
    from aiohttp import FormData

    from bot import web_references

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "is_s3_enabled", lambda: True)
    _, cookie = await account("reject-reference-not-image")
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        bad = FormData()
        bad.add_field("image", b"<script>evil</script>",
                      filename="evil.png", content_type="image/png")
        response = await client.post(
            "/mini-app/api/web-auth/web-generation/reference",
            data=bad, headers=auth(cookie),
        )
        assert response.status == 400
        anonymous = FormData()
        anonymous.add_field("image", b"\x89PNG\r\n\x1a\n" + b"fake",
                            filename="real.png", content_type="image/png")
        unauthorized = await client.post(
            "/mini-app/api/web-auth/web-generation/reference",
            data=anonymous, headers={"Origin": "https://neuromixbot.com"},
        )
        assert unauthorized.status == 401


@pytest.mark.asyncio
async def test_same_web_generation_key_concurrent_requests_only_reserve_once(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_generation, "_enabled", lambda: True)
    monkeypatch.setattr(web_generation.config, "KIE_AI_API_KEY", "test-token")
    monkeypatch.setattr(web_generation, "_price", lambda *args: "3.0000")
    owner, cookie = await account("paid-concurrency-test")
    await WalletService("live").apply(owner, "credit", "5", "concurrent-credit")
    payload = {"model": "v3_std", "prompt": "A flying bird in sky",
               "request_key": "parallel-task-creation-2026"}
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        calls = await asyncio.gather(*(
            client.post("/mini-app/api/web-auth/web-generation/create",
                        json=payload, headers=auth(cookie)) for _ in range(3)
        ))
        assert all(call.status in (200, 202) for call in calls)
        tasks = [await call.json() for call in calls]
        assert len({task["task_id"] for task in tasks}) == 1
        balance = (await WalletService("live").snapshot(owner))["balance"]
        assert balance["available"] == "2.0000" and balance["reserved"] == "3.0000"
        async with db_backend.connect() as db:
            row = await (await db.execute(
                "SELECT COUNT(*) FROM web_generation_tasks WHERE account_id=?", (owner,),
            )).fetchone()
        assert int(row[0]) == 1


@pytest.mark.asyncio
async def test_lava_web_order_only_routes_after_original_webhook_auth(monkeypatch):
    from bot.services import lava_payment_safety as safety

    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_commerce, "_enabled", lambda: True)
    monkeypatch.setattr(lava_service, "api_key", "test-key")
    monkeypatch.setattr(web_commerce, "_package", lambda key: (10000, "110", "offer", "Test"))
    monkeypatch.setattr(lava_service, "create_invoice", AsyncMock(return_value={
        "ok": True, "id": "invoice-ingress", "contractId": "contract-ingress",
        "paymentUrl": "https://gate.lava.top/pay/ingress",
    }))
    invoice = {"ok": True, "id": "invoice-ingress", "contractId": "contract-ingress",
               "status": "created", "currency": "RUB", "amount": "100.00"}
    monkeypatch.setattr(lava_service, "get_invoice", AsyncMock(return_value=invoice))
    from bot.config import config
    monkeypatch.setattr(config, "LAVA_WEBHOOK_SECRET", "test-provider-secret-2026")
    owner, cookie = await account("web-provider-webhook-ingress")
    legacy = SimpleNamespace(_extract_first=lambda payload, keys: None)
    async def wrapped(request):
        return await safety.safe_handle_lava_webhook(request, payments_module=legacy)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    app.router.add_post("/lava/webhook", wrapped)
    async with TestClient(TestServer(app)) as client:
        created = await client.post("/mini-app/api/web-auth/web-payments/create",
                                    json={"request_key": "webhook-auth-key-2026",
                                          "package_id": "x", "email": "buyer@example.com"},
                                    headers=auth(cookie))
        assert created.status == 200
        invoice["status"] = "completed"
        payload = {"eventType": "payment.success", "status": "completed",
                   "contractId": "contract-ingress", "amount": "100.00", "currency": "RUB"}
        unauthenticated = await client.post("/lava/webhook", json=payload)
        assert unauthenticated.status == 401
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "0.0000"
        verified = await client.post("/lava/webhook", json=payload,
                                     headers={"X-Api-Key": "test-provider-secret-2026"})
        assert verified.status == 200
        again = await client.post("/lava/webhook", json=payload,
                                   headers={"X-Api-Key": "test-provider-secret-2026"})
        assert again.status == 200
        assert (await WalletService("live").snapshot(owner))["balance"]["available"] == "110.0000"
