# 2026-11-21 — Systemic missing Trend poster assets

## Reproduction / production evidence
- Audited the latest 180 distinct approved, visible public Trend rows, including 137 videos and 43 photos.
- Initial state: 76 videos and 28 photos had neither a local preview poster nor a catalog manifest mapping; 16 video posts had local poster derivatives and 45 videos / 15 photos had durable manifest entries.
- The catalog deliberately never calls S3 or FFmpeg on reads. New approval via `database.approve_prompt` committed the row without creating a durable catalog thumbnail. Existing offline operator backfill was not run on every new publication.
- `#680` fixed one UI defect (video overlay) and merged, but it does not create missing JPGs.
- The production poster route `/uploads/trend-previews/catalog/<hash>.jpg` returns `200 image/jpeg` with no redirect. Pilot for posts 2637/2636/2641 proved this at the real origin.

## Reconciliation already performed on production
- Bounded S3 checks and generator/backfill batches: 3 + 18 + 25 + 25 + 25 + 8 = **104 new JPEGs** persisted.
- Each bounded batch reported 0 failures, and a subsequent DB lookup found 180/180 sampled rows with local or durable manifest posters. Original MP4/image files, recipes, payments, and balances were untouched.
- Disk before bulk: 197 GiB free of 871 GiB on production volume; batch source size ceiling used 35 MiB to constrain resource use.
- These are DB/persistence checks; all 180 individual browser renderings and links were not tested individually.

## Prevent recurrence
- Common `database.approve_prompt` path used by Telegram, Mini App and Seedance administration now calls `ensure_published_trend_poster` only for approved, public, tagged Trends, after DB commit.
- Shared bounded, idempotent `generate_thumbnail` pipeline: S3 HEAD size guard, first-frame JPEG or image resize, S3 persistence, manifest commit after upload; no hot catalog S3 calls and no original rewriting.
- Existing manifests short-circuit repeated conversion. Technical timeout `TREND_CATALOG_PUBLISH_POSTER_TIMEOUT_SECONDS` defaults to 15 seconds (clamped 3–45). Per-process semaphore limits conversions to 2.
- Failure is logged with trend ID and error class, without private URLs, and cannot revert committed approval; the offline backfill remains fallback for S3 outages.
- Security and privacy: skip pending, private, non-trend and external sources.

## Tests and release gates
- New regression tests cover video, photo, MOV, manifest dedup, private/pending/nontrend/external exclusion and timeout/provider failure fail-open.
- Python regression tests, protected CI (Python/deploy validation, safe regression suite, browser E2E, Docker image) and native squash auto-merge to `tanyapi` only.
- After merge: verify exact backend and frontend deployed SHA, health, the catalog/preview HTTP contract on random categories, a newly approved public test Trend, logs and disk; avoid synthetic paid generations.
- No frontend change in this PR; the separate #680 handles black video overlay. Preserve release branch protection.

## Known risks
- S3 outages or very large originals can exceed the bounded synchronous publication thumbnail deadline and require the existing offline backfill. The approach intentionally prefers publishing success and a visible fallback icon to rolling back user content.
- First-run latency grows by the poster creation time for approved Trends. Monitor approval p95 / timeout logs.
