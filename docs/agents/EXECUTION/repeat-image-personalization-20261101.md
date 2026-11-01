# Visual repeat personalization

Baseline: `ea704c3` on `tanyapi`. User supplied two screenshots: named image grids,
three columns, selected border, custom image upload, normal generation settings.
Access remains admin-only during development.

Preflight: text choices and private source fragment replacement already exist;
image options, durable catalog media, custom upload and image/tag assembly are absent.
Reuse publication fields JSON (no SQL migration), admin authorization, authenticated
upload, shared image/video form, server recipe restoration and provider limits.

Design: retain application theme and typography; image grids use existing border,
background and cyan selection tokens. No prices/categories/assets copied from screenshots.
Author manages image options in publication editor. Image selections are IDs; custom
images use actor-owned authenticated uploads. Curated images use durable catalog paths,
outside personal saved-reference retention. Backend appends selected images after
restoring source references and binds the allowed source fragment to the actual image
ordinal. Existing text choices and unconfigured repeats remain compatible.

Steps: (1) normalization/storage/render regression; (2) durable upload + API assembly;
(3) shared tiles/custom uploader + author editor; (4) unit/integration/frontend/build;
(5) code review, PR to tanyapi, protected CI/autodeploy, admin smoke.

Seams: domain field normalization and media selection; authenticated HTTP repeat/upload;
shared React selector and submitted provider recipe. No paid smoke required by this task.
Risks: reference capacity, private source DTO exposure, stale choices, upload failures,
personal retention, image ordinal drift, duplicate selected URLs, unsupported frame modes.
Observability: use existing repeat source/user/media counts; do not log URLs/prompts.

Progress:
- Backend normalization/storage and public metadata retain image choices; private bindings remain hidden.
- Catalog upload is admin/flag protected, JPEG reencoded, and excluded from generic upload cleanup.
- Actual image selection is resolved on the server, appended after restored inputs, deduplicated,
  and referenced by its actual ordinal; custom URLs must belong to the authenticated actor.
- Shared three-column selector has custom upload/error states and source-safe cancellation.
- Author editor manages images/labels/custom option; unsupported video recipes cannot publish image choices.
- Independent Spec/Standards review found cleanup retention, first-image ordering, unsupported publication
  configuration and older Safari ID generation issues; all addressed with regression coverage.

Verification so far:
- RED: seven new backend scenarios failed against baseline (missing metadata/render/media validation).
- Domain/image+existing personalization: 21 passed at first GREEN.
- Backend publication/prompt/review selection: 151 passed before review hardening.
- Backend continuity/prompt/WAN + new image cases: 210 passed before final mode-capability hardening.
- Latest focused backend after mode-capability changes: 145 passed.
- Full Mini App Jest: 75 suites, 576 passed; final editor fallback test: focused 9 passed.
- Production Next export/TypeScript passed; Ruff/compile/diff checks passed.
- Local Playwright default Chromium download failed (truncated upstream browser archive);
  repository browser E2E remains required in CI. Alternative local browser setup in progress.
- Existing production container observed healthy via SentinelX; no production config/data writes made.

Remaining: final build/browser/review confirmation, protected PR checks/autodeploy and live admin smoke.
No paid provider calls or business price changes.
