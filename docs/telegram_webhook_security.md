# Telegram webhook security

Production must start the bot through:

```bash
python -m bot.secure_main
```

The Docker image and maintained systemd templates use this entrypoint. Direct `python -m bot.main` remains available only for legacy development and does not install the authenticated bounded webhook adapter.

## Secret token

Preferred production configuration:

```dotenv
TELEGRAM_WEBHOOK_SECRET=replace_with_32_to_256_random_characters
```

Allowed characters are `A-Z`, `a-z`, `0-9`, `_` and `-`.

Generate a value with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

At startup the same value is passed to Telegram as `secret_token`. Every incoming request must contain the matching `X-Telegram-Bot-Api-Secret-Token` header before its JSON body is parsed or dispatched.

For backward-compatible rollout, if `TELEGRAM_WEBHOOK_SECRET` is absent, the runtime derives a stable 64-character HMAC secret from `BOT_TOKEN`. This is secure against callers that do not know the bot token, but an explicit independently rotatable value is preferred.

## Queue and deduplication

Defaults:

```dotenv
TELEGRAM_WEBHOOK_QUEUE_SIZE=256
TELEGRAM_WEBHOOK_WORKERS=4
TELEGRAM_WEBHOOK_MAX_BODY_BYTES=1048576
TELEGRAM_WEBHOOK_DEDUPE_TTL_SECONDS=86400
TELEGRAM_WEBHOOK_LOCAL_DEDUPE_LIMIT=20000
```

Updates are accepted into a bounded queue. When the queue is full, the endpoint returns `503` with `Retry-After: 1`, allowing Telegram to retry instead of creating an unlimited number of waiting `asyncio.Task` objects.

`update_id` is reserved atomically in Redis with `SET NX EX`. If Redis is unavailable, the runtime uses a bounded in-process TTL cache. Redis is required for deduplication across restarts or multiple instances.

## Rollout checklist

1. Add `TELEGRAM_WEBHOOK_SECRET` to the production secret store or `.env`.
2. Deploy the image or systemd unit using `bot.secure_main`.
3. Confirm startup log contains `Telegram webhook registered with secret token`.
4. Confirm a request without the secret header receives HTTP `403`.
5. Confirm the Telegram bot receives a normal `/start` update.
6. Watch queue-full, Redis fallback and invalid-secret warnings during the first rollout.

Never log or expose the configured secret.