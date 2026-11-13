# Mini App privacy bootstrap fastpath — 2026-11-13

## Evidence and objective

Production Mini App bootstrap p95 exceeded six seconds after PostgreSQL
watchdog and VK delivery-scan hotfixes. Slow-stage telemetry showed
`task_privacy` frequently waiting multiple seconds. Direct PostgreSQL
EXPLAIN showed the legacy approved-trend recipe scan itself takes ~5 ms
on 2553 prompt rows; connection acquisition/concurrency is the costly
part under production load.

## Fix and security invariants

`sanitize_task_api_payload` now passes only *unresolved* task IDs to the
legacy classification lookup. A task that `generation_has_private_recipe`
already classifies as private cannot become less private when the database
is queried, so its request/prompt/source links remain redacted without
another DB trip. Ambiguous/public tasks must still be checked against
historical curated trends. On lookup failure, all IDs are still redacted
(fail-closed).

No changes to SQL query semantics, user data, payments, permissions or
retention.

## Verification

New regression tests first failed on the old code and passed after fix:
- All-explicitly-private batch performs **no** legacy DB lookup.
- Mixed batch looks up only unresolved task IDs, keeps public originals,
  and redacts both explicit and historically protected recipes.

146 trend privacy/repeat/hidden prompt/Wan3 contract tests passed locally;
Ruff and diff whitespace passed. Post-merge exact-SHA CI and deployment
required; verify production event/bootstraps p50/p95 and cache/pool warnings.
