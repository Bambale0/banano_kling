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

## Final regression root-cause follow-up (2026-11-03)

- The first full CI run (at `d897c3e2`) identified five incompatible synthetic test inputs after the new mandatory-photo rule. Tests were updated to explicitly supply a visitor-owned image without weakening backend validation.
- The second full CI (at `4fc147b0`) reached **4,471 passing / 2 failing**. Both remaining failures were Seedance 2.5 personalized quote paths with a synthetic *32×32* image. The actual Seedance 2.5 source validator requires **at least 300 pixels per side**, so production correctly rejected the quote before charging or calling the provider.
- Updated the fixture to a real local **512×512 JPEG** in `tests/test_video_repeat_prompt_composition.py`. This preserves the full private-prompt, image-index, provider payload and quote validation; no service or policy change was made.
- Final exact-HEAD CI, code review, merge and deploy verification remain mandatory gates. Do not report production complete until `tanyapi` and both live revisions match the merge SHA, health is good, and workflow succeeds.

## 2026-11-03 — Release continuation and photo parity

Baseline: `tanyapi@8c2d2fe2a6a9f8fbc7d5aadc48ec853509f05438` (PR #402 squash-merged automatically from exact head `5c33d34eb2457b0a2ce0bd8159ad947590fb3be0`). All four exact-head PR gates succeeded. Exact merge-SHA CI and normal production deploy are running; production was still at `35821910` at the first live check.

User clarification: video trend personalization already works. Add the same missing-required-user-photo guard to photo repeats; preserve the hidden author's prompt, current slot assembly, owner/foreign permissions and the ability to retain authorized car/outfit/cake references. Do not redesign the flow or require re-uploading auxiliary author materials.

Fresh audit:
- Existing video form blocks curated repeats without an explicit uploaded/saved personal image; the authenticated video owner guard incorrectly accepted ownership anywhere in the list. Fresh PR #402 review `discussion_r4453653745` identifies this as P1.
- Photo form treats every feed repeat as exempt from local-reference requirements, while both photo HTTP routes append catalog choices after restoring authorized references. Thus author/catalog media can satisfy the model's nonempty-reference check without a user photo.
- Reuse the existing image-upload ownership validator, configured image-choice fields, saved-reference picker, server-side prompt composer and model image limits. Preserve reference ordering and private prompt assembly.
- No schema, migration, price, provider, payment contract, feature flag or admin configuration changes. The existing personalization access gate is retained. Telegram FSM and standalone image/text generation do not change.
- Public seams: both authenticated image HTTP routes, owner/foreign variants, selected/omitted structured choices, invalid/foreign/video input and successful own-image submission; image-form behavior and existing video regressions.

Plan and acceptance:
1. Reproduce the missing-photo and wrong-primary bugs with regression tests (RED: 26 cases reproduced before patch; additional successful-photo and spoofed-primary cases added).
2. Enforce an explicit owned primary image for curated photo repeats before cost/debit/provider dispatch, even if a crafted client omits structured values. Verify the explicit image survives existing recipe assembly.
3. Show a required photo picker in the image form; source preset references cannot implicitly satisfy it. Explicit saved-photo selection is supported. Preserve non-curated/all-fixed repeats.
4. Validate the first image, rather than any image, in the existing curated owner video guard.
5. Run focused Python and frontend tests, lint/build, two-axis review, protected PR/native squash auto-merge and normal exact-SHA CI/autodeploy.
6. Verify exact live backend image and frontend revision, public health, authenticated no-generation smoke and bounded error telemetry. No paid generations.

Observability: rejected photo repeats log source/user IDs and `personal_photo_required` without media URLs or private prompts. Existing reference-count and deploy-SHA telemetry remain in place.

Verification in progress: isolated source checkout using the already installed test interpreter; provider launch/price/payment seams mocked. Network isolation prevents any external generation call. First broad run: 323 passed; one installed HTTP test could not reach its own loopback in the isolated network namespace. Re-run with only loopback enabled; this is a test-harness issue, not an application failure. Rollback remains a protected revert to `tanyapi`; no data rollback is needed.
Review and verification update:
- Two-axis review identified retained author Image1 remaining ahead of the user's photo. Curated photo assembly now replaces only that primary slot, preserving auxiliary Image2..N; both HTTP routes test retained author face+car and ensure own photo first, author face absent, car retained.
- Reviewer then caught stale private-reference provenance after primary replacement. Launch metadata now includes only the author references actually retained; a regression exercises the real image launcher, permission resolution, task persistence and a mocked provider.
- Video review regression additionally covers Seedance 2.5 multimodal alias/list conflict and validates the actual provider primary after normalization.
- Focused backend and adjacent private-reference suites: **485 passed**. Full frontend Jest: **80 suites / 626 passed**; the combined command reached its wall-clock limit after Jest, so TypeScript and ESLint were rerun separately and passed. Full-file Ruff found two legacy findings outside edited lines; use the repository's changed-line gate for the final candidate. Python compilation passed.
- Added browser assertions to the existing CI personalization journey: selecting an author catalog tile leaves photo launch disabled; explicitly selecting a saved own photo unlocks it. All browser APIs remain intercepted.