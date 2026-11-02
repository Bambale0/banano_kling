# 2026-11-02 — Repeat personalization: image groups without prompt-string matching

Task: resolve the admin Mini App error "Исходное значение поля «Образ» не найдено в скрытом промпте" when publishing groups of selectable image references (person/outfit/cake/car). Target protected line: `tanyapi`; task branch: `fix/repeat-image-fields-label-only-20261102`.

## Root cause and existing paths
- `bot/repeat_personalization.normalize_repeat_fields` reused trend text normalization, which insists that every `original_value` occurs verbatim in the hidden source prompt; `render_repeat_base` then required the exact substring for **all** fields, including image groups.
- `task-detail-panel.tsx` exposed the source-fragment input for every group.
- Existing `repeat_image_references` / `append_repeat_images` correctly authorize catalog/custom images and deduplicate by real media identity. Do not change those semantics, the provider limits, auth, billing, or model routing.

## Acceptance and implementation
1. An image-backed group needs only its label and authorized image choices, even when its legacy `original_value` is absent from the base prompt.
2. The private scenario and original media remain intact; selected images are added as prioritized per-group `@ImageN` instructions using actual provider ordinals. Never assume fixed numbers when images are deduplicated.
3. Text-only fields still need exact verified source fragments and their existing typed/allowlist validation. No public exposure of private bindings.
4. Frontend hides the source-fragment input for an image-backed field and strips stale source values from its publication payload. The group label and image uploader remain.
5. All existing feature-flag and server-side admin checks remain. Invalid selections, reference limits, owner checks, and unsupported model modes still fail before billing.

## Test seams
- Backend regression: label-only image fields with unmatched legacy fragments; multiple image groups with face reference and @Image2/3/4; mixed strict text fields; invalid indices; existing forged/upload owner and provider constraints.
- Mini App regression: author preview shows image group name/upload editor without source text input and publishes without stale source fragment.
- Release gate: focused pytest/Jest, full CI for the exact PR head, protected merge into `tanyapi`, automatic deploy on merge, public frontend/backend revision verification and admin-only smoke; no paid provider generation for this incident.
- Recovery: revert task PR through protected line if needed; no schema migrations/config/tariff changes.

## Validation
- Source review: confirmed source-text normalization and image media index pipeline in `bot/repeat_personalization.py`, `bot/trend_user_fields.py`, Mini App publication editor and existing unit tests.
- Local direct execution / production host unavailable through connected agent: the `sentinelx` OS user cannot traverse root-owned `/root`. Never assert a live smoke or successful deploy on that evidence alone.
- Pending final CI, merge, and production verification.

## Engineering guidance consulted
- `Bambale0/skills`: diagnose-from-evidence / TDD baseline from repository AGENTS.
- `Bambale0/claw`: debugger (root cause, regression tests and narrow patch).
- `wondelai/skills`: release-it (release gate, health/observability).
- `anthropics/skills`: webapp-testing (frontend coverage requirements).
