# Execution ledger

## 2026-09-24 — RenderGrid Banana delivery recovery

### Incident
- Baseline: `tanyapi` at `510a520a22f42d1a1b64190fdeeed234e6634bd4`.
- User symptom: Banana 2/Pro shows “generation started”, then no result/failure message arrives.
- Confirmed example: local task `img_9225b661def2`, RenderGrid creation `01a0d4a9-f4a2-798b-902e-f4140b506744`.
- RenderGrid later returned terminal `failed` (safety filter); watchdog marked the DB task failed and refunded 1.5 bananas, but the user was not notified.
- In the preceding 24h, logs showed 6 watchdog-recovered Banana failures (4 `banana_pro`, 2 `banana_2`) that followed the same silent-refund recovery path.

### Root cause
1. The shared image-provider poller selected a bounded set of the oldest pending image rows **before** filtering for managed providers. A backlog of unmanaged/KIE image rows could therefore exclude RenderGrid tasks from every poll cycle.
2. Watchdog recovery correctly failed/refunded a terminal upstream failure, but had no failed-task notification callback. Recovery could therefore leave the user with only the original “generation started” message.

### Intended result
- Pending RenderGrid/Nexus image tasks cannot be starved by unrelated pending image providers.
- Normal poller handles RenderGrid terminal states promptly.
- If watchdog still recovers a failed/expired provider task, it sends the user a failure/refund message with the existing retry keyboard instead of refunding silently.
- Refund remains single and atomic; notification failure never causes a second refund.
- Poller/watchdog races are idempotent: whichever path atomically claims the pending task performs the refund and user notification; a late second path is a no-op.

### Scope / safety
- No DB schema or migration.
- No provider payload/model/routing changes: Banana 2/Pro remain on RenderGrid.
- No pricing/referral/payment changes.
- No Mini App contract change.
- Telegram `chat not found` remains a terminal Telegram delivery condition; completed media remains persisted by the existing delivery path.
- The separate 28.1 MB Telegram error observed in the same log window came from the saved-reference preview screen, not generation-result delivery, and is outside this incident fix.

### RED → GREEN
- RED command covered the exact two failure modes:
  - managed RenderGrid task behind older unmanaged pending image rows returned no poll candidate;
  - `run_watchdog_cycle(on_failed=...)` was unsupported.
- RED result: **2 failed**.
- Added direct user-notification regression asserting the failure card includes the public task ID, refund text and retry keyboard.
- GREEN focused regressions: **3 passed**.
- Added poller/watchdog race regression: a watchdog refund followed by a late poller must not change balance or send a duplicate failure card.
- Expanded RenderGrid/watchdog/delivery suite after the race fix: **48 passed**.
- Full safe regression suite: **991 passed, 3 skipped**.

### Implementation
- `bot/services/nexus_task_poller.py`: scan pending image rows in bounded pages until the requested managed-provider batch is collected, eliminating pre-filter starvation.
- `bot/services/task_watchdog.py`: support `on_failed` callback after an atomic fail/refund, including max-age forced failures; callback exceptions are isolated from financial state.
- `bot/main.py`: wire watchdog failed recovery to Telegram using existing failure/retry UX and start watchdog only after the Bot instance exists.
- Regression tests in `tests/test_rendergrid_provider_id_contract.py` and `tests/test_task_watchdog.py`.

### Rollout
- Task branch: `fix/rendergrid-delivery-recovery`.
- Next: lint/compile/diff review → PR to `tanyapi` → required CI → native auto-merge when green → exact-SHA production deploy verification and post-deploy telemetry.

---

## 2026-09-19 — admin partner applications pagination

