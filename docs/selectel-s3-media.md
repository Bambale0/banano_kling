# Selectel S3 for references and media

This runbook describes the additive migration from `static/uploads` to
Selectel S3. The application keeps the existing `/uploads/...` URL contract;
database rows do not need a URL rewrite.

Official provider references:

- [Selectel S3 API](https://docs.selectel.ru/api/object-storage-s3/)
- [Create and configure S3](https://docs.selectel.ru/s3/quickstart/)
- [Links and presigned URLs](https://docs.selectel.ru/s3/objects/obtain-link-to-object/)

## Storage model

```text
client/provider URL: https://neuromixbot.com/uploads/<relative>
                                      │
                                      ▼
backend /uploads route ── short presigned redirect ── Selectel bucket

internal validation/transformation ── bounded local materialization cache

new upload ── validation/transformation ── PutObject uploads/<relative>
```

The bucket remains private. Stable application URLs are stored in the database;
the backend turns each `/uploads/...` request into a short-lived signed Selectel
redirect, so normal media delivery consumes no local disk. S3 access keys and
temporary signed URLs are never stored in the database. Local materialization
is reserved for validation, transformations and provider adapters that require
a filesystem path.

## Selectel preparation

1. Create a dedicated production project and bucket in the selected pool.
2. Create a service user and S3 key limited to this bucket.
3. Grant only the object operations needed by the application for the
   `uploads/` prefix. Do not use an account-wide administrator key.
4. Record the current pool-specific S3 endpoint and region from the Selectel
   control panel. Do not infer them from examples.
5. Keep object versioning enabled during the first migration/cutover window if
   available for the selected bucket.

Selectel object ACL mutation is not supported. Access is controlled with IAM
roles and bucket policy. A public-read bucket is not required for the default
backend-proxy topology.

## Environment

```dotenv
MEDIA_STORAGE_BACKEND=s3
MEDIA_S3_ENDPOINT=https://REPLACE_WITH_POOL_S3_ENDPOINT
MEDIA_S3_REGION=REPLACE_WITH_POOL
MEDIA_S3_BUCKET=REPLACE_WITH_BUCKET
MEDIA_S3_ACCESS_KEY_ID=REPLACE_WITH_ACCESS_KEY
MEDIA_S3_SECRET_ACCESS_KEY=REPLACE_WITH_SECRET_KEY
MEDIA_S3_KEY_PREFIX=uploads
MEDIA_S3_PUBLIC_BASE_URL=https://neuromixbot.com
MEDIA_S3_FORCE_PATH_STYLE=1
MEDIA_S3_KEEP_LOCAL_CACHE=1
MEDIA_S3_CACHE_TTL_SECONDS=3600
MEDIA_S3_CACHE_CLEANUP_INTERVAL_SECONDS=900
MEDIA_S3_CONNECT_TIMEOUT_SECONDS=10
MEDIA_S3_READ_TIMEOUT_SECONDS=120
MEDIA_S3_MAX_ATTEMPTS=3
MEDIA_S3_PRESIGN_TTL_SECONDS=900
```

`MEDIA_S3_KEY_PREFIX=uploads` is a compatibility invariant. Changing it would
invalidate ownership checks and historical URL identities.

For Docker Compose production, put **only** `MEDIA_S3_ACCESS_KEY_ID` and
`MEDIA_S3_SECRET_ACCESS_KEY` in an untracked, root-owned `.env.s3` file
beside `compose.backend.yml` (`chmod 600`). Compose loads this optional
file after `.env` and `.env.postgres`; no credentials belong in the Git
repository or deployment logs. Set non-secret settings in `.env`.

## Safe rollout

1. Back up the environment file, database and `static/uploads` inventory.
2. Install/deploy the code while keeping `MEDIA_STORAGE_BACKEND=local`.
3. Add S3 settings and temporarily set
   `MEDIA_S3_KEEP_LOCAL_CACHE=1`.
4. Run a bounded dry run:

   ```bash
   python scripts/migrate_media_to_s3.py \
     --dry-run \
     --limit 100 \
     --manifest data/migrations/selectel-s3-dry-run.jsonl
   ```

5. Copy references first, then durable media. The command is resumable because
   equal-size remote objects are verified and skipped:

   ```bash
   python scripts/migrate_media_to_s3.py \
     --prefix refs \
     --prefix trend-assets \
     --workers 4 \
     --manifest data/migrations/selectel-s3-refs.jsonl

   python scripts/migrate_media_to_s3.py \
     --prefix feed \
     --prefix trend-previews \
     --prefix repeat-choices \
     --prefix wan3_prime \
     --prefix kling4 \
     --prefix seedance_fallback \
     --workers 4 \
     --manifest data/migrations/selectel-s3-media.jsonl
   ```

6. Verify every source object without writing:

   ```bash
   python scripts/migrate_media_to_s3.py \
     --verify-only \
     --workers 8 \
     --manifest data/migrations/selectel-s3-verify.jsonl
   ```

   Exit code `0` means every scanned non-empty source matches the S3
   object size and its application-provided SHA-256 metadata. Missing or
   mismatched checksums return a non-zero code. A separate sample GET/download
   audit is recommended before any future deletion of the original data.

7. Enable `MEDIA_STORAGE_BACKEND=s3`, restart through normal CI/CD, and verify:

   - `/health` reports `media_storage: s3`;
   - a new image, video and audio reference can be uploaded and reused;
   - provider generation can fetch the reference URL;
   - a new image and video result opens from task history;
   - feed media and thumbnails support `HEAD`, range/video playback and normal
     cache headers;
   - logs contain S3 put/materialize timings and no credential values.

8. Keep local source copies through the observation window. First preview the
   reclaimable set; this command does not delete anything:

   ```bash
   python scripts/reclaim_local_media.py \
     --manifest data/migrations/selectel-s3-reclaim-preview.jsonl
   ```

9. Local reclamation is a separate destructive step. After the exact-size
   verification, production smoke and explicit approval, run it with the exact
   configured bucket name:

   ```bash
   python scripts/reclaim_local_media.py \
     --execute \
     --confirm-bucket REPLACE_WITH_BUCKET \
     --manifest data/migrations/selectel-s3-reclaimed.jsonl
   ```

   Each file is checked against S3 size and SHA-256 metadata immediately
   before unlinking and then rehashed locally; missing or mismatched content
   blocks deletion and makes the command exit non-zero. Run an independent
   remote-download hash audit before any large-scale reclamation.
10. Set `MEDIA_S3_KEEP_LOCAL_CACHE=0`. Newly materialized cache files receive
    marker files and are removed by the bounded cache cleanup after
   `MEDIA_S3_CACHE_TTL_SECONDS`; отдельный worker запускается каждые
   `MEDIA_S3_CACHE_CLEANUP_INTERVAL_SECONDS`.

## Rollback

Before local reclamation, rollback is configuration-only:

```dotenv
MEDIA_STORAGE_BACKEND=local
```

Restart through the normal production workflow and verify reference upload,
generation, history and feed delivery. Do not delete S3 objects during rollback.
If local copies have already been reclaimed, first restore the required objects
with the migration inventory or an S3 download procedure, then switch to
`local`.

## Failure semantics

- In S3 mode incomplete configuration stops application startup.
- An upload is not reported successful until S3 persistence succeeds.
- S3 read misses return media unavailable; they do not silently use arbitrary
  external URLs.
- The migration command never deletes local files or database rows.
- The reclamation command is dry-run by default and never deletes an
  unverified or size-mismatched local file.
- Logs include backend, object key, byte count and duration, but never access
  keys or secret keys.
