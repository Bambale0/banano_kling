# NEUROMIX Trends catalog loading reliability — 2026-11-18

## Production reproduction
- The screenshot shows a spinner in Trends with a live authorized session (admin category buttons visible).
- Production bot Docker revision 0b039ca2590dfa0acd71b6df77b3bd1367bee128 was healthy, but POST /mini-app/api/trends/catalog sometimes took 2–7.5 seconds despite HTTP 200; some client-disconnected requests logged 200 with zero response bytes.
- A real read-only catalog profile returned 20 folders, 114 cards and approximately 126 KB JSON. A non-admin cold read took 2.66 seconds with one folder accounting for 2.30 seconds; an admin read took 0.575 seconds. Under load the API showed several 4–7.5-second responses.
- Production logs separately show S3 404 for specific older reference/poster objects. Missing individual media is not proof of a catalog API failure.
- Original frontend fetch had no abort deadline; a failed modern catalog read entered an additional heavy legacy fallback. This could keep the loading spinner alive indefinitely if the network stalled.

## Fix
- Short, bounded, process-local catalog cache keyed by role, creator tariff and per-category limit. Concurrent identical reads are coalesced; admin category mutations invalidate cached results immediately.
- Read-only catalog/category API calls get a 10-second abort deadline, including slow response JSON bodies. Admin mutations have no artificial abort deadline to avoid uncertain-write retries.
- Network/auth/timeouts no longer invoke the legacy prompt-list fallback; the spinner terminates, an actionable message appears and the user can retry. Only explicitly unsupported catalog contracts invoke the old fallback.
- Keep S3/preview errors isolated to per-card media placeholders and the existing thumbnail backfill workflow; do not fabricate missing assets.

## Verification
- Two new backend cache regressions were red before fix, then green. Existing trend API/editor test suite also passed (29 tests).
- Frontend simulated never-resolving fetch with abort and successful fetch timer cleanup.
- Mobile showcase E2E exercises first catalog network failure, clear error/retry, then normal cards/categories.
- No user balances, database rows, prompts, or uploaded S3 objects were modified.

## Release
- Task branch -> PR into protected tanyapi -> checks -> autodeploy -> check exact production SHA, /health and catalog latency.
- Keep Astro PR #615 separate and preserve its work.
