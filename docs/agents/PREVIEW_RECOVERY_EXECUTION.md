# Preview delivery recovery — 2026-11-07

Baseline: tanyapi `9eda416c861f8634b28fd94c81f634a24b7de875`.

User-visible acceptance: published reference/trend thumbnails resolve to actual
media on both deployed Mini App surfaces. Canonical Telegram screenshot remains
under investigation; the confirmed VK routing failure is a separate finding.

## Preflight and diagnosis

- Runtime: Docker aiohttp/aiogram webhook, port 1888, PostgreSQL-backed runtime;
  configured DATABASE_PATH `/app/data/bot.db`, Redis loopback port 6379 database 0.
- Actual Telegram UI document is `https://neuromixbot.com/mini-app/` (parent's
  read-only UI inspection). The three public recommended original PNGs decode
  in actual Chrome there and on their recorded legacy origin. Sizes are 5–6 MB,
  dimensions 1536 × 2752. The serializer leaves image preview URLs unchanged;
  only local videos have cached MP4/JPEG derivatives. No Next image transform.
- Ranked hypotheses: (1) wrong media routing on a surface; (2) transformed URL
  or stale payload; (3) transient native network/cache error; (4) native decode
  pressure from large originals. Only (1) is reproduced: the same saved uploads
  on VK return 200 text/html with SPA bytes instead of PNG. The frontend uses
  same-origin uploads, while the provisioned VK vhost has no upload route.
- Canonical native/server failure is not established. UA classification must
  distinguish TelegramBot crawlers from Chromium clients; server 200 alone does
  not prove a card rendered. No native OOM/cache assertion or speculative patch.
- Existing deploy publishes TG and VK exports but manages no VK media route.
  Reuse its privileged exact-SHA CI deployment and existing API proxy upstream.

## Implementation and scope

1. Add regression at installer file/reload seam; reproduce RED before script.
2. Install a small managed `/uploads/` proxy include before the existing VK SPA
   fallback during ordinary frontend deploy. Derive upstream from existing API
   route, preserve other vhost bytes, atomically write files, run `nginx -t`,
   reload only valid config, restore both files if validation/reload fails.
3. Test idempotency, upstream changes, fail-closed custom routing, rollback.
4. Independent Standards/Spec review; protected PR + native squash auto-merge.
5. Verify exact merge SHA CI/autodeploy, health/static revisions and real media
   content type, PNG magic, full browser decode on both production origins.

No new business/config environment variable, media-domain hardcode, DB/schema
change, maintenance/backfill, financial/provider call, auth change, or Telegram
FSM change. Existing upload handler retains access and cache policy; no public
CDN redirect or new shared cache. Nginx configuration is the only runtime change.
Observability: deployment validates/logs route outcome; focused production log
inspection uses aggregate status/byte/UA families, never user auth or IP output.
Regression API/DB/provider/payment layers are not applicable to this routing-only
change. Browser acceptance must use real published assets, not mocked media.

Guidance read: Bambale0/skills diagnosing-bugs, implement, code-review;
Bambale0/claw UX audit; anthropics/skills webapp-testing.

## Progress

- RED: new installer regression could not collect because installer was absent.
- Installer regressions pass, covering idempotency, upstream changes, preserving
  vhost bytes, rejecting existing custom exact/regex routes, and both validation
  and reload rollback with/without a previous snippet. Changed-file Ruff passes.
- Broader deploy-contract check: 13 passed, 7 failed in the pre-existing
  `test_development_release_flow.py` because its POSIX-only `__file__.rsplit`
  creates nonexistent paths on Windows. This test file was not modified.
- Read-only invocation of the actual public `_card` serializer confirms all
  three recommended image URLs stay unchanged, no poster/query, kind and
  preview_type=image. TelegramBot is absent from the sampled asset access logs;
  Telegram-marked Chromium clients are Android, not this user's Windows client.
  Their full 200 bodies do not verify the reported Windows card rendering.
- Real production browser smoke script accepts public paths from environment,
  checks status/content type/PNG magic and full decode on both app origins.
  Before the routing change, canonical passes and VK fails on text/html.
- Independent review and exact-SHA CI/release verification pending. No production
  configuration has been changed manually.
