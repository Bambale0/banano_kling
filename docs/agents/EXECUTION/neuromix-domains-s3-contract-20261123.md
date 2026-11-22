# NEUROMIX — production domain and S3 contract

Status: confirmed on production after the 2026-11-23 configuration repair. Applies to branch `tanyapi` only.

## Canonical domain map

| Purpose | URL | Notes |
| --- | --- | --- |
| Public landing | `https://neuromixbot.com/` | Browser-facing product website |
| Website login | `https://neuromixbot.com/login` | Browser OAuth / payments entry |
| Telegram Mini App / web studio | `https://neuromixbot.com/mini-app/` | New bot `WebAppInfo` URLs and static JS |
| User-facing images, videos and references | `https://neuromixbot.com/uploads/<relative-path>` | Stable URLs, regardless of S3 backend |
| Browser's Mini App API | `https://neuromixbot.com/mini-app/api/...` | Same-origin Nginx reverse proxy |
| Backend API and inbound provider/payment webhooks | `https://tanyapi.chillcreative.ru` | Telegram webhook and provider callbacks |
| `tanyapp.chillcreative.ru` | Legacy compatibility **only** | Never generate new launch/media URLs on this origin |

**Important separation:** S3 is the **storage backend**, `neuromixbot.com` is the **public URL origin**. With `MEDIA_STORAGE_BACKEND=s3`, an `/uploads/...` request can respond with a short-lived redirect to a **private Selectel S3 object**. The application must persist the stable `neuromixbot.com/uploads/...` URL, **not** a presigned S3 URL. Keep historical media origins readable; do not silently rewrite data or delete legacy files.

`tanyapi.chillcreative.ru` is the receiver of server-to-server events (Telegram, generation providers, payment notifications). Do not confuse **payment web redirects** to `neuromixbot.com/login` with **inbound payment webhooks**, whose domain remains `tanyapi.chillcreative.ru`. Preserve provider-specific callback paths.

## Required production environment

The untracked, root-owned `/root/tanya/banano_kling/.env` (mode `0600`) supplies Compose values. Keep these non-secret settings:

```dotenv
MINI_APP_URL=https://neuromixbot.com/mini-app/
STATIC_BASE_URL=https://neuromixbot.com
MEDIA_S3_PUBLIC_BASE_URL=https://neuromixbot.com
WEB_AUTH_PUBLIC_ORIGIN=https://neuromixbot.com
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
MEDIA_STORAGE_BACKEND=s3
MEDIA_S3_KEY_PREFIX=uploads
MEDIA_S3_KEEP_LOCAL_CACHE=0
```

S3 endpoint, region, bucket, secrets, retry policy and cache TTL come from the existing environment/configuration — **do not hardcode credentials**. Do not change provider callback variables such as `PRODAMUS_WEBHOOK_URL` or `YOOKASSA_WEBHOOK_URL` to the frontend domain.

**Root cause of the November 2026 drift:** the running container had `MINI_APP_URL=neuromixbot.com`, but the source `.env` and `docker compose config` still resolved `MINI_APP_URL`, `STATIC_BASE_URL` and `MEDIA_S3_PUBLIC_BASE_URL` to `tanyapp.chillcreative.ru`. A container recreation would restore the wrong launch domain. Update source configuration **and** confirm the effective running environment; checking either alone is not sufficient.

## S3 durability and local disk

The application uses Selectel `uploads/<relative>` object keys with SHA-256 object metadata. A successful `persist_upload_bytes` / `persist_upload_file` writes to S3. `MEDIA_S3_KEEP_LOCAL_CACHE=0` disables *retained* copies from the storage adapter, but other upload/transformation paths first create local staging files and the application may materialize S3 objects for providers. Files marked `.<filename>.s3-cache` are eligible for the bounded TTL cache cleanup.

**Cache cleanup does not delete unmarked historical source files.** On 2026-11-23, production had approximately **338 GiB** under `static/uploads`, mainly `feed` and `refs`, despite S3 being enabled. This is not proof of S3 failure; fresh samples from each of `feed`, `refs/image`, `refs/video`, `wan3_prime`, and `trend-previews` had matching S3 object lengths and SHA-256 metadata. This was a **sample audit**, not a complete 338 GiB verification.

Never perform broad `rm -rf static/uploads` or bulk delete merely because S3 is configured. First produce a per-file manifest with local size/SHA-256 and remote `HeadObject` size/SHA-256, confirm every candidate and active writer behavior, preserve recovery copies, then delete only the verified safe subset under an explicitly reviewed cleanup plan. Unknown/missing/mismatched S3 metadata is **not** proof and must be excluded from deletion. Also inspect `backups`, application temp files, and Docker usage separately.

See [Selectel media runbook](../selectel-s3-media.md) for migration, verification and recovery.

## Minimal non-secret production smoke

```bash
cd /root/tanya/banano_kling
sudo docker compose -f compose.backend.yml config --quiet
sudo docker compose -f compose.backend.yml config --format json |
  python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["bot"]["environment"]; print({k:e.get(k) for k in ("MINI_APP_URL","STATIC_BASE_URL","MEDIA_S3_PUBLIC_BASE_URL","WEB_AUTH_PUBLIC_ORIGIN","WEBHOOK_HOST","MEDIA_STORAGE_BACKEND","MEDIA_S3_KEEP_LOCAL_CACHE")})'
sudo docker exec banano-kling-bot python -c '
from bot.config import config
from bot.services.media_storage import is_s3_enabled, public_upload_url
print("app", config.mini_app_url)
print("s3_enabled", is_s3_enabled())
print("media_sample_url", public_upload_url("refs/image/smoke-sample.png"))
print("webhooks", config.WEBHOOK_HOST)
'
curl -fsSI https://neuromixbot.com/mini-app/
curl -fsSI https://neuromixbot.com/login
curl -fsSI https://tanyapi.chillcreative.ru/health
```

For a **known existing** image/video, test `https://neuromixbot.com/uploads/<real-relative>` with GET + `Range: bytes=0-1023` and follow any S3 redirect; HTTP 200 on a landing page is not a valid media test. Inspect bot health, Telegram pending webhook queue, and recent payment webhook statuses after recreation.

A fresh `/start` bot keyboard reflects the current `MINI_APP_URL`; **previously sent** inline buttons retain their original Telegram `WebAppInfo` URL. Telegram's Main Mini App configuration is independent and must be checked in BotFather if relevant.

## Recovery

Back up `.env` outside the repository; keep its file permissions restricted. Change **only** the wrong origin keys, validate Compose, then when needed recreate only the bot using the **existing** image:

```bash
sudo docker compose -f compose.backend.yml up -d --no-deps --no-build --force-recreate bot
```

Verify image SHA is unchanged and bot health is green; re-check canonical App/Media URL and backend callback origin. Restore the backed-up `.env` only when the current changes are demonstrably harmful; avoid wholesale rollback to obsolete `tanyapp` URLs.
