import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from bot import internal_admin_api as base_api
from bot import internal_admin_payments as payments
from bot import internal_admin_tariffs as tariffs
from bot.internal_admin_dispatch import _AuthenticatedBody
from bot.internal_admin_user_commands import CommandValidationError


def payment_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 9,
        "order_id": "order-9",
        "payment_id": "external-9",
        "provider": "yookassa",
        "status": "pending",
        "user_id": 3,
        "credits": 25,
        "amount_rub": 250.0,
        "promo_code": None,
        "promo_bonus_credits": 0,
        "created_at": "2026-07-11T10:00:00",
        "telegram_id": 123456,
        "username": "igor",
        "first_name": "Igor",
        "last_name": None,
        "user_balance": 12,
    }
    row.update(overrides)
    return row


def command_request(path: str, payload: dict[str, Any]):
    request = make_mocked_request(
        "POST",
        path,
        headers={
            "Idempotency-Key": "payment-command-key-9",
            "X-Admin-User-Id": "admin-user-123",
            "X-Request-Id": "payment-request-9",
        },
    )
    request.match_info["payment_id"] = "9"
    request["internal_body"] = _AuthenticatedBody(
        json.dumps(payload, separators=(",", ":")).encode()
    )
    return request


@pytest.mark.asyncio
async def test_payment_list_uses_parameterized_filters(monkeypatch) -> None:
    request = make_mocked_request(
        "GET",
        "/internal/admin/payments?limit=2&query=igor&status=pending&provider=yookassa&user_id=3",
    )
    captured: dict[str, Any] = {}

    async def fake_fetch_all(sql: str, parameters: tuple[Any, ...] = ()):
        captured["sql"] = sql
        captured["parameters"] = parameters
        return [payment_row()]

    monkeypatch.setattr(base_api, "_fetch_all", fake_fetch_all)
    response = await payments.payments_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["items"][0]["order_id"] == "order-9"
    assert "LOWER(t.status) = ?" in captured["sql"]
    assert "LOWER(t.provider) = ?" in captured["sql"]
    assert captured["parameters"][-4:] == ("pending", "yookassa", 3, 3)


def test_external_state_never_exposes_raw_provider_payload() -> None:
    public = payments._external_state_public(
        {
            "provider": "yookassa",
            "status": "succeeded",
            "paid": True,
            "failed": False,
            "invoice": {"Raw": {"secret": "must-not-leak"}},
        }
    )

    assert public == {
        "provider": "yookassa",
        "provider_status": "succeeded",
        "paid": True,
        "failed": False,
        "error": None,
    }


@pytest.mark.asyncio
async def test_recheck_returns_saved_idempotent_result(monkeypatch) -> None:
    request = command_request(
        "/internal/admin/payments/9/recheck",
        {
            "reason": "support requested status check",
            "confirmation": "RECHECK 9",
        },
    )
    saved = {
        "channel": "telegram",
        "api_version": "1",
        "data": {"payment_id": 9, "provider_status": "succeeded"},
    }

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def rollback(self):
            return None

        async def commit(self):
            return None

    async def reserve(*_args, **_kwargs):
        return saved

    async def fetch(_payment_id: int):
        return payment_row()

    monkeypatch.setattr(payments.db_backend, "connect", lambda: Connection())
    monkeypatch.setattr(payments, "_reserve_command", reserve)
    monkeypatch.setattr(payments, "_fetch_payment", fetch)

    response = await payments.recheck_payment_handler.__wrapped__(request)

    assert response.status == 200
    assert json.loads(response.text) == saved


@pytest.mark.asyncio
async def test_reprocess_completed_payment_does_not_credit_again(monkeypatch) -> None:
    request = command_request(
        "/internal/admin/payments/9/reprocess",
        {
            "reason": "verify duplicate webhook",
            "confirmation": "REPROCESS 9",
        },
    )
    original = payment_row(status="completed", user_balance=37)
    completed_calls: list[str] = []
    events: list[dict[str, Any]] = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def reserve(*_args, **_kwargs):
        return None

    async def fetch(_payment_id: int):
        return original

    async def complete(order_id: str, *, bot=None):
        completed_calls.append(order_id)
        return {"ok": True}

    async def finish(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(payments.db_backend, "connect", lambda: Connection())
    monkeypatch.setattr(payments, "_reserve_command", reserve)
    monkeypatch.setattr(payments, "_fetch_payment", fetch)
    monkeypatch.setattr(payments, "_complete_transaction", complete)
    monkeypatch.setattr(payments, "_finish_command", finish)

    response = await payments.reprocess_payment_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["data"]["action"] == "already_completed"
    assert completed_calls == []
    assert events[0]["event"]["event_type"] == "payment.reprocessed"


def valid_price_config() -> dict[str, Any]:
    return {
        "currency": "RUB",
        "packages": [
            {
                "id": "start",
                "name": "Start",
                "credits": 25,
                "price_rub": 250,
                "bonus_credits": 0,
            }
        ],
        "costs_reference": {
            "image_models": {"banana_2": 2.5},
            "video_models": {
                "v3_std": {
                    "base": 15,
                    "duration_costs": {"5": 15},
                    "quality_costs": {},
                }
            },
        },
        "admin_ids": [123],
        "support_contact": "@only_tany",
    }


def test_tariff_merge_preserves_non_tariff_security_fields() -> None:
    current = valid_price_config()
    merged = tariffs._merge_tariff_view(
        current,
        {
            "currency": "RUB",
            "packages": [
                {
                    "id": "start",
                    "name": "Start Plus",
                    "credits": 30,
                    "price_rub": 300,
                    "bonus_credits": 0,
                }
            ],
        },
    )

    assert merged["admin_ids"] == [123]
    assert merged["support_contact"] == "@only_tany"
    assert merged["packages"][0]["credits"] == 30


def test_tariff_validation_rejects_duplicate_packages() -> None:
    config = valid_price_config()
    config["packages"] = [config["packages"][0], dict(config["packages"][0])]

    with pytest.raises(CommandValidationError, match="duplicate package id"):
        tariffs._validate_tariff_config(config)


def test_tariff_validation_accepts_lava_package_fields() -> None:
    config = valid_price_config()
    config["packages"][0]["lava_offer_id"] = "1911ef9d-4d81-4a92-9a4f-1224ff5a6c9c"
    config["packages"][0]["lava_currency"] = "RUB"

    tariffs._validate_tariff_config(config)


def test_atomic_tariff_write_replaces_complete_file(tmp_path: Path) -> None:
    path = tmp_path / "price.json"
    path.write_bytes(b'{"old":true}\n')
    payload = b'{"new":true}\n'

    tariffs._atomic_write(path, payload)

    assert path.read_bytes() == payload
    assert not list(tmp_path.glob(".price.json.*.tmp"))