- Baseline: `tanyapi` at `4e56b65a8b9748ba7d3bb351039ede643cf7f1ba`.
- Finding: production has `138` pending partner applications, while the first implementation displayed only the first 20.
- Intended result: admins can access every pending application through a paginated Telegram admin queue without exceeding Telegram message/keyboard limits.
- Implementation: add pending count + offset pagination in `partner_approval_service`; show total and visible range in the admin text; add page navigation callbacks `admin_partner_applications:<page>`.
- Verification before merge:
  - `./venv/bin/python -m pytest tests/test_database.py -q -k 'pending_partner_applications or admin_partner_applications or safe_admin_edit'` → 3 passed.
  - `./venv/bin/python -m py_compile bot/services/partner_approval_service.py bot/handlers/admin.py tests/test_database.py` → passed.
  - `./venv/bin/python -m ruff check --select I bot/services/partner_approval_service.py bot/handlers/admin.py tests/test_database.py` → passed.
  - `git diff --check` → passed.

---

## 2026-09-19 — admin partner applications button hotfix

- Baseline: `tanyapi` at `6eadf4236544f853b87e243a43fb0d0b8b9bc74f`.
- Symptom: admin pressed `✅ Заявки на активацию`; Telegram showed no visible result.
- Evidence: production logs showed `TypeError: _safe_admin_edit() got an unexpected keyword argument 'disable_web_page_preview'` in `admin_partner_applications`; the callback reached the handler and failed during message rendering.
- Fix: `_safe_admin_edit` now accepts `disable_web_page_preview` and passes it to `edit_text`, fallback `answer`, and direct `send_message`.
- Regression: added `test_safe_admin_edit_accepts_disable_web_page_preview` for the exact argument combination used by the queue screen.
- Verification before merge:
  - `./venv/bin/python -m pytest tests/test_database.py -q -k 'pending_partner_applications or admin_partner_applications or safe_admin_edit'` → 3 passed.
  - `./venv/bin/python -m py_compile bot/handlers/admin.py tests/test_database.py` → passed.
  - `./venv/bin/python -m ruff check --select I bot/handlers/admin.py tests/test_database.py` → passed.
  - `git diff --check` → passed.
- Rollout plan: merge hotfix branch back to `tanyapi`, push, verify exact CI/deploy SHA, health, container revision and filtered logs.

---

## 2026-09-19 — partner activation application queue

- Baseline: `tanyapi` at current workspace head before task branch `fix/partner-activation-queue`.
- Intended result: admins can open a visible list of pending partner activation applications from the partner admin menu and approve/reject them even when the original Telegram notification is buried.
- Existing state: `partner_applications` already stores `pending/approved/rejected`, user submissions notify admins with inline approve/reject buttons, and `review_partner_application` performs the atomic activation by setting `users.partner_agreed_at`.
- Gap: there is no admin queue screen that re-lists pending applications after the original notification is missed.
- Reuse: keep the existing `partner_approval_service`, callback IDs `partner_app_approve_*` / `partner_app_reject_*`, and admin partner menu.
- No-hardcode decision: no new mutable business values; the list limit is a bounded UI page size, not business configuration.
- Schema/API/UI/FSM impact: no schema migration; Telegram admin UI gets one new callback screen. Mini App and user FSM are unchanged.
- Security: admin-only callback guard remains server-side; pending list exposes Telegram profile links only to configured admins.
- Observability: existing review path logs review-card update failures and user notification failures; queue retrieval is deterministic from DB.
- Test plan: add service regression for pending-only ordering/limit and handler formatting/keyboard checks, then run focused pytest and compile touched modules.
- Implementation: added `get_pending_partner_applications()`, a new admin partner-menu button, queue text/keyboard helpers, and `admin_partner_applications` callback using existing approve/reject callback IDs.
- Verification:
  - `./venv/bin/python -m pytest tests/test_database.py -q -k 'pending_partner_applications or admin_partner_applications'` → 2 passed.
  - `python -m py_compile bot/services/partner_approval_service.py bot/handlers/admin.py tests/test_database.py` → passed.
  - `./venv/bin/python -m ruff check --select I bot/services/partner_approval_service.py bot/handlers/admin.py tests/test_database.py` → passed.
  - Full `ruff check` on the same files still fails on pre-existing unrelated `bot/handlers/admin.py` findings (timezone calls, old string concatenation style, broad exceptions, executable bit).

---

## 2026-09-15 — payment provider priority

