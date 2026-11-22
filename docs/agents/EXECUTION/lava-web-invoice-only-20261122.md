# Lava web invoice-only checkout incident — 2026-11-22

## Production evidence

Tanyapi backend accepts Lava `POST /api/v3/invoice` replies that contain invoice `id` and `paymentUrl` but omit `contractId` on the legacy Telegram path (`lava_invoice_compat`). The browser-native `bot/web_commerce.py::create_payment` separately rejected such replies because it required `contractId` before persisting the invoice.

Production logs Nov 21-22 repeatedly showed `Invalid web invoice binding` right after `Accepted Lava invoice response ... no contractId`; 12 historical `web_payment_orders` were in `creating` without invoice ID, contract ID, or payment URL. These records cannot be proven paid or safely bound from local data. No automatic duplicate invoice creation or crediting is authorized.

## Fix

- Accept a successful create reply with invoice ID + validated HTTPS checkout URL; `contractId` may be absent.
- Persist the provider invoice ID immediately while still `creating`, so a transient detail lookup failure retains a durable recovery handle and repeat requests reuse the same local order.
- Verify authenticated provider GET returns the **same** invoice ID, exact RUB amount and currency before enabling the checkout URL. Reject mismatched identity or any conflicting provider-supplied `contractId`.
- Derive a fallback `contract_id = invoice_id` only after independent verification; prefer provider-supplied contract ID when available.
- Reconciliation safely promotes a `creating` record with a verified provider invoice, persisting a later binding. No state transition when detail lookup yields no invoice.
- All wallet settlements remain idempotent by `web:topup:<order_id>`. No edits to credits, prices, existing invoices, historical rows, or payment method priority.

## Regression verification

New tests in `tests/test_web_commerce_settlement.py`: invoice-only checkout and duplicate callback, provider API outage after durable binding and no duplicate invoice, provider identity mismatch and no credits. Existing contractful checkout + amount-mismatch + outage tests remain in place.

## Release requirements

- Python/deploy, Safe Regression, Mini App browser E2E, Production Docker Image CI all green.
- Native protected auto-merge to `tanyapi` and exact SHA deployment.
- Production no-cost smoke: unchanged current prices, provider API status, webhook 2xx within 10s, payments idempotent. Do not create paid production invoice solely for testing.
- Separately address 12 unbound `creating` orders via a read-only merchant/provider reconciliation using proof of original invoice identity. Never blindly replay or credit.
- Follow up on cryptographic webhook authentication: currently the observed IP is temporarily allowlisted and external signature is not configured.
