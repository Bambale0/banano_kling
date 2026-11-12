# Selectel S3: references and media

## Task

- Baseline: `e9587eb4c9d4e1ac7e0e8663ed1d8794f93bb182` (`origin/tanyapi`).
- Branch: `feature/selectel-s3-media`.
- Intended result: new references and durable generated media are stored in
  Selectel S3; existing `/uploads/...` URLs remain valid; existing local files
  can be copied and verified before any disk reclamation.

## Current-state audit

1. Production media is currently stored under `static/uploads` and exposed as
   `/uploads/...` by aiohttp and Nginx.
2. Personal references use `saved_references.file_url` and files under
   `static/uploads/refs`.
3. Durable feed results, trend assets, repeat choices and provider result
   copies also use `static/uploads`.
4. Many validation and preview paths reopen media locally. A redirect-only S3
   cutover would break those paths after local cleanup.
5. `bot/config.py` contains unused Cloudflare R2 placeholders but there is no
   object-storage adapter, S3 dependency, upload path or migration tool.
6. Existing database URLs are path-based (`/uploads/...`), so changing hosts or
   rewriting rows is unnecessary and increases rollback risk.
7. Selectel supports the Amazon S3 API, Signature V4, object CRUD, multipart
   upload and presigned URLs. Object ACL mutation is not supported and objects
   are private by default; access must be configured with a bucket policy.

## Reuse and prefactor

- Preserve `static/uploads/<relative-key>` as the local cache/staging layout.
- Preserve the public `/uploads/<relative-key>` contract.
- Add one deep storage module for local/S3 persistence, availability,
  materialization and deletion instead of distributing SDK calls across
  handlers.
- Route the existing media-input resolver through the storage module so
  S3-backed objects can be materialized for validation and preview work.

## Configuration and no-hardcode decisions

- Backend selection, endpoint, region, bucket, prefix, public base URL,
  credentials, path-style addressing and local-cache policy are environment
  configuration.
- Credentials remain secret and are never returned, logged or committed.
- `local` remains the default backend for safe rollback.
- `s3` mode fails closed when required settings are incomplete; it must not
  silently write only to local disk.

## Data, security and integration risks

- Bucket policy must grant only the intended read access. The application key
  needs object CRUD only for the selected bucket/prefix.
- Provider-facing references need stable HTTPS URLs; expiring URLs cannot be
  persisted in existing database fields.
- Migration must be additive and resumable: upload and verify first, never
  delete source files by default.
- S3 network failures must be visible in logs and must not produce successful
  database records pointing at missing objects.
- Cache materialization must reject traversal and only address configured
  `/uploads/` object keys.

## Public test seams

1. Storage interface: local and fake-S3 put/materialize/exists/delete behavior.
2. Personal-reference upload seam: saved reference URL is returned only after
   durable object persistence.
3. Media resolver seam: a missing local file is materialized from configured
   S3 storage.
4. Migration CLI seam: dry-run, upload, verification and non-destructive
   defaults.
5. Deployment/config seam: environment validation and Docker import checks.

## Implementation steps

1. Add failing storage/config tests.
2. Implement the S3-compatible storage module and Selectel configuration.
3. Integrate reference and shared media write/read paths.
4. Add a resumable migration/verification command.
5. Update deployment, environment, operations and rollback documentation.
6. Run focused tests, full safe regression gates, syntax/import checks and
   two-axis review against this ledger.

## Acceptance criteria

- S3 mode never reports a successful upload before `PutObject` succeeds.
- New personal references and durable media are present in the configured
  bucket under deterministic `/uploads/...` keys.
- Existing URL values do not require a database migration.
- Local consumers can reopen S3-only objects through a bounded local cache.
- Normal `/uploads/...` delivery redirects to a short-lived signed S3 URL and
  does not rematerialize the object on local disk.
- The migration command can resume, verifies remote size/metadata, and does
  not delete local files unless a separate explicitly authorized operation is
  performed.
- Local mode preserves existing behavior and tests.
- Logs identify operation, key, size, duration and failure without credentials.

## Progress

- [x] Baseline and dirty-worktree isolation verified.
- [x] Selectel S3 API and link behavior checked against official docs.
- [x] Backend, Mini App, Telegram, database, cleanup, CI/CD and media paths
      audited.
- [x] Storage tests and implementation.
- [x] Call-site integration.
- [x] Non-destructive migration, verified-reclamation tooling and docs.
- [x] Storage and migration regression suite: 369 passing tests across 24 files,
      including SHA-256 metadata verification; new-module Ruff and diff checks.
- [x] Confirmed Nginx routes /uploads through the bot for neuromixbot.com.
- [ ] Live Selectel credential/bucket preflight and small-object round-trip.
- [ ] GitHub CI checks, PR review and production deployment verification.
- [ ] Full migration/verify-only and provider-facing live smoke.
- [ ] Historical local-data reclamation: explicitly deferred by user.