- Baseline: tanyapi @ ac4f35c7c6f5.
- Intended result: Robokassa is the first/default visible RUB option and is labeled СБП / карта; FK Kassa is second and explicitly marked reserve; Lava is moved below the primary/reserve and alternative methods.
- Existing state: backend config already selects Robokassa as primary, but Telegram and Mini App UI plus regression tests still encode Lava-first / Robokassa-reserve behavior.
- Scope: presentation/routing order only. Provider webhook validation, transaction creation, amounts, bonuses, idempotency and crediting are unchanged.
- Surfaces: Telegram flat payment menu, legacy provider keyboards, Mini App balance sheet, E2E/static regression contracts.
- Risk: duplicate choose_pay handlers make router order important; the production flat menu is owned by lava_checkout and decorated by miniapp_lava_payment_methods_compat.
- Test plan: first update regression expectations and confirm RED, then implement order/labels, run focused pytest, Mini App E2E/build checks, review diff, CI, merge to tanyapi, verify exact deployed SHA and production smoke/logs.
- RED evidence: focused contract suite initially failed 9 assertions on the old Lava-first / Robokassa-reserve ordering.
- Implementation: Telegram flat menu, legacy reserve keyboards, Mini App balance UI and E2E were aligned to Robokassa → KASSA reserve → alternatives → Lava.
- Documentation: robokassa.md and freekassa.md now describe the same verified priority.
- Verification so far:
  - focused Python payment contract suite: 57 passed;
  - Ruff on all changed Python/test files: passed;
  - Mini App Jest: 17 suites / 46 tests passed;
  - Mini App ESLint: passed;
  - Next.js production export/build: passed;
  - critical Playwright browser E2E: passed.

---

## 2026-09-15 — RenderGrid legacy media and reference retention

### Task
Repair legacy RenderGrid media and reference-retention behavior without rewriting the working RenderGrid adapter.

### Baseline
- Original baseline SHA: `ac4f35c7c6f5726d586bfc17a9859f2161ac83d8`.
- Rebasing target before PR: current `origin/tanyapi`, including payment-priority commit `cf6ce28`.
- Task branch: `fix/rendergrid-legacy-storage-policy`.
- Production container: `banano-kling-bot`.
- Production DB: PostgreSQL database `banano_kling`.

### Intended user-visible result
- Old RenderGrid results are localized while their provider URLs are still alive.
- A historical generation that can be repeated keeps its snapshot references even after the saved-reference row is pruned.
- RenderGrid external result URLs stop leaking through history/task-detail and are treated with a 24h provider-specific lifetime.
- Feed, profile, Mini App history/detail and repeat flows agree on media availability.
- Backfill becomes an idempotent deploy/reconciliation step with bounded batches and telemetry.

### Current-state audit
Existing and reusable:
- Fresh RenderGrid completion already localizes image results in `bot.main._persist_result_url_if_needed`.
- `scripts/backfill_rendergrid_image_results.py` already verified a non-empty local file, updated `result_url/result_urls` with compare-and-swap, and emitted counters.
- Feed/profile already use the database media availability resolver.
- Production baseline found exactly 7,133 completed image rows still pointing at `cdn.rendergrid.io`.

Confirmed gaps at task start:
- Backfill had no cursor/checkpoint and could retry the same dead rows indefinitely.
- Backfill was not part of deploy/reconciliation.
- Orphan reference cleanup protected `saved_references` and active prompt previews, but not generation snapshots.
- RenderGrid shared the generic ephemeral TTL (72h) instead of 24h.
- Mini App recent-task history and task-detail used a separate URL parser and could expose old RenderGrid URLs directly.
- Requested legacy/repeat regression matrix was incomplete.

### Production evidence
- Baseline 2026-09-15: exactly 7,133 completed image rows pointed at `cdn.rendergrid.io`.
- Controlled batch 1: `scanned=100 localized=100 updated=100 skipped_race=0 failed=0`.
- Controlled batch 2 localized another 500 rows; DB verification after commit showed 6,533 external RenderGrid rows remaining.
- During the 500-row run PostgreSQL reported a deadlock while the old script held its DB connection across provider downloads. The backfill was then changed to fetch candidates, close DB, localize remotely, and reopen DB only for short CAS updates.
- Production bot health remained `healthy`; no additional recovery batch is started until the merged transaction-safe version is deployed.
- Snapshot-retention PostgreSQL query was executed against production successfully and resolved 95,982 unique historical local snapshot-ref URLs without transferring request_data JSON blobs to Python.

