# Prodamus Payform

Production integration for the `tanyapi` payment flow.

## Required merchant configuration

Set these values only in the production `.env` / secret store:

```env
PRODAMUS_PAYFORM_URL=https://<merchant>.payform.ru/
PRODAMUS_SECRET_KEY=<secret from Prodamus Payform settings>
PRODAMUS_SYS=<integration code agreed with Prodamus support>
```

Optional overrides:

```env
PRODAMUS_WEBHOOK_URL=https://tanyapi.chillcreative.ru/prodamus/webhook
PRODAMUS_SUCCESS_URL=<optional Mini App return URL>
```

Do not commit real values. The payment method stays hidden in the Mini App and
Telegram payment keyboard until all three required variables are present.

## Prodamus settings

- Webhook: `POST https://tanyapi.chillcreative.ru/prodamus/webhook`.
- Use the same secret key as `PRODAMUS_SECRET_KEY`.
- `SYS` is mandatory in this integration because `urlNotification` is passed in
  each signed checkout.
- The generated checkout uses `callbackType=json` and `payments_limit=1`.
- Do not use `urlSuccess` as a payment confirmation. Credits are issued only
  after a webhook with a valid `Sign` header and `payment_status=success`.

## Runtime contract

1. A checkout creates a local `pending` transaction before the link is shown.
2. The Payform URL is signed with HMAC-SHA256 using Prodamus canonical JSON.
3. The webhook signature is verified before any database lookup.
4. The merchant order, amount and currency are checked against the transaction.
5. Successful payment is finalized through the shared atomic
   `_complete_transaction()` path, so webhook retries remain idempotent.
6. Invalid signatures and mismatched amounts return non-200 responses.

## Safe verification

```bash
curl -i -X POST https://tanyapi.chillcreative.ru/prodamus/webhook \
  -H 'Content-Type: application/json' \
  --data '{}'
```

When Prodamus is configured, an unsigned request must return `401`. A real
payment should then produce one completed `provider=prodamus` transaction and
one balance credit even if Prodamus retries the webhook.
