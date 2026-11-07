# Preview delivery recovery — 2026-11-07

Baseline: tanyapi `9eda416c861f8634b28fd94c81f634a24b7de875`.

User-visible acceptance: published reference/trend thumbnails resolve to actual
media on both deployed Mini App surfaces, including the exact VK-origin image
copied from the user's failing Windows Telegram card.

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
- Initial canonical native/server failure was not established. UA classification
  distinguishes TelegramBot from Chromium clients; server 200 alone does not
  prove a card rendered. No native OOM/cache assertion or speculative patch.
- Root cause confirmed from the user's actual failed image address: the Windows
  Telegram card requests `https://vk.neuromixbot.com/uploads/refs/image/...png`.
  This exact public resource is among the three production smoke assets: VK
  returns SPA HTML; canonical returns a valid PNG. The missing VK upload route
  therefore directly explains the reported Telegram card failure too.
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
- Final local checks: 18 installer/production URL tests passed; Ruff and Node
  syntax passed; 7 existing deploy-contract functions passed through an isolated
  harness normalizing their Windows-only path issue (no source edits).
- Exact provisioned VK vhost was copied read-only into a temporary local fixture:
  installer dry-run retained all original bytes except the managed include and
  derived the verified 1888 upstream. Nginx validation/reload were intercepted in
  this local fixture; no host configuration was modified.
- Actual published-asset browser smoke: three canonical PNGs passed 206,
  image/png, signature and 1536×2752 full decode; VK failed on text/html as
  expected before the route repair. This is the concrete deployment acceptance
  regression; no paid request, user token or mocked media used.
- Independent Standards review found a regex custom-route bypass; Spec review
  found cross-server ambiguity and unbounded decode. All addressed, regression
  cases added; both independent rereviews are clean. Integrated current tanyapi
  `84df6be850dc0d9f7906354f8e08ff47b2ac099c` before PR.
- PR421 native squash auto-merge armed. First required Python check rejected
  the script's shebang without executable mode (Windows Ruff did not enforce
  EXE001); executable Git mode corrected. Strict protection remains true with
  all four required gates; no bypass or manual production change.
- User confirmed the Windows failure persists after reopen, then supplied the
  exact failed public VK image address without query/hash. Its response matches
  the already-reproduced HTML fallback; additional native telemetry is unnecessary
  for this fix and is excluded from the final change.
- Exact-SHA CI/release verification pending. Final scope remains routing,
  regression and real-asset smoke only; no speculative frontend source change.