### Data-safety / no-hardcode decisions
- No blind bulk UPDATE: preserve compare-and-swap guard and validate the local file before mutation.
- Backfill is bounded by batch size and cursor/checkpoint; failures are counted, not silently dropped.
- Provider TTL is explicit and configurable; RenderGrid default is 24h.
- Reference cleanup errs toward retention when a completed generation snapshot owns a local reference.
- No schema rewrite is required.
- Deploy reconciliation cursor is persisted under the existing `/app/data` persistent volume.

### Observability
Backfill/reconciliation emits:
- scanned;
- localized;
- updated;
- failed;
- skipped_race;
- next_before_id;
- exhausted.

Reference cleanup reports how many generation snapshot refs are protected.

### Test seams / acceptance
1. RenderGrid completed → local file → DB canonical URL.
2. Old RenderGrid card resolves through shared availability policy.
3. Repeat remains viable beyond 24h when canonical media/refs are local.
4. Pruned saved-reference file remains while referenced by historical generation snapshot.
5. Mini App profile/remix and history/task-detail do not emit stale direct RenderGrid URLs.
6. Telegram repeat uses retained snapshot refs.
7. Provider payload still receives correct references; no adapter rewrite/regression.
8. Backfill cursor progresses past failures and CAS prevents races.
9. Deploy reconciliation is bounded, persistent, idempotent and fail-safe.

### Implementation status
- [x] Audit current branch/runtime and confirm live legacy count.
- [x] Run initial controlled production backfill batches; 600 rows localized.
- [x] Add red regressions for snapshot retention, provider TTL/shared resolver and cursor progress.
- [x] Implement generation-snapshot protection in orphan cleanup.
- [x] Add provider-specific RenderGrid TTL and shared public result resolver.
- [x] Route Mini App history/task-detail/media proxy through shared resolver.
- [x] Add cursor/checkpoint-aware backfill telemetry and reconciliation entrypoint.
- [x] Persist deploy reconciliation cursor under `/app/data`.
- [x] Wire bounded reconciliation into production deploy.
- [x] Add requested Mini App/Telegram/provider regression coverage.
- [x] Update environment/provider docs to match async RenderGrid + durable localization reality.
- [x] Focused regression matrix: 20/20 green before checkpoint change; 14/14 targeted green after checkpoint change; 11/11 cleanup/backfill tests green after query optimization.
- [x] Run two-axis review (standards + spec), fix blockers.
  - blocker fixed: deploy reconciliation now persists cursor across deploys;
  - blocker fixed: orphan cleanup no longer fetches/parses ~198k request_data JSON blobs in Python;
  - no unresolved high-severity review issue remains.
- [ ] Full safe pytest suite / changed-lines CI lint on rebased PR head.
- [ ] Push branch, open PR to `tanyapi`, verify CI, merge only when green.
- [ ] Verify exact production SHA, health, smoke and telemetry.
- [ ] Continue controlled production backfill and report current recovered/remaining totals.

### Rollback
- Code changes are normal git rollback.
- Backfill only replaces provider URLs with verified local durable URLs; it does not delete source data/files.
- CAS guard prevents overwriting concurrently changed rows.


---

## 2026-09-23 — Seedance video-reference binding regression

### Incident
- Production branch: `tanyapi`.
- Symptom: Seedance 2.0/2.5 accepted video references but frequently preserved performers from the donor video instead of replacing them with people from uploaded image references.
- Reproduced from live generation metadata on 2026-09-23 with 3 image references + 1 video reference.
- Reference video transport is healthy: sampled donor files are H.264/AAC, 720x1280, 30 fps, ~14.8s, ~5.7 MB.
- When a video survives the UI/FSM path, provider transport is healthy and KIE receives separate `reference_image_urls` and `reference_video_urls`.
- A second bug was confirmed in live logs: at 19:52:11 a prompt that still referenced `@video1` was sent with `ref_images=3 ref_videos=0`; at 20:05:29 the same flow sent `ref_images=3 ref_videos=1`.

