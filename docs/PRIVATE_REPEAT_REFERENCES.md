# Private references in ordinary image repeats

Ordinary image publications now have two independent owner controls:

- **Public references:** the existing visibility switch and per-image/video publication selection determine which source previews and links are published.
- **Private image-repeat permission:** a separate image-only selection permits the server to reuse these particular original images in other users’ repeats. It does not publish their previews or links. The author must explicitly select them; old public-reference selections never enable this permission.

## Permission and withdrawal

`generation_tasks.feed_repeat_reference_selection` is nullable JSON containing an `images` URL snapshot. The migration is additive, with no backfill. The owner publication API accepts `repeat_reference_image_indices`; an omitted, null or empty selection grants no private reuse. Owner task detail returns only indices in `feed_repeat_reference_selection`, using the existing canonical source-index mapping. Public cards do not include the grant snapshot.

Only an original, completed image generation may supply a grant. Published repeat/trend results are also repeat sources: use the selected result’s server-side prompt and require the next consumer’s replacement files. Root lineage is retained for accounting; the immediate publication is the permission boundary. Owner Telegram repeats of a child retain provenance and re-check the original permission. Foreign callers cannot edit it. Child/legacy remix rows cannot re-authorize inherited inputs. Each new provider submission checks the current original publication, exact selected URL membership, and availability. A persisted child snapshot records inputs to re-check, never permission by itself. Revocation or missing assets reject the affected new repeat/retry rather than silently changing its composition. Already submitted generation requests cannot be recalled from a provider.

Hiding public previews does not revoke the separate private-use permission. To revoke reuse, clear the private-repeat selection or withdraw the whole publication. Removing only the feed placement while retaining the published profile leaves the publication shared. Full withdrawal clears the grant. Re-publishing from an older client with no private-use field also clears it, fail-closed.

## Data boundaries

Private refs enter only the server-side generation recipe and provider input. They are excluded from child task detail, recent task history/bootstrap, public/owner child cards, restored selectable FSM inputs, and user-facing errors. Server logs retain IDs, counts and sanitized error categories without source URLs. The original author still has their own source images in owner task detail.

Ordinary image repeats preserve the original image positions used by `ImageN` prompts. Selected original images retain their slots; new images fill replaced slots in order. Missing required replacements or a combined model limit violation is rejected before generation. Seedance trend hidden/fixed reference behavior is separate and unchanged.

Public reference-media responses now use `Cache-Control: private, no-store`, and both thumbnail/full routes re-check current visibility even if an on-disk thumbnail already exists. Previously downloaded or previously cached assets cannot be erased retroactively by changing these headers. This is not a promise of retroactive deletion from third-party caches.

## Verification and release

All automated checks use synthetic URLs/assets and mocked providers. No paid generation or real customer private-asset reads are part of this implementation. See the execution ledger for exact tests, review findings, and release status. Merge/deploy requires separate authorization.


## Repeat integrity (2026-10-07)

Image creation and Feed remix now assemble the same authorized recipe. A repeat
whose slots are all explicitly fixed does not require an extra uploaded photo.
Owner-selected inputs retain their original ImageN positions; a missing earlier
replacement rejects before billing rather than shifting a later fixed object.

Video repeats likewise reject incomplete fixed-reference slots or failed recipe
restoration before reaching the generation handler. Private inputs remain server-side.
Known canonical and legacy local-upload aliases represent one source identity for
permission checks; unrelated external hosts do not. Existing grants/revocation and
reference-display settings retain their separate meanings.

## Ordinary video replacements (2026-10-21)

For foreign ordinary-video repeats, the authenticated request boundary uses the
publication's prompt and requires the consumer's files for every replaceable
source slot. A missing/legacy repeat grant grants no implicit provider use:
consumer descriptors mark the source slots as `upload`; absent, failed or partial
uploads reject before billing. Public reference visibility alone does not
constitute repeat-use consent. The original owner's own editable source flow
remains available. Explicit current fixed-slot grants keep their separate,
server-validated contract; no migration or silent grant is written to old posts.

Old Telegram callbacks redirect foreign legacy videos to this same Mini App
replacement flow. A derivative with a missing parent fails closed and cannot
fall through to replaying inherited private media from its saved request.


## Publishing generated results

Every authenticated user can publish their own completed image/video result to
Feed and Profile, including curated trend runs and repeat/remix results. Output
publication does not depend on whether the underlying prompt is private.
Task-detail publication controls therefore remain available with `prompt_hidden`.
Copying/exporting a private prompt stays unavailable; prompts and inherited
reference URLs are never included in the published result or child task DTO.
Private descendants cannot grant inherited inputs to the next consumer.

The legacy prompt-text privacy heuristic recognizes the original author of an
approved trend: publishing that trend does not hide their ordinary source works.
Explicit trend/lineage/private-recipe markers still take precedence. Other
users' legacy trend recipes retain privacy matching and fail-closed lookup.

Completed private Genjutsu results can publish through the existing output
publisher with the executable plan kept server-side. Their published repeat
contract requires a new consumer video and each photo, including slots that were
fixed in the ancestor recipe. Publication verifies ownership of the final output,
completion, quote integrity and mutable privacy state; it does not transfer the
ancestor's fixed files or disclose the hidden plan.
