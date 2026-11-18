# 2026-11-18 — Blank Trend cards after #617: same-origin poster response

## Reproduction and evidence
- User screenshot 2026-11-18 21:44 shows all six first-row thumbnails and photo references blank while labels and prices render.
- Production static/backend revision 8ba493696aa83d030bf75636b23290662e00936a includes #617.
- #617 made Mini App prefer direct signed S3 host. Durable /uploads poster fallback also returns HTTP 307 to that same S3 host, therefore it cannot recover when the browser cannot reach the S3 hostname.
- Server-side S3 GET delivered a valid 8,780-byte JPEG in 163ms. This does not prove browser-to-S3 connectivity. A failing browser network trace was not captured; root cause is a strongly supported routing design flaw, not proven specific client network block.
- All 114 current visible public thumbnails match catalog/six-digit folder + 24..64 hex JPEG naming, permitting narrow routing.

## Implementation contract
- Add dedicated aiohttp GET/HEAD route before generic S3 redirect for the public /uploads/trend-previews namespace, only hashed JPEG variants.
- Fetch bounded <=2 MiB S3 object in background thread, close response, confirm JPEG signature, send inline same-origin image/jpeg HTTP 200, public cache headers, no Location.
- Protect against arbitrary paths, private files, other extensions, oversized objects and temporary S3 errors, with explicit 404/413/503.
- Remove ephemeral preview_poster_fast_url from public catalog; stable preview_poster_url unchanged, so older cached frontend also uses same-origin route.
- Frontend never chooses signed S3 for thumbnails; preserve lazy viewport gating, full originals in dialog, and fallback icons/images.
- No DB mutation, payments, tariffs, Telegram auth, originals, domain changes.

## Verification
- Backend unit tests for valid JPEG and bounded range, 404 traversal/missing, 413 too-large, 503 network failures.
- Frontend regression blocks use of signed S3 poster URLs even if a legacy API returns one.
- Required protected CI and review before merge into tanyapi. Use native squash auto-merge.
- Post deploy verify exact backend image SHA and frontend revision, normal GET on first-row and reference images returns 200 image/jpeg with no 307, no S3 Location. Inspect Cloudflare cache and 5xx plus public Mini App health.
- Browser end-user rendering and timing need a real client trace for complete confirmation.

## Rollback and risk
- Revert PR to restore previous S3 redirect behavior if necessary; no original data changed.
- Origin downloads add backend load on cache misses. Monitor GET latency, concurrency, memory and S3 request rate.