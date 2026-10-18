# Reference loss recovery — 2026-10-18

## Confirmed incident

The October 11 application log explicitly records generic upload cleanup deleting content-addressed `static/uploads/trend-assets` originals. The current baseline already excludes this directory, but did not restore the deleted files. On October 18 all 17 persisted asset rows (15 unique files across nine templates) initially pointed to missing files. Recent `trend_run_claims.response_json` confirmed missing-reference launch failures after a successful price quote.

## Implemented safeguards

- Keep typed Seedance image/video/audio bindings. Missing `@ImageN` is never implicitly converted into another media type; legacy combined-ordinal conversion is available only through explicit helper opt-in.
- Validate all user and fixed references before quote or launch. Return `missing_user_reference`, `missing_trend_reference`, or `missing_reference_binding` without exposing author asset URLs. Log trend, actor, stage and stable rejection code.
- Removing a saved-reference shortcut only removes the library row. Physical reclamation is deferred to an ownership-aware collector.
- The collector reads nested references from all generation states and media types, repeat selections, result lists and template settings, including dated upload directories, plus saved references, previews and durable asset rows. Malformed owner JSON aborts the collector before deletion. Unowned aged files remain reclaimable; the initial blanket-disable proposal in PR #326 is superseded.

## Restoration utility

`scripts/restore_trend_assets.py` reads asset metadata through a read-only PostgreSQL connection. It scans explicitly supplied source roots and accepts only matching full SHA-256 and byte size. Default mode is dry-run. `--apply` stages each exact file, verifies it again, publishes without overwriting a destination, fsyncs, and writes a private per-run JSONL receipt. It never changes task rows, slot order, balances or template metadata.

```sh
python scripts/restore_trend_assets.py \
  --source-root /path/to/retained/originals \
  --media-root /path/to/project/static/uploads/trend-assets \
  --receipt /private/diagnostics/unique-run.jsonl
```

Supply the existing database connection through the runtime environment; never paste it into logs or command arguments. Review the dry-run, then run with `--apply` and a new receipt path. Receipts include private source paths and must not be committed. A missing source is reported, not replaced with a lookalike. Existing differing files are preserved and reported as errors.

## Observed recovery

Eleven unique originals were restored, resolving twelve asset rows for six templates. File hashes, local and public HTTP availability, and the production Seedance payload preflight for all six templates were verified without paid requests. Four unique originals/five rows across three templates were not found in retained upload/data directories, checked workspaces or the public cache (404). Examined predeployment archives contained PostgreSQL data, not media bytes; a database backup alone is not proof that original media can be restored.

An independent read-only production query validated the new PostgreSQL ownership traversal (145,565 URLs). New isolated regression cases prove protection of active/failed/completed video and audio inputs, nested recipe slots and draft template references, while existing orphan-reclamation tests remain unchanged. Run the full safe suite and CI before release; do not infer production deployment from a PR or recovery receipt.
