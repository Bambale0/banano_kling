# ADR: Selectel S3 as canonical media storage

## Status

Proposed

## Context

NEUROMIX currently keeps references and generated media in
`static/uploads`. Public URLs, provider payloads, database records, ownership
checks, preview generation and cleanup all depend on the `/uploads/...` path
contract. Local disk capacity incidents show that the server filesystem should
not remain the canonical durable store.

Selectel exposes an Amazon S3-compatible API. Its current documentation states
that objects are private by default, access is controlled by bucket policy, and
the API supports Signature V4, object CRUD, multipart uploads and presigned
URLs. Object ACL mutation is not supported.

## Options considered

| Option | Benefits | Costs / risks |
| --- | --- | --- |
| Redirect `/uploads/` to S3 only | Small serving change | Breaks local media validation, preview generation and repeat flows |
| Rewrite database URLs to a new S3 domain | Direct object delivery | Large data migration, rollback complexity, stale embedded URLs |
| Mount the bucket as a filesystem | Few code edits | Weak filesystem semantics, operational coupling, hard-to-observe failures |
| Storage module with S3 canonical objects and local materialization cache | Preserves contracts, testable, resumable migration | Requires call-site integration and cache lifecycle management |

## Decision

Introduce a storage module with `local` and `s3` adapters. In S3 mode:

- object keys retain the `uploads/<relative-path>` namespace;
- public application URLs retain `/uploads/<relative-path>`;
- successful writes require confirmed S3 persistence;
- normal media delivery redirects to short-lived signed S3 reads and does not
  consume local disk;
- local files are staging/cache, not the canonical durable copy;
- local-only consumers materialize a configured S3 object into the existing
  safe `static/uploads` layout;
- migration copies and verifies existing objects before any separate cleanup.

The production bucket will use an explicit bucket policy or origin proxy for
provider-readable HTTPS access. Expiring presigned URLs are not stored in the
existing durable database URL fields.

## Consequences

Positive:

- existing database values and public links remain compatible;
- rollback to the local adapter is configuration-only while local copies are
  retained;
- S3 behavior is isolated behind a small test surface;
- migration is additive and resumable.

Negative:

- media processing can incur an S3 download on cache miss;
- S3 availability becomes part of upload availability;
- bucket policy and Nginx/origin routing require deployment configuration.

Mitigations:

- bounded retries/timeouts and structured operation logs;
- deterministic cache keys and traversal protection;
- staged rollout: copy, verify, enable writes, switch reads, observe, then
  separately approve local reclamation.

## Revisit triggers

- private per-user delivery becomes a product requirement;
- media traffic warrants CDN direct delivery under a dedicated domain;
- cache volume or egress indicates that local transformation workers should
  use a separate derived-media pipeline.

## References

- https://docs.selectel.ru/api/object-storage-s3/
- https://docs.selectel.ru/s3/objects/obtain-link-to-object/
