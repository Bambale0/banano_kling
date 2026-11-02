# 2026-11-02 — Public video repeats: curated choices are not required face uploads

Repository: Bambale0/banano_kling, protected release line `tanyapi`.
Base SHA: `5dfcb30e48f212f3ea2050ec958544dfe0da9b76`.
Branch: `fix/repeat-photo-choice-slots-20261102`.

## User symptom and root cause

The owner already set up picture-card categories such as Car, Clothes and Cake.
The visitor opening a foreign published video saw four mandatory source-photo uploads
as well as those same card categories. Even when only the visitor's face should be
personal, the app counted all four source images as replaceable user-owned slots.

Backend `video_repeat_descriptors` and WAN `build_repeat_plan` marked ungranted
source images `upload`; `repeat_image_references` appended the user's chosen
catalog pictures **after** those source positions. For example, four originals
plus three chosen catalog images yielded seven provider inputs and three
unnecessary mandatory user uploads. The old general reference-upload workflow
must remain available independently of publication personalization.

## New contract

- A configured *image-backed choice group* replaces one ungranted source
  reference-image position in the **server-only** recipe, `binding=choice`.
  Do not expose source URLs, source text bindings or underlying owner media.
- Remaining `binding=upload` positions are the **only** required visitor files;
  author-approved `binding=fixed` continues to be silently reused with explicit
  consent. The image catalog is distinct from the user's own upload/library.
- Four source images + three curated groups default to one user upload plus
  three selected variants, preserving provider positions and `@ImageN` bindings.
  The author may explicitly choose source-photo positions for each group.
  Older groups without a mapping bind to the rightmost free image positions
  in display order, leaving leading images (such as a person's face) for upload.
- First/last-frame slots, video, audio, document and link slots are never consumed
  by picture-choice groups. Unsupported/under-capacity recipes keep the previous
  append-only behavior; invalid explicit assignments and duplicate assignments
  are rejected before billing.
- Text-only personalization and repeat generations with no configured image
  groups follow existing contracts. The catalog remains viewable only through
  authenticated, publicly enabled personalization.
- Both generic Seedance/Omni video and WAN quote/launch use the exact same
  resulting provider image order. Catalog values remain ID-based and
  validated against server-stored choices; the custom photo URL belongs to
  the authenticated visitor; server-only selected image references remain
  rechecked before charging.
- No DB schema changes, provider changes, pricing changes, payment writes or
  unauthorized grant widening. Existing `repeat_user_fields` JSON stores
  optional `image_slot_index`; public DTO intentionally omits its private
  mapping, retaining labels/curated IDs/image links.

## Reproduce / verify

1. Source recipe: four ordered image references; three author picture-choice
   groups, no implicit permission to reuse source images.
2. Ordinary visitor sees one personal face-photo slot and Car, Clothes, Cake
   grids; can select preset picture or `Свой вариант` in each group.
3. Client sends one upload plus choice IDs. Backend binds the four provider
   images in correct order, preserves original private prompt and authorized
   videos, emits correct `@ImageN` role instructions, quotes and charges once.
4. Missing face, malformed/forged choice, stale permission, unsupported mode,
   lost source file, duplicate slot assignment and stale provider media fail
   before charge. Old 4-photo legacy repeats without a catalog remain intact.
5. Safe mocked Python/React tests, browser Mini App E2E, CI gates,
   protected auto-merge and exact-SHA deploy + public health/revision checks.

## Observability and rollback

Use source generation ID, profile scope, slot counts, quote/receipt IDs and
error categories only; never log private prompts, media URLs, personal choices
or Telegram credentials. Revert release PR via protected `tanyapi` if tests
or production smoke fail. UI instructions must remain user-facing Russian,
without technical provider/implementation details.

Status: changes in review branch, awaiting exact-head CI/deployment verification.
