# Reference loss recovery — 2026-10-18

## Confirmed risk

`cleanup_orphaned_reference_files` previously considered saved references, prompt previews, and selected completed-generation image fields. It did not establish complete reachability across all Studio works, trend assets, repeat configurations, in-flight jobs and all video/audio reference fields. A file could therefore be incorrectly classified as orphaned.

## Containment

Suspend orphan reference file deletion until the complete ownership graph is implemented and tested. This does not restore already missing files or prevent unrelated cleanup paths; audit all cleanup entrypoints separately. No user DB rows are changed by this patch.

## Recovery sources found on host

- `backups/predeploy-20261012*` through `predeploy-20261015*` PostgreSQL dumps
- `backups/postgres-latest.dump` (2026-10-18)
- `backups/media-origin-before-20261007T072500Z.jsonl.gz`
- `static/uploads/refs`, `static/uploads/feed`, `static/uploads/trend-assets`

## Safe restoration requirements

Inventory live DB references and backups read-only; compare missing URLs with local files, snapshots and provider results. Restore into staging first with hashes, owners and ordinal positions verified. Back up live DB before any writes; apply only proven, idempotent mappings, then invalidate caches and smoke-test original Studio work plus Trend repeat. Do not delete or replace originals; do not promise 100% recovery until verified.

## Validation

`pytest -q tests/test_reference_cleanup_suspended.py`; run CI and production smoke after merge. The status of those steps must be reported from evidence, not assumed.
