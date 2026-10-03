# Private references in ordinary image repeats

Ordinary image publications now have two independent owner controls:

- **Public references:** the existing visibility switch and per-image/video publication selection determine which source previews and links are published.
- **Private image-repeat permission:** a separate image-only selection permits the server to reuse these particular original images in other users’ repeats. It does not publish their previews or links. The author must explicitly select them; old public-reference selections never enable this permission.

## Permission and withdrawal

`generation_tasks.feed_repeat_reference_selection` is nullable JSON containing an `images` URL snapshot. The migration is additive, with no backfill. The owner publication API accepts `repeat_reference_image_indices`; an omitted, null or empty selection grants no private reuse. Owner task detail returns only indices in `feed_repeat_reference_selection`, using the existing canonical source-index mapping. Public cards do not include the grant snapshot.

Only an original, completed image generation may supply a grant. New Mini App repeats require that original author publication; legacy child publication sources are rejected. Owner Telegram repeats of a child retain provenance and re-check the original permission. Foreign callers cannot edit it. Child/legacy remix rows cannot re-authorize inherited inputs. Each new provider submission checks the current original publication, exact selected URL membership, and availability. A persisted child snapshot records inputs to re-check, never permission by itself. Revocation or missing assets reject the affected new repeat/retry rather than silently changing its composition. Already submitted generation requests cannot be recalled from a provider.

Hiding public previews does not revoke the separate private-use permission. To revoke reuse, clear the private-repeat selection or withdraw the whole publication. Removing only the feed placement while retaining the published profile leaves the publication shared. Full withdrawal clears the grant. Re-publishing from an older client with no private-use field also clears it, fail-closed.

## Data boundaries

Private refs enter only the server-side generation recipe and provider input. They are excluded from child task detail, recent task history/bootstrap, public/owner child cards, restored selectable FSM inputs, and user-facing errors. Server logs retain IDs, counts and sanitized error categories without source URLs. The original author still has their own source images in owner task detail.

Ordinary image repeats preserve the original image positions used by `ImageN` prompts. Selected original images retain their slots; new images fill replaced slots in order. Missing required replacements or a combined model limit violation is rejected before generation. Seedance trend hidden/fixed reference behavior is separate and unchanged.

Public reference-media responses now use `Cache-Control: private, no-store`, and both thumbnail/full routes re-check current visibility even if an on-disk thumbnail already exists. Previously downloaded or previously cached assets cannot be erased retroactively by changing these headers. This is not a promise of retroactive deletion from third-party caches.

## Verification and release

All automated checks use synthetic URLs/assets and mocked providers. No paid generation or real customer private-asset reads are part of this implementation. See the execution ledger for exact tests, review findings, and release status. Merge/deploy requires separate authorization.
