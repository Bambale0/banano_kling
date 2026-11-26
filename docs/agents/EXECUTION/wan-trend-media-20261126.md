# WAN publication media incident — 2026-11-26 14:55 MSK

Baseline tanyapi / deployed Docker revision: `12c9183f5e891514665bbd50274bd1702ae085dc`.
Acceptance: existing WAN cards display durable posters and live clips; future
manual and generated WAN publications prepare media without changing Seedance.

## Evidence and preflight

- Production PostgreSQL rows: 2675 «Горы» (manual, 26 Nov 10:34 UTC),
  2653 «Ты на меня смотри 😍 ❄️», 2652 «😍😍😍», 2654 «Я давала шанс»
  (generated, 22 Nov). All approved/public WAN3. Seedance control 2674.
- Read-only `enrich_cards` probe reproduced failure: all four have durable live
  clips, none has a poster; control has both. Assertion requiring both assets
  failed. `LivePreview` requires poster AND compact clip before autoplay.
- Both WAN publishers INSERT approved rows directly, bypassing
  `database.approve_prompt` and its post-commit media hooks introduced by #681.
  #683 reconciles live clips, but does not reconcile missing posters.
- Originals exist in S3 (3,142,600 / 11,197,123 / 7,496,918 / 5,333,561 bytes
  for 2675 / 2653 / 2652 / 2654), ffprobe decodes H.264 High/yuv420p + AAC LC.
  Seedance control also H.264 High/yuv420p + AAC LC. No evidence of codec loss.
- Runtime logs retained since container restart ~11:21 UTC do not cover the
  original publication times. No historical publication log claim is made.
- New isolated worktree preserves unrelated local VK work. Repository AGENTS,
  Bambale0/.agents systematic-debugging, Bambale0/skills diagnosing-bugs,
  Bambale0/claw frontend audit and anthropics webapp-testing guidance read.

## Recovery already performed

Called existing bounded `ensure_published_trend_poster` for exactly the four
approved/public WAN ids, without reapproval or republication. All four succeeded.
Before/after SHA256 snapshots of their complete user_prompts, private WAN recipe,
category membership and generation-run rows were identical. Only new JPEG assets
and poster manifest mappings were added. Enrichment then returned both assets
for all four. No original/recipe/counter/provider/payment mutations.

## Implementation plan and verification

1. Add real SQLite publisher regressions: generated/manual, both manual models,
   separate-connection post-commit visibility, replay/deactivation, fail-open.
2. Reuse existing bounded poster helper + live scheduler after both WAN commits.
   No frontend, Seedance, schema, pricing, provider or new config changes.
3. Focused regressions/lint, two-axis review, PR to tanyapi + native squash
   auto-merge under existing strict required CI. Never bypass required checks.
4. Verify exact merge SHA CI/deploy, Docker health, public media Range/MIME,
   poster decode and advancing live playback. Real iOS Telegram WebView requires
   an accessible iPhone session; headless browser cannot establish native proof.

Rollback: protected revert of code; added immutable poster/manifest assets can
remain. The bounded helper logs trend id/error class and fails open on S3 outage;
existing operator backfill remains retry mechanism. No data migration/admin change.

## Verified candidate

- RED: `pytest tests/test_wan3_publication_media.py -q --tb=short` through a
  Windows-only harness substituting POSIX directory fsync: 4 failures, each
  publisher never awaited poster preparation. An initial direct Windows run
  also hit the existing POSIX directory-fsync incompatibility in the manual
  fixture; the production filesystem code and committed tests were not altered.
- GREEN: the new regression plus `test_wan3_manual_trends`,
  `test_wan3_curated_trends`, `test_trend_catalog_publish_thumbnail`,
  `test_trend_catalog_live_video`, `test_trend_catalog_media_cache`: 40 passed
  with the same Windows filesystem harness. Linux CI must run without that
  harness. Changed-file Ruff, py_compile and Node syntax checks passed.
- Runtime prevention is 16 added lines in the WAN service: reuse bounded
  poster generation and tracked live scheduler after both transactions close.
- Two independent code-review axes (Standards/Spec) against `12c9183f...82e9c3bb`
  found no actionable issues. Known fail-open/backfill policy is unchanged.
- Live Chromium smoke on the real Mini App origin, 390×844 viewport, passed
  all four recovered cards: poster JPEG decoding, compact MP4 and full original
  playback with advancing time; all 12 asset Range probes returned 206 with
  correct Content-Type, Content-Range and JPEG/MP4 magic. Derivatives have no
  redirect. This is real-media verification, not a native Telegram UI claim.
- ffprobe of all four compact clips: muted H.264 Constrained Baseline,
  yuv420p, 4 seconds, moov before mdat, 61,215–173,310 bytes. Original URLs
  are stable unsigned uploads, not stored expiring provider links.
- Existing frontend lazy gate is the failure amplifier: without poster it
  deliberately attaches no grid video source. Creating the missing poster
  restores eligibility without removing lazy loading or its two-video limit.
- Server-to-public HTTP from the datacenter was denied by Cloudflare (403).
  Desktop Chromium/public HTTP succeeded; no change to origin policy was made.

Progress: production card recovery and real-media smoke green; code tested and
reviewed. Required protected CI, exact-SHA release and native iOS smoke pending.
