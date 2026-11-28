from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import aiohttp

from bot import db as db_backend

logger = logging.getLogger(__name__)
_lookup_reason: ContextVar[str] = ContextVar('freekassa_lookup_reason', default='unknown')

FREEKASSA_PAID_STATUS = 1
FREEKASSA_FAILED_STATUSES = {6, 8, 9}
FREEKASSA_CARD_RUB_METHOD_ID = 36
FREEKASSA_SBP_METHOD_ID = 44
FREEKASSA_CHECKOUT_METHOD_IDS = {
    FREEKASSA_CARD_RUB_METHOD_ID,
    FREEKASSA_SBP_METHOD_ID,
}
DEFAULT_ALLOWED_WEBHOOK_IPS = {
    "168.119.157.136",
    "168.119.60.227",
    "178.154.197.79",
    "51.250.54.238",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_amount(value: Any) -> str:
    """Return a stable two-decimal amount used in signatures and DB checks."""
    try:
        amount = Decimal(str(value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid payment amount") from exc
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    return format(amount, ".2f")


def build_sci_signature(
    merchant_id: str,
    amount: Any,
    secret_word: str,
    currency: str,
    order_id: str,
) -> str:
    amount_text = normalize_amount(amount)
    source = f"{merchant_id}:{amount_text}:{secret_word}:{currency}:{order_id}"
    return hashlib.md5(
        source.encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def build_notification_signature(
    merchant_id: str,
    raw_amount: str,
    secret_word_2: str,
    order_id: str,
) -> str:
    source = f"{merchant_id}:{raw_amount}:{secret_word_2}:{order_id}"
    return hashlib.md5(
        source.encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def build_api_signature(payload: dict[str, Any], api_key: str) -> str:
    values = [str(payload[key]) for key in sorted(payload) if key != "signature"]
    message = "|".join(values).encode("utf-8")
    return hmac.new(api_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def normalize_order_status(value: Any) -> dict[str, Any]:
    try:
        status = int(value)
    except (TypeError, ValueError):
        status = -1
    return {
        "status_code": status,
        "status": {
            0: "new",
            1: "paid",
            6: "refunded",
            8: "error",
            9: "cancelled",
        }.get(status, "unknown"),
        "paid": status == FREEKASSA_PAID_STATUS,
        "failed": status in FREEKASSA_FAILED_STATUSES,
    }


class FreeKassaService:
    """FreeKassa SCI checkout with optional API reconciliation."""

    def __init__(self) -> None:
        self.merchant_id = os.getenv("FREEKASSA_MERCHANT_ID", "").strip()
        self.secret_word = os.getenv("FREEKASSA_SECRET_WORD", "").strip()
        self.secret_word_2 = os.getenv("FREEKASSA_SECRET_WORD_2", "").strip()
        self.api_key = os.getenv("FREEKASSA_API_KEY", "").strip()
        self.currency = (
            os.getenv("FREEKASSA_CURRENCY", "RUB").strip().upper() or "RUB"
        )
        self.language = (
            os.getenv("FREEKASSA_LANGUAGE", "ru").strip().lower() or "ru"
        )
        self.pay_base_url = os.getenv(
            "FREEKASSA_PAY_BASE_URL", "https://pay.fk.money/"
        ).strip()
        self.api_base_url = (
            os.getenv("FREEKASSA_API_BASE_URL", "https://api.fk.life/v1")
            .strip()
            .rstrip("/")
        )
        self.webhook_path = (
            os.getenv("FREEKASSA_WEBHOOK_PATH", "/freekassa/webhook").strip()
            or "/freekassa/webhook"
        )
        if not self.webhook_path.startswith("/"):
            self.webhook_path = f"/{self.webhook_path}"

        self.verify_webhook_ip = _env_bool("FREEKASSA_VERIFY_IP", True)
        configured_ips = {
            item.strip()
            for item in os.getenv("FREEKASSA_ALLOWED_IPS", "").split(",")
            if item.strip()
        }
        self.allowed_webhook_ips = configured_ips or set(
            DEFAULT_ALLOWED_WEBHOOK_IPS
        )
        self.enabled = bool(
            self.merchant_id and self.secret_word and self.secret_word_2
        )
        self.api_enabled = bool(self.enabled and self.api_key)

        self._session: aiohttp.ClientSession | None = None
        self._nonce_lock = asyncio.Lock()
        # FreeKassa requires every nonce to be greater than the previous one.
        # Serializing the complete API request prevents concurrently generated
        # nonces from reaching the provider out of order.
        self._api_request_lock = asyncio.Lock()
        self._last_nonce = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _next_nonce(self) -> int:
        async with self._nonce_lock:
            current = int(time.time() * 1000)
            self._last_nonce = max(current, self._last_nonce + 1)
            return self._last_nonce

    def create_payment_url(
        self,
        *,
        amount_rub: Any,
        order_id: str,
        email: str | None = None,
        phone: str | None = None,
        payment_system_id: int | None = None,
        custom_params: dict[str, str] | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("FreeKassa is not configured")

        amount = normalize_amount(amount_rub)
        order = str(order_id or "").strip()
        if not order:
            raise ValueError("order_id is required")

        params: dict[str, str] = {
            "m": self.merchant_id,
            "oa": amount,
            "currency": self.currency,
            "o": order,
            "s": build_sci_signature(
                self.merchant_id,
                amount,
                self.secret_word,
                self.currency,
                order,
            ),
            "lang": self.language,
        }
        if email:
            params["em"] = str(email).strip()
        if phone:
            params["phone"] = str(phone).strip()
        if payment_system_id is not None:
            normalized_method_id = int(payment_system_id)
            if normalized_method_id not in FREEKASSA_CHECKOUT_METHOD_IDS:
                raise ValueError("Unsupported FreeKassa payment method")
            params["i"] = str(normalized_method_id)

        for key, value in (custom_params or {}).items():
            key_text = str(key).strip()
            value_text = str(value).strip()
            if key_text.startswith("us_") and value_text:
                params[key_text] = value_text

        separator = "&" if "?" in self.pay_base_url else "?"
        return f"{self.pay_base_url}{separator}{urlencode(params)}"

    async def create_payment(
        self,
        *,
        amount_rub: Any,
        order_id: str,
        description: str = "",
        return_url: str | None = None,
        notification_url: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        customer_ip: str | None = None,
        payment_system_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an API-only Card RUB or SBP order and return its checkout URL."""
        _ = description
        if not self.api_enabled:
            return {"ok": False, "error": "FreeKassa API is not configured"}

        method_id = int(payment_system_id or 0)
        if method_id not in FREEKASSA_CHECKOUT_METHOD_IDS:
            return {"ok": False, "error": "Unsupported FreeKassa payment method"}
        email_text = str(email or "").strip()
        ip_text = str(customer_ip or "").strip()
        if not email_text or not ip_text:
            return {"ok": False, "error": "Customer email and IP are required"}

        payload: dict[str, Any] = {
            "paymentId": str(order_id),
            "i": method_id,
            "email": email_text,
            "ip": ip_text,
            "amount": normalize_amount(amount_rub),
            "currency": self.currency,
        }
        if phone:
            payload["tel"] = str(phone).strip()
        if return_url:
            payload["success_url"] = return_url
        if notification_url:
            payload["notification_url"] = notification_url

        response = await self._api_post("orders/create", payload)
        payment_url = str((response or {}).get("location") or "").strip()
        provider_order_id = str((response or {}).get("orderId") or "").strip()
        if (response or {}).get("type") != "success" or not payment_url:
            logger.warning("FreeKassa API did not create order: payment_id=%s", order_id)
            return {"ok": False, "error": "FreeKassa rejected payment creation"}

        return {
            "ok": True,
            "payment_id": provider_order_id or str(order_id),
            "payment_url": payment_url,
            "provider": "freekassa",
            "mode": "api",
        }

    def verify_notification(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if not self.enabled:
            return False, "service_disabled"

        merchant_id = str(payload.get("MERCHANT_ID") or "").strip()
        raw_amount = str(payload.get("AMOUNT") or "").strip()
        order_id = str(payload.get("MERCHANT_ORDER_ID") or "").strip()
        received_signature = str(payload.get("SIGN") or "").strip().lower()

        if not merchant_id or not raw_amount or not order_id or not received_signature:
            return False, "missing_required_fields"
        if not hmac.compare_digest(merchant_id, self.merchant_id):
            return False, "merchant_mismatch"

        expected = build_notification_signature(
            merchant_id,
            raw_amount,
            self.secret_word_2,
            order_id,
        )
        if not hmac.compare_digest(received_signature, expected.lower()):
            return False, "invalid_signature"
        return True, "ok"

    def is_allowed_webhook_ip(self, remote_ip: str | None) -> bool:
        if not self.verify_webhook_ip:
            return True
        return bool(remote_ip and remote_ip in self.allowed_webhook_ips)

    async def _api_post(
        self, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.api_enabled:
            _lookup_reason.set('disabled')
            return None

        async with self._api_request_lock:
            body = dict(payload)
            body["shopId"] = int(self.merchant_id)
            body["nonce"] = await self._next_nonce()
            body["signature"] = build_api_signature(body, self.api_key)

            session = await self._get_session()
            url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
            try:
                async with session.post(url, json=body) as response:
                    if response.status != 200:
                        _lookup_reason.set("http_error")
                        logger.warning(
                            "FreeKassa API request failed: endpoint=%s status=%s",
                            endpoint,
                            response.status,
                        )
                        return None
                    try:
                        data = await response.json(content_type=None)
                    except (ValueError, UnicodeError):
                        _lookup_reason.set("invalid_json")
                        logger.warning(
                            "FreeKassa API returned invalid JSON: endpoint=%s",
                            endpoint,
                        )
                        return None
                    if not isinstance(data, dict):
                        _lookup_reason.set("invalid_shape")
                        return None
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError):
                _lookup_reason.set("transport_error")
                logger.warning("FreeKassa API request error: endpoint=%s", endpoint)
                return None

    async def get_payment(
        self,
        payment_id: str | None = None,
        *,
        merchant_order_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Look up a payment through the optional merchant API."""
        lookup_id = str(merchant_order_id or payment_id or "").strip()
        if not lookup_id:
            return None
        if not self.api_enabled:
            return {
                "status": "webhook_only",
                "paid": False,
                "failed": False,
                "merchant_order_id": lookup_id,
            }

        response = await self._api_post("orders", {"paymentId": lookup_id})
        orders = (response or {}).get("orders")
        if response is None:
            return None
        if response.get("type") == "error":
            _lookup_reason.set("api_error")
            return None
        if not isinstance(orders, list):
            _lookup_reason.set("invalid_shape")
            return None
        if not orders:
            _lookup_reason.set("empty_orders")
            return None

        matches = [
            item for item in orders
            if isinstance(item, dict)
            and str(item.get("merchant_order_id") or "") == lookup_id
        ]
        # Never infer a merchant order from an unrelated or ambiguous response.
        if len(matches) != 1:
            _lookup_reason.set("identity_mismatch" if not matches else "ambiguous_identity")
            logger.warning("FreeKassa order lookup unverified: exact_matches=%s", len(matches))
            return None
        selected = matches[0]

        status = normalize_order_status(selected.get("status"))
        return {
            **status,
            "id": str(selected.get("fk_order_id") or ""),
            "merchant_order_id": lookup_id,
            "amount": selected.get("amount"),
            "currency": selected.get("currency"),
            "raw": selected,
        }

    async def _select_rotating_pending(self, provider_names, limit):
        """Keep a fresh lane and a durable keyset sweep over the remaining backlog."""
        scope = ",".join(sorted(set(provider_names)))
        placeholders = ",".join("?" for _ in provider_names)
        where = f"FROM transactions WHERE provider IN ({placeholders}) AND status = 'pending'"
        fields = "SELECT id, order_id, payment_id, amount_rub "
        history_budget = max(1, limit // 5)
        async with db_backend.connect() as connection:
            connection.row_factory = db_backend.Row
            cursor = await connection.execute(
                "SELECT last_transaction_id FROM freekassa_reconcile_cursor WHERE scope = ?",
                (scope,),
            )
            previous = await cursor.fetchone()
            last_id = int(previous["last_transaction_id"]) if previous else 0
            cursor = await connection.execute(
                fields + where + " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*provider_names, limit - history_budget),
            )
            fresh = list(await cursor.fetchall())
            excluded = tuple(row["id"] for row in fresh)
            exclusion = (
                " AND id NOT IN (" + ",".join("?" for _ in excluded) + ")"
                if excluded else ""
            )
            query = fields + where + exclusion
            budget = limit - len(fresh)
            cursor = await connection.execute(
                query + " AND id > ? ORDER BY id ASC LIMIT ?",
                (*provider_names, *excluded, last_id, budget),
            )
            history = list(await cursor.fetchall())
            if last_id and len(history) < budget:
                cursor = await connection.execute(
                    query + " AND id <= ? ORDER BY id ASC LIMIT ?",
                    (*provider_names, *excluded, last_id, budget - len(history)),
                )
                history.extend(await cursor.fetchall())
        next_id = int(history[-1]["id"]) if history else last_id
        return fresh + history, len(fresh), scope, last_id, next_id

    async def _advance_reconcile_cursor(self, scope: str, previous: int, next_id: int) -> None:
        if previous == next_id:
            return
        async with db_backend.connect() as connection:
            await connection.execute(
                "INSERT INTO freekassa_reconcile_cursor (scope, last_transaction_id) VALUES (?, ?) "
                "ON CONFLICT (scope) DO UPDATE SET last_transaction_id = excluded.last_transaction_id "
                "WHERE freekassa_reconcile_cursor.last_transaction_id = ?",
                (scope, next_id, previous),
            )
            await connection.commit()

    async def poll_pending_transactions(
        self,
        *,
        limit: int = 100,
        providers: Iterable[str] = ("freekassa",),
        rotate_history: bool = True,
        complete_order: Callable[
            [str], Awaitable[dict[str, Any]]
        ]
        | None = None,
    ) -> list[dict[str, Any]]:
        if not self.api_enabled:
            return []

        provider_names = tuple(
            str(provider).strip().lower() for provider in providers if provider
        )
        limit = int(limit)
        if not provider_names or limit <= 0:
            return []
        if rotate_history:
            rows, fresh_count, scope, previous_id, next_id = await self._select_rotating_pending(
                provider_names, limit
            )
        else:
            placeholders = ",".join("?" for _ in provider_names)
            query = (
                "SELECT order_id, payment_id, amount_rub FROM transactions "
                f"WHERE provider IN ({placeholders}) AND status = 'pending' "
                "ORDER BY created_at DESC LIMIT ?"
            )
            async with db_backend.connect() as connection:
                connection.row_factory = db_backend.Row
                cursor = await connection.execute(query, (*provider_names, limit))
                rows = await cursor.fetchall()
            fresh_count = len(rows)

        results: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            order_id = str(row["order_id"])
            item: dict[str, Any] = {"order_id": order_id}
            if rotate_history:
                item["scan_lane"] = "fresh" if index < fresh_count else "history"
            token = _lookup_reason.set("unknown")
            try:
                payment = await self.get_payment(merchant_order_id=order_id)
                reason = _lookup_reason.get()
            finally:
                _lookup_reason.reset(token)
            if not payment:
                item["action"] = "not_found"
                item["lookup_reason"] = reason
                results.append(item)
                continue

            item["status"] = payment.get("status")
            if payment.get("merchant_order_id") != order_id:
                item["action"] = "verification_failed"
                results.append(item)
                continue
            if payment.get("paid"):
                try:
                    amount_matches = (
                        normalize_amount(payment.get("amount"))
                        == normalize_amount(row["amount_rub"])
                    )
                except (ValueError, TypeError, InvalidOperation):
                    amount_matches = False
                currency_matches = (
                    str(payment.get("currency") or "").strip().upper()
                    == self.currency
                )
                if not amount_matches or not currency_matches:
                    # Keep the order pending for a verified webhook or review.
                    item["action"] = "verification_failed"
                    results.append(item)
                    continue
                completion = (
                    await complete_order(order_id) if complete_order else None
                )
                item["action"] = (
                    "already_completed"
                    if completion and completion.get("already_completed")
                    else "completed"
                    if completion and completion.get("ok")
                    else "paid_unhandled"
                )
                item["completion"] = completion
            elif payment.get("failed"):
                async with db_backend.connect() as connection:
                    cursor = await connection.execute(
                        "UPDATE transactions SET status = 'failed' "
                        "WHERE order_id = ? AND status = 'pending'",
                        (order_id,),
                    )
                    await connection.commit()
                item["action"] = (
                    "failed" if cursor.rowcount else "already_updated"
                )
            else:
                item["action"] = "still_pending"
            results.append(item)

        if rotate_history:
            # A crash repeats work instead of silently skipping unprocessed history.
            await self._advance_reconcile_cursor(scope, previous_id, next_id)
        return results


freekassa_service = FreeKassaService()
