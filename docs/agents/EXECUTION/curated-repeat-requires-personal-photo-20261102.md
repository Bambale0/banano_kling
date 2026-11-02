# 2026-11-02 — Mandatory personal photo in video repeats with curated image choices

Protected release baseline: `35821910c7bf0926386b69f196cee5e9beefb351`.
Scope: Mini App published-video repeats with author-curated image-choice groups.

## Reproduction and root cause

When an owner opens their own published video from the feed, the card intentionally omits `repeat_reference_slots`. The general video form also treats all source-aware image-to-video inputs as optional by checking `!sourceFeedGenId`. Thus selecting a curated car/outfit/cake image enables video launch even when no personal photo has been uploaded. A foreign repeat with no source image slots similarly has no mandatory upload; the selected catalog pictures are not the visitor's own face.

## Behaviour and API invariant

- Curated author images do **not** count as the viewer's personal photo.
- If there is a typed required image upload slot, it already enforces the photo. Do not add a duplicate.
- Otherwise, with curated image choices, display one required personal-photo picker. It accepts uploaded or saved visitor-owned photos. The launch button stays disabled until supplied.
- The authenticated server rejects missing or non-visitor-owned personal photo before provider submission or any debit, on both owner and foreign repeat paths.
- For typed recipes with zero upload image slots, the personal photo follows the preserved source image positions (including any choice-bound source slot). In the append-only catalog case it precedes the newly appended curated images. This preserves existing private `@ImageN` bindings; an explicit identity instruction refers to the actual additional-photo index.
- Provider image limits are taken from existing model metadata and checked on the final assembled list before billing; no silent truncation of selected pictures is allowed.
- No changes to price, provider routing, feature availability, database schema, permissions or payments. Text-only repeats and non-curated all-fixed recipes keep their previous behaviour.

## Regression and release gate

Jest: owner choice-only + foreign zero-slot choice-only form; selected catalog option alone leaves launch disabled; saved personal photo unlocks and is included in outgoing payload.

Pytest: missing photo rejects; forged foreign upload rejects; zero-source image recipe and one choice-bound source photo include actual viewer face before catalog; owner shortcut cannot restore hidden author photo in lieu of an explicit upload.

Check existing Seedance/WAN repeat suites, browser E2E, full CI, protected merge, exact production SHA, backend health, Mini App revision and personal-reference feature flag. No paid generation is required to verify this fix.
