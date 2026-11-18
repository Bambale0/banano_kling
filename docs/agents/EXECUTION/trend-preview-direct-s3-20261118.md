# Trend gallery: remove redundant S3 redirect (2026-11-18)

## User-visible failure and evidence
- Production `neuromixbot.com` showed multiple blank Trend cards after #597/#598.
- Public `/uploads/trend-previews/catalog/*.jpg` returns temporary HTTP 307 signed redirects with `Cache-Control: private, no-store`; each card incurs backend + S3 hops.
- In the inspected Nginx access log sample, poster requests included intermittent 502. A separate direct GET probe confirmed 206 image/jpeg on normal S3 responses; HEAD signed with a GET URL is invalid and is not a frontend failure.
- Gallery's first nine catalog cards have compact post JPGs (9–47 KB), except trend #2595, which was backfilled with a 70,639-byte JPG in production; subsequent backfill dry-run reported total_visible=0.
- Measured sequential production poster GETs: 0.268–1.071 s (includes both hops).

## Fix
1. Keep durable `preview_poster_url` unchanged; expose an optional `preview_poster_fast_url` signed locally (no S3 HEAD/GET in catalog reads). Only allow known-host public `/uploads/trend-previews/` image paths.
2. Deduplicate signing per catalog page and perform it off-loop; cache signed public-poster URLs for at most half of the configured S3 signature TTL with a bounded process-local cache. Failures leave stable poster URLs intact.
3. Mini App prefers fast URL, falls back to durable `/uploads/` poster on expiry/network failure, then to existing original photo or video icon.
4. After IntersectionObserver admits a tile, immediately request its small poster; offscreen tiles still attach no media URLs. Full MP4 never loads in the grid.
5. Preserve auth, payment, pricing, recipes, originals, storage configuration, and the stable API fields.

## Follow-up performance measurements
- Five production public JPEG GET probes returned `206` each; old `/uploads/` 307 chain measured 214–793 ms while the equivalent direct signed GET took 124–140 ms. Sequential small-range probes; not a WebView benchmark.
- Signing 99 distinct existing catalog posters in a cold process took about 221 ms (2.2 ms/poster). A bounded process-local cache was added before release to avoid repeat catalog latency. Cold start still pays one-time signature construction; direct S3 requests avoid the subsequent redirect. Verify API p95 after release.
- In the Nginx sample, poster 502 responses cluster at 16:34 UTC during an app release; no continued 502 pattern in subsequent sampled minutes.

## Acceptance / release plan
- Backend tests: deduplication, public-only signing, stable fallback on signing outage, manifest semantics.
- Frontend tests: direct poster preference, expired-link fallback for photo and video, no offscreen media.
- Protected PR CI: Python/deploy validation, safe regression, browser E2E, production Docker image; audit/security gates must remain enabled.
- Deploy only via merge to `tanyapi`. Verify exact production SHA, static Mini App revision, health, first-load card render and media status/timing.
- Monitor 502 rates for poster requests and frontend load errors after deployment.

## Risks
- Signed S3 GET links expire (existing `MEDIA_S3_PRESIGN_TTL_SECONDS`); fallback is intentionally stable and must be exercised.
- Native browser/Telegram WebView timing was not captured with user-session credentials; verify real browser smoke before claiming visual issue resolved.
- Do not cache signed redirect beyond token TTL and never expose signed originals as durable URLs.
