# YooKassa Integration

## Production URLs

Webhook URL for YooKassa dashboard:

```text
https://2loop.chillcreative.ru/yookassa/webhook
```

Compatibility URL also accepted by production:

```text
https://2loop.chillcreative.ru/webhook/yookassa
```

Return URL:

```text
https://2loop.chillcreative.ru/shop
```

## Required Environment

```env
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://2loop.chillcreative.ru/shop
YOOKASSA_RECEIPT_EMAIL=payments@2loop.chillcreative.ru
YOOKASSA_RECEIPT_PHONE=
YOOKASSA_VAT_CODE=1
YOOKASSA_PAYMENT_SUBJECT=service
YOOKASSA_PAYMENT_MODE=full_prepayment
```

## YooKassa Dashboard

In YooKassa personal account, configure HTTP notifications:

- URL: `https://2loop.chillcreative.ru/yookassa/webhook`
- events:
  - `payment.succeeded`
  - `payment.canceled`

YooKassa requires HTTPS on port `443` or `8443`. Production uses public HTTPS on `443`.

The legacy URL `/webhook/yookassa` is kept as an alias so old YooKassa retries do not fail
with `404`, but the dashboard should use `/yookassa/webhook`.

## Local Handler

The route is registered in `bot/main.py` and handled by `bot/handlers/payments.py`.

Flow:

1. User chooses a GOE package.
2. Bot creates a YooKassa payment via `bot/services/yookassa_service.py`.
3. Transaction is saved locally as pending.
4. Payment request includes a `receipt` item for the GOE package.
5. YooKassa sends webhook to `/yookassa/webhook` or the compatibility alias `/webhook/yookassa`.
6. Handler fetches payment details from YooKassa.
7. Handler verifies:
   - payment status is successful;
   - `paid` is true;
   - metadata order id matches when present;
   - amount matches local transaction.
8. Credits are added idempotently.

## Receipt Notes

YooKassa returns `Receipt is missing or illegal` when online receipts are enabled but the
payment request has no valid `receipt`. The app sends:

- `receipt.customer.phone` when `YOOKASSA_RECEIPT_PHONE` is set;
- otherwise `receipt.customer.email`;
- one `receipt.items[]` entry equal to the GOE package amount;
- `vat_code`, `payment_subject`, and `payment_mode` from env.

## Manual Checks

```bash
curl -fsS https://2loop.chillcreative.ru/api/miniapp/health
journalctl -u 2loop-bot.service -n 100 --no-pager | rg -i yookassa
```

Check pending transactions:

```bash
cd /root/2loop
venv/bin/python scripts/poll_yookassa_pending.py
```
