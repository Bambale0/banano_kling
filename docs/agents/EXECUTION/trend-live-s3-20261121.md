# NEUROMIX — live video Trend grid previews (2026-11-21)

## Incident and evidence
Production audit of all 362 approved, visible, public Trends: 264 videos.
Only 43 video cards had local compact MP4 derivatives, while 221 rendered
static JPGs. S3 originals existed (sample: 18/18 valid HEAD, ~1.6–12.9 MiB).
The grid was intentionally limited to compact H.264 previews; the existing
local-only resolver returned the original URL when local files were evicted by
S3 migration. The poster recovery (#681) fixed black thumbnails, but not live
animations for 221 videos.

## Contract
- Public catalog keeps `preview_url` unchanged for full dialog, repeat, share.
- Adds optional `preview_video_url` for autoplay only; 4-second muted H.264
  baseline 480px/12fps/faststart, looped by browser.
- JPG renders immediately. New MP4 is hidden until `playing`; pause, stall,
  autoplay refusal, visibility or network failure falls back to JPG.
- One active conversion per runtime; at most two visible autoplay tiles per
  browser, nothing downloaded offscreen. Respect save-data/reduced-motion.
- Short media URL: /uploads/trend-previews/live/<32hex>.mp4 served from the
  Mini App's own origin with correct HTTP 206 Range, not S3 redirects.
- Strict hash-only public route (6 MiB cap), not an arbitrary S3 proxy.
- Durable source->short clip PostgreSQL/SQLite manifest; one batch lookup per
  catalog page. No S3 HEAD/FFmpeg on hot catalog requests.
- Newly approved public video Trends schedule background encoding after
  successful DB commit; periodic reconciler scans the committed public
  catalog after process restart, moving its cursor after failures to prevent
  head-of-line starvation.
- Operator CLI: `python -m scripts.backfill_trend_live_previews --limit 40`
  read-only; `--execute` explicitly starts uploads. Batch at most 200;
  per-file source cap 200 MiB, generated MP4 cap 6 MiB. Originals untouched.
- Technical encoding settings configured via env (duration 2–6 seconds,
  FPS 8–20, width 240–720, ffmpeg timeout 20–180 seconds). Defaults 4, 12,
  480, 90 seconds respectively. Runtime background batch and cadence also
  configurable through TREND_LIVE_RECONCILE_*.

## Risk / protection
- Anonymous GET is limited to hashed compact public derivatives, whereas
  full/private uploads still use the original signed S3 route.
- Never convert pending/private/nontrend/external source URLs.
- A failed generation is logged by trend id and exception class and does not
  roll back publication or debit any user; retry on next scheduler pass.
- Potential CPU/network cost during bulk backfill: run sequential and monitor
  disk/CPU/S3 errors. Existing JPGs remain visible.
- A user's WebView and external ISP blocking still require real device smoke;
  server-side HTTP 206 is necessary but insufficient.
- No checkout/auth/pricing/payment or original content modifications.

## Release
- Required protected Python/DB/safe regression/browser E2E/Docker image checks.
- Native squash auto-merge to `tanyapi`; exact-SHA production auto-deploy.
- Post-merge, perform dry-run, bounded media backfill and idempotent re-run.
- Verify /trends/catalog and /trends/category return both original and short
  URL, sample 200/206/416 public MP4 responses with correct MIME and no
  Location, ffprobe short H264 mute, JPG fallback, logs and release SHA.
- Keep a numeric count of video Trends without live derivatives. Do not claim
  264/264 unless confirmed from production DB.
