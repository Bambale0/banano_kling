# Account-owned private photos (Draft native VK slice)

Baseline tanyapi@4f6387d65135b04a17c2d448ebeef793c5b08482. Implements the
account-owned reference portion of #408/#412 without a legacy Telegram actor.
No public/native generation, financial authority or production activation.

Reuse verified shared sessions and the current administrator-only preview gate.
Do not migrate saved_references/categories or manufacture Telegram users. Keep
one new metadata table for photos and original account ownership provenance;
canonical-account/merged-descendant access preserves both sides after consent.

Proposed private HTTP contract under `/mini-app/api/account-preview`:

- `POST /references`: exactly one multipart `file`; authenticate before reading
  and revalidate after normalization. Real image decoding, existing technical
  byte/time/pixel bounds, EXIF handling and PNG normalization; MIME is not proof.
- `GET /references?offset=N`: owner-scoped metadata and bounded pagination.
- `GET /references/{id}/content`: repeat authentication/ownership and return PNG
  bytes with no-store/nosniff; no token/query URL or public uploads path.
- `GET /references/{id}/thumbnail`: the same private boundary with a bounded
  normalized thumbnail, so a gallery does not download every full-size input.
- `DELETE /references/{id}`: idempotently remove an owned photo from the library;
  keep a tombstone/provenance and deny later library-content access. This is not
  a claim of erasing accepted historical generation inputs.

Metadata: opaque server ID, MIME, decoded dimensions, byte count and creation
time. Storage keys, local paths and ownership IDs are not client-selectable or
returned. A signed VK-only account must complete these operations with no new
legacy users row. Ordinary/revoked/expired/policy-denied actors remain denied.

Private files live under the existing persisted data volume, outside public
static/uploads and legacy orphan cleanup. Stage on the same filesystem and
normalize before final promotion/metadata commit. Clean staging only after its
worker finishes. Never delete a final file after uncertain commit/cancellation;
unconfirmed private files require later reconciliation, not unsafe compensation.
Public quota/retention/reconciliation is a release gate before ordinary activation.

The browser fetches authenticated Blobs and creates/revokes object URLs. A small
gallery reuses Input/Button design components; this avoids UploadArea's legacy
library and logging calls without widening that generator component. Default
Telegram behavior stays intact. Do not submit Blob URLs to a provider: later
native generation must resolve owned reference IDs through the server.

Tests: signed VK-only HTTP upload/list/media/remove, identity negatives,
actual JPEG/PNG/WebP decode, forged MIME/corrupt/oversized/pixel-bomb input,
merge/alias access, FS/DB failure and cancellation around commit, private file
containment, Blob cleanup and browser reload/removal without legacy API calls.
Use SQLite and the existing isolated PostgreSQL shared-account workflow. Preserve
Genjutsu normalization behavior while extracting only its pure image core.

Keep each decoder capacity permit until its real worker finishes even after
request cancellation. Initial multipart parsing is part of the upload deadline.
Verify the stored content and thumbnail hashes before returning bytes. The UI
uses finite deadlines, re-reads persisted metadata after uncertain mutations and
does not label failed authentication as an empty library. Linked VK photos stay
independent of the Telegram-only settings read, with server access checks intact.