### Root cause
- Runtime passed prompt reference aliases through verbatim.
- Live prompts used incompatible variants such as `@image1`, `@video1`, `@IMAGE 1`, and a legacy combined ordinal where the fourth uploaded asset was called `@IMAGE 4` although the provider receives it as `reference_video_urls[0]`.
- Seedance reference-to-video expects type-specific aliases such as `@Image1` and `@Video1`; invalid aliases can fail to bind the intended media role.
- The Seedance 2.0 media screen exposed `Без видео-рефов` even after a video had already been uploaded. Its generic callback unconditionally cleared `v_reference_videos`, allowing a prompt containing `@Video1` to reach KIE with zero video references.
- Historical note: a global Seedance prompt injection was intentionally removed in commit `cff2eb4`; this fix does not restore that global semantic injection.

### Fix
- Add a shared provider-boundary alias normalizer for Seedance 2.0 and 2.5.
- Canonicalize case/spacing: `@image1` / `@IMAGE 1` -> `@Image1`, `@video1` -> `@Video1`, and equivalent audio aliases.
- Repair legacy combined ordinals using actual media counts: with 3 images + 1 video, `@IMAGE 4` -> `@Video1`.
- Preserve prompt wording and existing KIE request fields/endpoints; no global role lock is injected.
- Reject a Seedance request before provider submission when the canonical prompt references `@ImageN`/`@VideoN`/`@AudioN` that has no matching uploaded media.
- Hide `Без видео-рефов` after a Seedance video has been uploaded, and make stale skip callbacks non-destructive.
- Emit count-only telemetry when aliases are normalized or a request is blocked; do not log prompt contents or media URLs.

### Verification
- RED: 4 focused binding tests failed before implementation.
- GREEN: 4/4 focused tests after implementation.
- Expanded Seedance/continuity/repeat/trend regression set: 57/57 passed before the stale-callback regression was added; final focused suite is rerun before PR.
- Real production media files validated with ffprobe and are within reference-video constraints.
- Example transformation verified offline:
  - before: `@IMAGE 1 ... @IMAGE 4 = видеореференс`
  - after: `@Image1 ... @Video1 = видеореференс`

### Rollback
- Revert the shared alias normalizer integration in `seedance_service.py` and `seedance_25_service.py`.
- No schema migration or persisted-data mutation is involved.

---

## 2026-09-26 — Seedance 2.5 trend launch regression

### Incident
- Production branch baseline: tanyapi at 9edef3dcdb9bdf98ef1c54ac365680250b3f7aed.
- User report: curated trends configured for Seedance 2.5 do not generate.
- Direct Seedance 2.5 generation is healthy in production: provider tasks are accepted, KIE callbacks arrive, tasks reach completed, and result MP4 URLs are persisted.
- Trend history contains recent banana_pro, seedream_5_pro, and legacy seedance_2 tasks, but no seedance_2_5 trend task.
- Production /mini-app/api/trends/run returned HTTP 400 during the reported flow before any Seedance provider task was created or credits were deducted.

### Root cause
- The dedicated Seedance 2.5 trend adapter called the legacy miniapp._find_video_model_meta("seedance_2_5").
- Seedance 2.5 is intentionally injected dynamically by its compatibility/bootstrap layer and is not present in the legacy static VIDEO_MODELS registry.
- Therefore every Seedance 2.5 curated trend that passed earlier user-field validation was rejected locally as "Seedance 2.5 сейчас недоступна" before provider submission.
- Existing unit coverage masked the defect by monkeypatching the legacy lookup to return Seedance metadata.
- A separate preflight on current trend #1605 also demonstrated its configured required "Цифры" user field; missing that field is correctly rejected before launch. Current frontend source has a regression test proving required trend fields are rendered and sent.

### Fix
- Resolve Seedance 2.5 trend capabilities from the dedicated public Seedance metadata provider instead of the legacy generic video-model registry.
- Keep ratio/duration normalization, billing, provider payloads, task persistence, refunds, and all non-Seedance trend routing unchanged.
- Update the regression test so the legacy lookup explicitly returns None; the Seedance trend must still reach its dedicated provider runtime.

