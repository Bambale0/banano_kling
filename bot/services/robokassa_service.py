from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

ROBOKASSA_MAX_INV_ID = 9_223_372_036_854_775_807
_SUPPORTED_HASHES = {"md5", "sha1", "sha256", "sha512"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_amount(value: Any) -> str:
    """Normalize checkout amounts to two decimal places."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid payment amount") from exc
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    return format(amount, ".2f")


def amounts_equal(actual: Any, expected: Any) -> bool:
    """Compare callback amount independently of provider decimal formatting."""
    try:
        return Decimal(str(actual)) == Decimal(str(expected))
    except (InvalidOperation, ValueError, TypeError):
        return False


def new_invoice_id() -> str:
    """Create a positive numeric InvId that fits Robokassa limits."""
    # Milliseconds leave six decimal digits for collision-resistant entropy while
    # staying comfortably below signed 64-bit max for current Unix timestamps.
    candidate = int(time.time() * 1000) * 1_000_000 + secrets.randbelow(1_000_000)
    if not 0 < candidate <= ROBOKASSA_MAX_INV_ID:
        candidate = secrets.randbelow(ROBOKASSA_MAX_INV_ID - 1) + 1
    return str(candidate)


def _hash_text(value: str, algorithm: str) -> str:
    normalized = str(algorithm or "md5").strip().lower().replace("-", "")
    if normalized not in _SUPPORTED_HASHES:
        raise ValueError(f"Unsupported Robokassa hash algorithm: {algorithm}")
    if normalized == "md5":
        return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()
    return hashlib.new(normalized, value.encode("utf-8")).hexdigest()


def _shp_items(payload: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not payload:
        return []
    return sorted(
        (
            str(key),
            str(value),
        )
        for key, value in payload.items()
        if str(key).startswith("Shp_")
    )


def build_checkout_signature(
    merchant_login: str,
    raw_amount: str,
    inv_id: str,
    password1: str,
    *,
    algorithm: str = "md5",
    shp: dict[str, Any] | None = None,
) -> str:
    parts = [merchant_login, raw_amount, inv_id, password1]
    parts.extend(f"{key}={value}" for key, value in _shp_items(shp))
    return _hash_text(":".join(parts), algorithm)


def build_result_signature(
    raw_amount: str,
    inv_id: str,
    password2: str,
    *,
    algorithm: str = "md5",
    shp: dict[str, Any] | None = None,
) -> str:
    parts = [raw_amount, inv_id, password2]
    parts.extend(f"{key}={value}" for key, value in _shp_items(shp))
    return _hash_text(":".join(parts), algorithm)


class RobokassaService:
    """Signed redirect checkout and ResultURL verification for Robokassa."""

    def __init__(self) -> None:
        self.merchant_login = os.getenv("ROBOKASSA_MERCHANT_LOGIN", "").strip()
        self.password1 = os.getenv("ROBOKASSA_PASSWORD1", "").strip()
        self.password2 = os.getenv("ROBOKASSA_PASSWORD2", "").strip()
        self.test_password1 = os.getenv("ROBOKASSA_TEST_PASSWORD1", "").strip()
        self.test_password2 = os.getenv("ROBOKASSA_TEST_PASSWORD2", "").strip()
        self.hash_algorithm = (
            os.getenv("ROBOKASSA_HASH_ALGORITHM", "md5").strip().lower() or "md5"
        )
        self.test_mode = _env_bool("ROBOKASSA_TEST_MODE", False)
        self.pay_base_url = (
            os.getenv(
                "ROBOKASSA_PAY_BASE_URL",
                "https://auth.robokassa.ru/Merchant/Index.aspx",
            ).strip()
            or "https://auth.robokassa.ru/Merchant/Index.aspx"
        )
        self.webhook_path = (
            os.getenv("ROBOKASSA_WEBHOOK_PATH", "/robokassa/result").strip()
            or "/robokassa/result"
        )
        if not self.webhook_path.startswith("/"):
            self.webhook_path = f"/{self.webhook_path}"

        # Validate the configured algorithm eagerly without exposing credentials.
        _hash_text("robokassa-config-check", self.hash_algorithm)

        active_password1 = self.active_password1
        active_password2 = self.active_password2
        self.enabled = bool(self.merchant_login and active_password1 and active_password2)

    @property
    def active_password1(self) -> str:
        return self.test_password1 if self.test_mode else self.password1

    @property
    def active_password2(self) -> str:
        return self.test_password2 if self.test_mode else self.password2

    def create_payment_url(
        self,
        *,
        amount_rub: Any,
        inv_id: str,
        description: str,
        email: str | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("Robokassa is not configured")

        invoice = str(inv_id or "").strip()
        if not invoice.isdigit() or not 0 < int(invoice) <= ROBOKASSA_MAX_INV_ID:
            raise ValueError("Robokassa InvId must be a positive 64-bit integer")

        amount = normalize_amount(amount_rub)
        signature = build_checkout_signature(
            self.merchant_login,
            amount,
            invoice,
            self.active_password1,
            algorithm=self.hash_algorithm,
        )
        params: dict[str, str] = {
            "MerchantLogin": self.merchant_login,
            "OutSum": amount,
            "InvId": invoice,
            "Description": str(description or "")[:100],
            "SignatureValue": signature,
            "Culture": "ru",
            "Encoding": "utf-8",
        }
        if self.test_mode:
            params["IsTest"] = "1"
        if email:
            params["Email"] = str(email).strip()

        separator = "&" if "?" in self.pay_base_url else "?"
        return f"{self.pay_base_url}{separator}{urlencode(params)}"

    def verify_result(self, payload: dict[str, Any]) -> tuple[bool, str]:
        if not self.enabled:
            return False, "service_disabled"

        raw_amount = str(payload.get("OutSum") or "").strip()
        inv_id = str(payload.get("InvId") or "").strip()
        received = str(payload.get("SignatureValue") or "").strip().lower()
        if not raw_amount or not inv_id or not received:
            return False, "missing_required_fields"
        if not inv_id.isdigit() or not 0 < int(inv_id) <= ROBOKASSA_MAX_INV_ID:
            return False, "invalid_invoice_id"

        expected = build_result_signature(
            raw_amount,
            inv_id,
            self.active_password2,
            algorithm=self.hash_algorithm,
            shp=payload,
        ).lower()
        if not hmac.compare_digest(received, expected):
            return False, "invalid_signature"
        return True, "ok"


robokassa_service = RobokassaService()
