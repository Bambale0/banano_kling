# Execution ledger

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