### Verification
- RED: tests/test_trend_seedance_25_compat.py failed with TrendRunValidationError: Seedance 2.5 сейчас недоступна.
- GREEN: focused Seedance trend regression passes after the fix.
- Expanded backend trend/Seedance suite: 43/43 passed.
- Frontend required-user-field contract: 1/1 passed.
- Ruff on changed Python files: clean.
- Full backend suite: 991 passed, 3 skipped; exit code 0.

### Rollout
- Task branch: fix/tanyapi-seedance25-trend-runtime.
- PR target: tanyapi.
- No schema/data migration.
- No business-value hardcode added.
- After merge: verify exact deployed SHA, submit a controlled Seedance 2.5 trend through the real Mini App path, confirm provider task creation/callback/result delivery, and inspect post-deploy logs.

---

## 2026-09-26 — Production pipeline observability status repair

### Incident
- Production observability workflow failed after the Seedance 2.5 rollout while the actual reliable production deploy succeeded.
- GitHub reports `.github/workflows/deploy-production.yml` as `disabled_manually` and `.github/workflows/deploy-production-reliable.yml` as `active`.
- `publish-pipeline-pending-status.yml` still tried to discover runs for the disabled workflow, so it failed after publishing only the `tanya/ci` pending status.
- The active reliable deploy workflow did not publish a terminal `tanya/deploy` commit status, so merely repointing observability would leave that context pending forever.

### Fix
- Point pending deploy status discovery at `deploy-production-reliable.yml`.
- Add an always-running terminal status job to the reliable deployment workflow.
- Publish `tanya/deploy=success` only when both exact-SHA CI verification and deployment succeed; otherwise publish failure with the release run URL.
- Keep the disabled legacy production workflow disabled to avoid duplicate production deployments.

### Verification
- RED: new workflow-contract tests failed on the stale deploy filename and missing terminal status publisher.
- GREEN: both workflow-contract tests pass after the change.
- YAML parsing succeeds for both changed workflows.
- Existing deployment workflow regression matrix: 19/19 passed before PR.

### Rollout
- Task branch: `fix/tanyapi-pipeline-observability`.
- PR target: `tanyapi` with auto-merge only after CI is green.
- After merge/deploy: verify exact production SHA, `tanya/ci` and `tanya/deploy` commit statuses, then inspect fresh backend logs for trend/Seedance/webhook/errors.

---

## 2026-09-26 — Seedance 2.5 tagged trend production smoke

### Incident
- A controlled production smoke of published trend #1605 reached the dedicated Seedance 2.5 runtime but returned HTTP 502 before task creation.
- Billing safety worked: the 72-credit debit was rolled back and the smoke account balance stayed unchanged.
- Exact provider-bound error: Prompt references missing Seedance media: @Image1.

### Root cause
- The curated prompt uses a Seedance image binding (@Image1 after canonicalization).
- Trend compatibility mapped every single uploaded photo to Seedance first_frame.
- In first-frame mode the photo is not present in reference_image_urls, so the provider binding layer sees @Image1 as unbound and rejects the request before KIE task creation.

### Fix
- Keep ordinary single-photo Seedance trends on first_frame.
- If the curated prompt explicitly binds an image reference, keep even one uploaded image in Seedance multimodal reference_image_urls.
- Multi-photo trends remain multimodal.
- No pricing, billing, task persistence, callback, or delivery contract changed.

### Verification
- RED regression: tagged single-photo trend launched as first_frame.
- GREEN regression: tagged single-photo trend launches as multimodal; untagged single-photo behavior remains first_frame.
- Expanded Seedance/trend suite: 59/59 passed.
- Ruff changed Python: clean.
- Full backend suite: 994 passed, 3 skipped; exit code 0.
- Production smoke will be repeated after exact-SHA deployment and followed through provider callback, DB completion and Telegram delivery.

### Rollout
- Task branch: fix/tanyapi-seedance25-trend-image-binding.
- PR target: tanyapi.
