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
- Local Playwright default browser download was unavailable. The same browser E2E ran
  successfully with packaged Chromium and process-per-case adaptation: 8/8 admin/ordinary
  cases across photo, Seedance 2, WAN 3 and WAN Prime. Mobile screenshot inspected:
  image grid, selected border, custom upload tile and no horizontal overflow.
  Unmodified Playwright browser E2E remains an exact-head CI gate.
- Production baseline ea704c3 observed healthy via SentinelX; existing admin preview flag true.
  No production config/data writes or paid generations made.
- PR #387 created with native auto-merge; synchronized current tanyapi 2d0c491 without conflicts.
  Independent re-review found no remaining blockers; new catalog backend cases: 20 passed.

Remaining: final build/browser/review confirmation, protected PR checks/autodeploy and live admin smoke.
No paid provider calls or business price changes.

Final concurrency check: simultaneous custom uploads in separate groups reproduced a lost selection (RED). Shared selector now merges from the latest synchronous value snapshot; regression GREEN.

GitHub review hardening: selected WAN catalog/custom inputs are now inspected via an exact
server-authorized local-file capability (real ActualWan3PrimeProbe plus digest), including
explicit consent when publishing derived results. Seedream effective adapter cap is checked
before prompt binding; existing source-host aliases are deduplicated before @ImageN assignment.
Regression covers real WAN probe (without wan3_prime_media rows), disallowed URL, Seedream
cap, and source aliases. PR temporarily draft while these checks run.

Real WAN quote→launch regression reproduced a second rejection: generic catalog images
have no managed-media row. MediaInfo now carries a server-only local-repeat-image capability;
reservation verifies its exact local path and SHA-256 again instead of requiring a managed
WAN upload row. Existing managed media retains its row/expiry lock checks. The same-key
launch is idempotent, and file mutation after quote rejects before debit/provider.
RED reproduced missing row; GREEN quote→launch and tamper: 2 passed. Adjacent lifecycle,
publication and repeat backend selection: 68 passed.
