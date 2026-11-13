# WAN 3.0: production provider routing (2026-11-13)

## Purpose
Move supported **Wan 3 Video** and **Wan 3 Video Prime** requests to the
native Neironych API without changing customer prices, model labels, repeat
recipes, historical KIE tasks or exactly-once credit settlement.

Baseline: `tanyapi` `95a9fd85742cc298e8296287a1ce671af54d024b`.
Neironych public `GET /v1/models` returned HTTP 200 with both `wan-3`
and `wan-3-prime` on 2026-11-13. No `wan-2.7` model was listed, so
**Wan 2.7 Image stays on KIE** pending an actual provider contract.

## Provider selection
- Database setting `wan3_primary_provider` overrides `WAN3_PRIMARY_PROVIDER`
  (default: `neironych`). Set value `kie` for immediate rollback of *new*
  submissions without changing source or reprocessing in-flight jobs.
- Neironych requires existing `NEIRONYCH_API_KEY` and
  `NEIRONYCH_API_BASE_URL`. No secret is committed.
- The native API receives `POST /v1/videos/generations` with
  `model=wan-3` or `wan-3-prime`, native reference objects and a stable
  `Idempotency-Key=internal_task_id`.
- In-flight Neironych request IDs are persisted with `neironych:` prefix.
  Old/unprefixed KIE IDs always poll KIE, regardless of later configuration.
- Native `GET /v1/videos/{request_id}` is polled by the existing durable
  Wan 3 reconciler; `/content` is downloaded using authorization to a
  bounded local file and stored via the existing S3 media persistence path.
  Native callbacks are not assumed to exist.
- An uncertain paid native POST is **not** retried through KIE. Recovery uses
  the stable idempotency key; do not make a new paid request without provider
  acceptance reconciliation.
- Failure, reserve/refund, trend and delivery remain in the current Wan 3
  lifecycle, with the actual provider recorded in generation task metadata.

## Contract gaps / preserved KIE compatibility
Native **Wan 3 Standard** supports text, references, frames and edit.
Native **Wan 3 Prime** supports text/reference but **not** edit, frames,
adaptive ratio, seed, silent video, or auto-duration. The Prime native
contract also requires duration >= 4 and ratios 16:9, 1:1 or 9:16.
File/link inputs and unsupported flags remain on KIE for both variants.
Such requests do *not* silently lose inputs, change model identity, or
become Standard while sold as Prime. Provider catalog unavailability before
a POST also uses the existing KIE route.

Note: the current Prime UI defaults to `adaptive`, and that request is
KIE-routed unless the user selects a native-supported ratio. Full removal
of KIE requires parity in Neironych or an approved product contract change.

## Smoke and release
1. Contract tests: `pytest tests/test_wan3_neironych_runtime.py` and
   `pytest tests/test_wan3*.py`.
2. Protected `tanyapi` gates, production image and browser E2E.
3. Verify both models in `GET /v1/models`, production config presence
   (never print key), exact deployed SHA, HTTP health and poll/delivery.
4. Run an explicitly authorised paid non-user smoke, then correlate
   internal task ID, native `request_id`, final S3 URL and delivery.
   Do not claim paid E2E was performed if it was not.

Rollback: set `wan3_primary_provider=kie` for future tasks only. Never
rewrite provider identifiers of existing intents. Preserve native poll access
until all Neironych tasks are settled.
