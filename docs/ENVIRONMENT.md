# Environment

Production uses `/root/2loop/.env`, loaded by `2loop-bot.service`.

Never commit real secrets. Use this file as a reference, not as a copy-paste of production
values.

## Required

```env
BOT_TOKEN=
ADMIN_IDS=7736745862,339795159

WEBHOOK_HOST=https://2loop.chillcreative.ru
WEBHOOK_IP=217.11.166.233
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8443
```

## Static And Mini App

```env
TWOLOOP_DATA_DIR=/root/2loop/data
TWOLOOP_UPLOAD_DIR=static/uploads/2loop
TWOLOOP_VERIFY_INIT_DATA=1
TWOLOOP_ADMIN_IDS=${ADMIN_IDS}
TWOLOOP_ORDER_NOTIFY_CHAT_IDS=${ADMIN_IDS}
TWOLOOP_STATIC_ROOT=/var/www/2loop/static
TWOLOOP_UPLOADS_ROOT=/var/www/2loop/static/uploads
```

`TWOLOOP_UPLOAD_DIR=static/uploads/2loop` is supported by code and maps product uploads to
`/var/www/2loop/static/uploads/2loop`.

## YooKassa

```env
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://2loop.chillcreative.ru/shop
YOOKASSA_WEBHOOK_SECRET=
YOOKASSA_RECEIPT_EMAIL=payments@2loop.chillcreative.ru
YOOKASSA_RECEIPT_PHONE=
YOOKASSA_VAT_CODE=1
YOOKASSA_PAYMENT_SUBJECT=service
YOOKASSA_PAYMENT_MODE=full_prepayment
```

Webhook URL:

```text
https://2loop.chillcreative.ru/yookassa/webhook
```

Production also accepts the legacy alias:

```text
https://2loop.chillcreative.ru/webhook/yookassa
```

If YooKassa online receipts are enabled, each payment request must include `receipt`.
The code builds one receipt item for the GOE package. Set either `YOOKASSA_RECEIPT_PHONE`
or `YOOKASSA_RECEIPT_EMAIL`; phone has priority when both are set.

## Robokassa

```env
ROBOKASSA_MERCHANT_LOGIN=
ROBOKASSA_PASSWORD1=
ROBOKASSA_PASSWORD2=
ROBOKASSA_TEST=0
```

Robokassa URLs:

```text
https://2loop.chillcreative.ru/robokassa/result
https://2loop.chillcreative.ru/robokassa/success
```

## AI Providers

```env
KIE_AI_API_KEY=
KIE_AI_WEBHOOK_PATH=/webhook/kie_ai
KIE_AI_WEBHOOK_SECRET=
KIE_AI_REQUIRE_WEBHOOK_SECRET=1
KIE_BASE_URL=https://api.kie.ai

NANOBANANA_API_KEY=
GEMINI_API_KEY=
FREEPIK_API_KEY=
NOVITA_API_KEY=
KLING_API_KEY=
PIAPI_API_KEY=
REPLICATE_API_TOKEN=
REPLICATE_WEBHOOK_SECRET=
ALLOW_NSFW=0
```

Kie.ai webhook URL:

```text
https://2loop.chillcreative.ru/webhook/kie_ai
```

## Data

SQLite uses `DATABASE_PATH` from `bot/database.py`. If `DATABASE_PATH` is not set, the
default is:

```env
DATABASE_PATH=bot.db
```

With `WorkingDirectory=/root/2loop`, the production database is therefore:

```text
/root/2loop/bot.db
```

`TWOLOOP_DATA_DIR=/root/2loop/data` is used by the JSON-backed Mini App storage, not by the
main SQLite database unless `DATABASE_PATH` is explicitly changed.

Recommended production value for clarity:

```env
DATABASE_PATH=/root/2loop/bot.db
```

Before changing this value, stop the bot and copy the existing database to the new path.
