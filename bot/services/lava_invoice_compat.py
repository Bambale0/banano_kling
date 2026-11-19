from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any
from uuid import UUID

from bot.config import config
from bot.services import lava_payment_safety as safety
from bot.services.lava_service import LavaProviderUnavailable, LavaService, lava_service

logger = logging.getLogger(__name__)

_INSTALL_MARKER = "_lava_invoice_compat_installed"
_TRANSACTION_MARKER = "_lava_invoice_transaction_normalizer"


# The invoice detail API may return 404 even when its list endpoint contains
# the exact invoice. Keep this snapshot bounded, short-lived and PII-free.
_LIST_CACHE_TTL_SECONDS = 120.0
_LIST_MAX_PAGES = 15
_LIST_PAGE_SIZE = 100
_LIST_LOOKBACK_DAYS = 14
_lava_list_lock = asyncio.Lock()
_lava_list_cache: dict[str, dict[str, Any]] = {}
_lava_list_cache_until = 0.0


def _clear_lava_invoice_list_cache() -> None:
    """Test/operator reset; never changes payment records."""
    global _lava_list_cache_until, _lava_list_cache
    _lava_list_cache = {}
    _lava_list_cache_until = 0.0


def _is_recent_transaction(transaction: Any) -> bool:
    timestamp = getattr(transaction, "created_at", None)
    if not isinstance(timestamp, datetime):
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    age = datetime.now(UTC) - timestamp
    return timedelta(seconds=-300) <= age <= timedelta(days=_LIST_LOOKBACK_DAYS)


