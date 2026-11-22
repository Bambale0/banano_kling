# Seedance 2.5 legacy photo-text video repeat: scenario restoration and diagnostic contract

Date: 2026-11-20. Base: tanyapi 15ea1667185c4a3194ee2aecbdefcceeb7d8a9b8.

## Exact reproduced failure

Older completed Seedance tasks created through the generic video path saved v_type="imgtxt" and v_image_url, with no seedance25_scenario. On repeating such a publication:
- The server restores private first-frame metadata, but does not restore the Seedance-native scenario.
- Public Seedance validator defaults missing scenario to text, which discards the frame.
- If the browser supplies a new photo reference, the restoration incorrectly switches the task to multimodal instead of replacing the original first frame.

The reported UI symptom is the generic error "Не удалось проверить входные данные повтора. Проверьте свои файлы.". We have reproduced the underlying legacy-shape bug in tests. The exact affected production task ID is not present in the screenshot, so the screenshot-to-task attribution is not independently confirmed.

## Tested fix

- For tasks without an explicit Seedance scenario, infer it only from the original server-owned stored media:
  - list of images/videos/audio => multimodal;
  - single old v_image_url/first-frame alias => first_frame;
  - no source media => text.
- An explicitly stored scenario remains authoritative.
- A visitor replacing a photo in old photo-text mode replaces the first frame, not a multimodal recipe.
- Do not infer private consent from visitor-supplied metadata. Existing typed/legacy repeat slot permissions, media availability and owner-only rules remain intact.
- On a rejected prepayment Seedance input, log structured source_id, stage and error_type without secret prompt/media URLs. Return a stable client error code repeat_input_validation_failed and an actionable, redacted Russian error.
- Neither paid debit nor provider launch is changed.

## Evidence / release gates

- RED pure AST regression: 3 failures (two missing scenario, one wrong scenario) before fix.
- GREEN pure AST regression: 18/18 tests including new legacy first frame, replacement, multimodal, text and original permission guards.
- Added HTTP boundary regression through the existing isolated repeat fixture (exact old task metadata → restored correct first_frame) for GitHub backend CI.
- Python compileall, Ruff I/F, diff --check pass locally.
- GitHub protected CI, exact SHA production rollout, HTTP /health and one owner-scoped synthetic repeat quote/validation smoke remain release gates.
- Never run real paid generations on customer accounts for smoke testing.

Rollback: revert this two-handler restoration/diagnostic patch, preserving DB and balances.
