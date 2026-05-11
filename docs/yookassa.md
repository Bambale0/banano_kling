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
4. YooKassa sends webhook to `/yookassa/webhook` or the compatibility alias `/webhook/yookassa`.
5. Handler fetches payment details from YooKassa.
6. Handler verifies:
   - payment status is successful;
   - `paid` is true;
   - metadata order id matches when present;
   - amount matches local transaction.
7. Credits are added idempotently.

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