async def _list_verified_invoice(transaction: Any) -> dict[str, Any] | None:
    """Find a locally created invoice by exact ID and verified receipt.

    A missing or incomplete vendor list must NEVER imply failed payment.
    A receipt mismatch returns a nonterminal marker: no credit, no refund.
    """
    global _lava_list_cache_until, _lava_list_cache

    invoice_id = str(getattr(transaction, "payment_id", "") or "").strip()
    if not invoice_id or not _is_recent_transaction(transaction):
        return None
    try:
        UUID(invoice_id)
    except (TypeError, ValueError):
        # Non-UUID legacy/test references preserve the existing detail lookup.
        return None

    async with _lava_list_lock:
        if time.monotonic() >= _lava_list_cache_until:
            begin = (datetime.now(UTC) -
                     timedelta(days=_LIST_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            records: dict[str, dict[str, Any]] = {}
            # Bound the entire vendor pagination operation. A provider outage
            # should produce a retryable 503 instead of a minutes-long webhook.
            deadline = time.monotonic() + max(
                0.05, float(config.LAVA_INVOICE_LIST_TIMEOUT_SECONDS)
            )
            total = None
            complete = False
            for page in range(1, _LIST_MAX_PAGES + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning("Lava invoice listing timed out page=%s", page)
                    raise LavaProviderUnavailable(None)
                try:
                    response = await asyncio.wait_for(
                        lava_service._request(
                            "GET", "/api/v2/invoices",
                            params={
                                # The provider currently returns all lifecycle
                                # states; validate every returned status.
                                "invoiceStatuses": "IN_PROGRESS",
                                "beginDate": begin,
                                "page": page,
                                "size": _LIST_PAGE_SIZE,
                            },
                        ),
                        timeout=remaining,
                    )
                except TimeoutError as exc:
                    logger.warning("Lava invoice listing timed out page=%s", page)
                    raise LavaProviderUnavailable(None) from exc
                except Exception as exc:
                    logger.warning("Lava invoice listing unavailable: %s",
                                   type(exc).__name__)
                    raise LavaProviderUnavailable(None) from exc
                if not isinstance(response, dict) or not response.get("ok"):
                    status_code = response.get("status") if isinstance(response, dict) else None
                    logger.warning("Lava invoice listing failed status=%s", status_code)
                    if status_code == 404:
                        # Some installations expose only the detail endpoint.
                        return None
                    raise LavaProviderUnavailable(status_code)
                items = response.get("items")
                if not isinstance(items, list):
                    logger.warning("Lava invoice listing malformed: items not an array")
                    return None
                raw_total = response.get("total")
                if isinstance(raw_total, int) and raw_total >= 0:
                    total = raw_total
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("id") or "").strip()
                    state = str(item.get("status") or "").lower()
                    receipt = item.get("receipt")
                    if not key:
                        continue
                    if state not in {"new", "in_progress", "completed", "failed"}:
                        # Unknown status must not authorize payment state change.
                        state = ""
                    if not isinstance(receipt, dict):
                        receipt = {}
                    # Do not cache buyer / contact / provider PII.
                    records[key] = {
                        "id": key, "status": state,
                        "receipt": {
                            "amount": receipt.get("amount"),
                            "currency": receipt.get("currency"),
                        },
                    }
                if not items or (total is not None and page * _LIST_PAGE_SIZE >= total):
                    complete = True
                    break
                if len(items) < _LIST_PAGE_SIZE and total is None:
                    complete = True
                    break
            if not complete:
                # No partial vendor snapshot: missing pages could hide a paid invoice.
                logger.warning("Lava invoice listing exceeded page safety limit")
                return None
            _lava_list_cache = records
            _lava_list_cache_until = time.monotonic() + _LIST_CACHE_TTL_SECONDS

        record = _lava_list_cache.get(invoice_id)
        if record is None:
            return None
        if not safety._payload_amount_matches(transaction, record["receipt"]):
            logger.error("Lava invoice listing receipt mismatch; confirmation blocked")
            return {"id": invoice_id, "status": ""}
        return dict(record)


async def _create_invoice_compatible(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Create a Lava invoice without requiring contractId in the create response.

    The current POST /api/v3/invoice response can contain only the invoice ``id``
    and ``paymentUrl``. ``contractId`` is a contract/webhook identifier and may
    become available later. The invoice ID is sufficient to persist the local
    transaction and query GET /api/v2/invoices/{id}.
    """

    # Call the class implementation directly. The previous safety layer replaces
    # the instance method and incorrectly rejects successful invoice-only replies.
    response = await LavaService.create_invoice(lava_service, *args, **kwargs)
    if not isinstance(response, dict) or not response.get("ok"):
        return response

    invoice_id = lava_service.extract_invoice_id(response)
    if not invoice_id:
        logger.error("Rejected Lava invoice response without invoice id")
        return {
            **response,
            "ok": False,
            "error": "Lava did not return invoiceId",
        }

    contract_id = lava_service.extract_contract_id(response)
    if contract_id:
        try:
            await safety._save_binding(contract_id, invoice_id)
        except Exception:
            # Do not invalidate a successfully created invoice. The webhook and
            # reconcile paths can rebuild this mapping from the invoice API.
            logger.exception(
                "Could not persist Lava contract/invoice mapping at creation"
            )
    else:
        logger.info(
            "Accepted Lava invoice response with invoice_id=%s and no contractId; "
            "binding will be resolved from the invoice API/webhook",
            invoice_id,
        )

    return response


def _make_transaction_normalizer(
    original: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    signature = inspect.signature(original)

    async def create_transaction_with_invoice_id(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind_partial(*args, **kwargs)
        provider = str(bound.arguments.get("provider") or "").lower()
        payment_id = str(bound.arguments.get("payment_id") or "").strip()

        if provider == "lava" and payment_id:
            mapped_invoice_id = await safety._invoice_id_for_contract(payment_id)
            if mapped_invoice_id:
                bound.arguments["payment_id"] = mapped_invoice_id

        return await original(*bound.args, **bound.kwargs)

    setattr(create_transaction_with_invoice_id, _TRANSACTION_MARKER, True)
    return create_transaction_with_invoice_id


def _install_transaction_normalizer(module: ModuleType) -> None:
    original = getattr(module, "create_transaction", None)
    if not callable(original) or getattr(original, _TRANSACTION_MARKER, False):
        return
    module.create_transaction = _make_transaction_normalizer(original)


def _make_lookup_with_discovery(
    original_lookup: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
    async def lookup_lava_transaction(
        *,
        contract_id: str,
        order_id: str | None,
    ) -> Any | None:
        transaction = await original_lookup(
            contract_id=contract_id,
            order_id=order_id,
        )
        if transaction:
            return transaction

        # New invoice creation responses may not expose contractId. Resolve the
        # relation when the first webhook arrives, then retry the local lookup by
        # the invoice ID stored in transactions.payment_id.
        invoice_id = await safety._discover_invoice_id_by_contract(contract_id)
        if not invoice_id:
            return None

        return await original_lookup(
            contract_id=contract_id,
            order_id=order_id,
        )

    return lookup_lava_transaction


async def _provider_status_compatible(
    transaction: Any,
    *,
    contract_id: str | None = None,
    retry_delays: Iterable[float] = (0.0, 0.75, 1.5),
) -> tuple[str, str | None]:
    """Query by invoice ID first and bind a later webhook contractId.

    New rows store the invoice ID. Legacy rows may still store contractId, so the
    already-installed get_invoice compatibility wrapper remains the fallback.
    """

    payment_id = str(getattr(transaction, "payment_id", "") or "").strip()
    contract = str(contract_id or "").strip()

    candidates: list[str] = []
    for candidate in (payment_id, contract):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return "", None

    last_status = ""
    resolved_invoice_id: str | None = None

    for delay in retry_delays:
        if delay:
            await asyncio.sleep(delay)

        # Prefer verified list lookup for recent local invoices. The provider's
        # detail endpoint sometimes answers 404 for valid contract IDs.
        invoice = await _list_verified_invoice(transaction)
        # Keep the successful *lookup identifier*, not the last item in the
        # candidate-building loop. A provider list hit always uses payment_id.
        resolved_lookup_id = payment_id if invoice is not None else None
        if invoice is None:
            for candidate in candidates:
                invoice = await lava_service.get_invoice(candidate)
                if invoice:
                    resolved_lookup_id = candidate
                    break
        if not invoice:
            continue

        # GET /api/v2/invoices/{invoice_id} may return the contract ID
        # as the top-level "id". Do not overwrite the invoice ID used in
        # the successful lookup with that unrelated response identifier.
        # Otherwise a webhook can poison contract -> invoice bindings and
        # cause later status requests to return 404.
        if resolved_lookup_id == payment_id:
            resolved_invoice_id = payment_id
        else:
            # For legacy contract-based transactions, only accept an
            # explicitly named invoice identifier from the response.
            explicit_invoice_id = invoice.get("invoiceId") or invoice.get("invoice_id")
            if explicit_invoice_id:
                resolved_invoice_id = str(explicit_invoice_id)

        if contract and resolved_invoice_id and contract != resolved_invoice_id:
            try:
                await safety._save_binding(contract, resolved_invoice_id)
            except Exception:
                logger.exception(
                    "Could not persist Lava contract/invoice mapping during status check"
                )

        last_status = (
            lava_service.webhook_status(invoice)
            or str(invoice.get("status") or "").lower()
        )
        if last_status not in safety._PENDING_STATUSES:
            break

    if not resolved_invoice_id and contract:
        resolved_invoice_id = await safety._invoice_id_for_contract(contract)

    return last_status, resolved_invoice_id


def install_lava_invoice_compat(
    payments_module: ModuleType,
    lava_checkout_module: ModuleType,
) -> None:
    """Install the invoice-only response compatibility fix once."""

    if getattr(lava_service, _INSTALL_MARKER, False):
        return

    original_lookup = safety._lookup_lava_transaction

    # Replace only the incorrect creation wrapper. The existing safe get_invoice,
    # webhook, authentication and atomic completion layers stay active.
    lava_service.create_invoice = _create_invoice_compatible  # type: ignore[method-assign]
    safety._lookup_lava_transaction = _make_lookup_with_discovery(original_lookup)
    safety._provider_status = _provider_status_compatible

    _install_transaction_normalizer(payments_module)
    _install_transaction_normalizer(lava_checkout_module)

    setattr(lava_service, _INSTALL_MARKER, True)
    logger.info("Installed Lava invoice-only response compatibility layer")
