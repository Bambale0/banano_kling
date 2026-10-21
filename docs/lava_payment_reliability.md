# Lava payment reliability

This change keeps both Lava identifiers and makes webhook delivery retry-safe.

## Identifier model

- `contractId` is the identifier delivered by `payment.success` / `payment.failed` webhooks.
- `invoiceId` is the identifier used with `GET /api/v2/invoices/{id}`.
- `transactions.payment_id` remains backward compatible with existing rows.
- `lava_payment_bindings` stores the durable `contractId -> invoiceId` mapping.

The invoice creation wrapper persists the mapping before the payment link is shown. Existing rows are backfilled from `GET /api/v2/invoices` when needed.

## Webhook behavior

- Unknown route probes return `200` and are ignored.
- Invalid JSON returns `400`.
- A configured webhook secret is verified using either `X-Api-Key` or HTTP Basic authentication.
- Without configured credentials, only Lava's documented source IP is accepted and the event is always verified against the invoice API.
- `payment.success` is completed only after the invoice API reports a successful status.
- Temporary `in_progress`, lookup failures, and database failures return `503`, allowing Lava to retry delivery.
- Amount and currency must match the local transaction: RUB webhooks are compared against `transactions.amount_rub`, USD (foreign) webhooks against the package `price_usd` resolved from the package id encoded in the order id. Unknown currencies are rejected.
- Raw headers, Basic credentials, request bodies, and buyer email are not logged.

## Environment variables

Preferred API-key webhook authentication:

```env
LAVA_WEBHOOK_SECRET=<the X-Api-Key configured in Lava>
```

HTTP Basic authentication can use either:

```env
LAVA_WEBHOOK_BASIC_USERNAME=<rotated username>
LAVA_WEBHOOK_BASIC_PASSWORD=<rotated password>
```

or:

```env
LAVA_WEBHOOK_BASIC_CREDENTIALS=<rotated username:password>
```

`LAVA_WEBHOOK_SECRET` also accepts the full Basic `username:password` value for backward compatibility.

The allowed source IP fallback defaults to Lava's documented sender address and can be overridden:

```env
LAVA_WEBHOOK_ALLOWED_IPS=158.160.60.174
```

## Reconciliation

The periodic reconciliation loop no longer marks stale pending rows as failed before checking Lava. It now:

1. resolves `contractId` to `invoiceId`;
2. checks the invoice status;
3. atomically completes successful transactions;
4. marks a transaction failed only when Lava reports a final failed status;
5. records lookup failures as errors instead of silently counting them as pending.

## Deployment safety

Rotate previously exposed Basic credentials before enabling credential verification. Deploy the code, restart the Telegram service, then run the existing Lava success audit over the period that may contain missed payments. Atomic payment completion prevents duplicate crediting when a webhook is resent.

### Sender changes and transaction binding

Keep `LAVA_WEBHOOK_ALLOWED_IPS` as explicit operator configuration when Lava changes delivery infrastructure; do not infer trust from a callback's claimed IP or add new production senders to source-code defaults. Configured secret/Basic authentication always takes precedence. Every accepted payment still requires a matching local transaction and independent invoice-API confirmation; sender admission never grants balance by itself. An `order_id` hint cannot associate a different invoice with a transaction. The invoice identifier or its persisted contract mapping must match before provider verification or completion.

The 2026-10-21 audit compared 100 recent provider invoices with local final states (33 paid/completed, 67 failed), plus pending invoices. No provider-paid/local-uncredited item was found in that sample. This is a bounded incident audit, not certification of all historical payments.
