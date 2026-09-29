# Execution ledger

## 2026-09-29 — Resumed combined release verification

- Recovered task branch at `8ac64fa`; remote PR #208 still at `6b919ee`; production and fresh `origin/tanyapi` both `932e48d`.
- Read/updated engineering sources: Bambale0/skills `tdd`, `code-review`; Bambale0/claw README release/config discipline; anthropics/skills `webapp-testing`. Two independent review axes: Spec found no blockers; Standards identified missing operation correlation in Gemini/fallback logs, addressed before release.
- Targeted backend run initially: 62 passed / 1 failed. Failure exposed order-dependent partner approval fixture pointing at stale SQLite path after admin imports. Fixed fixture to use isolated DB, installed real approval guard, explicitly approved referral test partners; production eligibility unchanged.
- Corrected targeted run: 63 passed. Additional referral checks (approved self-referral, unapproved referrer blocked): 11 passed.
- Frontend: all 19 suites / 50 tests passed; production build/typecheck/static export passed; critical browser E2E passed against freshly copied build.
- Frontend lint initially scanned untracked generated `.e2e-server` output (4,096 generated-file errors); source lint `npx eslint . --ignore-pattern .e2e-server` passed. Generated fixture is not committed.
- Deployment shell syntax and diff whitespace passed.
- Live synthetic Gemini smoke: photo JPEG data URI returned "Red" in 126.8s; video URL returned "blue" in 9.1s; actual PhotoPromptService with its production system prompt/parser returned populated Russian/English prompts in 31.4s with Gemini confirmed by terminal telemetry. No user media or account balance was used. Temporary video fixture removed.
- Initial diagnostic photo attempt timed out at120s, exposing nginx120s as a real release risk. Corrected only exact `/mini-app/api/photo-to-prompt` locations in production backend and both frontend vhosts to900s (default bounded Gemini+Qwen chain ~722s plus overhead). Existing proxy/CORS/security headers copied intact. Original broader route timeouts and dev/VK untouched.
- Nginx files: `/etc/nginx/sites-enabled/banano-kling.conf` (first production HTTPS block), `/etc/nginx/sites-available/tanyapp.chillcreative.ru.conf`, `/etc/nginx/sites-available/tanyapp.xn--e1aikcel5c5a.online.conf`. Backups: `/root/<filename>.pre-gemini-20260929T152124Z`; restore those files, `nginx -t`, reload for rollback. Successful syntax test/reload; all3 analysis endpoints reject unsigned requests with401; health remains200. Existing unrelated nginx TLS warnings preserved.
- Diagnostic video fixture initially used wrong URL then restrictive temporary-directory permissions; corrected to readable `/uploads/` fixture before the successful provider call.
- Full safe backend regression: 1,029 passed / 3 skipped in 249.36s (run started before final observability edits). Final affected media/handler/billing suites: 61 passed. Final PR CI reruns the entire tree.
- Standards finding resolved with task-local correlation across provider/fallback/terminal outcomes and caller user identity; RED test failed on missing correlation context, then GREEN. Sanitized failure categories and no media/prompt/key in logs. Changed-line Ruff: 0; new files formatted.
- Remaining: exact-head CI, authorized merge to `tanyapi`, exact merge CI/autodeploy, production read-only API/static/telemetry verification. Final merge/deploy evidence is recorded in PR #208 and the delivery report because the release SHA cannot be embedded in its own commit.

## 2026-09-29 — KIE Gemini 3.1 Pro media analysis (scope addition)

- User supplied https://kie.ai/gemini-3-1-pro for photo/video analysis. Existing photo, video and V2 photo analyzer share user flows and parsers; Qwen primary, GPT/Claude voice and video fallback exist. Assume replacement of current media primary, preserving text-only/voice paths.
- Contract verified: https://docs.kie.ai/market/gemini/gemini-3-1-pro, POST `/gemini-3.1-pro/v1/chat/completions`, Bearer KIE key; photo/video both use content `type=image_url`, `image_url.url`; `stream=false`, `include_thoughts=false`, supported `reasoning_effort=high`. Do not send undocumented max_tokens or OpenRouter reasoning fields.
- TODO/TDD: (1) adapter HTTP tests RED with media payload/response and finite errors; (2) implement explicit adapter; (3) public photo/video service tests RED then route through Gemini; (4) preserve existing voice/text behavior and fallback; (5) add validated DB setting `media_analysis_provider` and authenticated `/analysis_provider` command with audit; (6) regression/refund checks; (7) review, documentation, combined CI/release.
- Runtime choice: `kie_gemini31` default / `qwen38` rollback; database setting avoids source changes for selection. Existing `KIE_AI_API_KEY` secret; no new credential or migration. Timeout/retry managed config with bounded values. Existing billing unchanged.
- Observability: provider/model, request correlation ID, attempt, HTTP status and duration; never log media, prompt, credentials or provider response body.
- Risks: external media access and malformed/provider failure; finite timeout/retry and existing user refund handling. Native video URL preserves full video (not just frames); existing fallback remains available. Live smoke uses synthetic media only if run.
- Test seams: local HTTP provider server, public analysis services with external provider boundary fake, admin command/real settings DB, existing billing suites. No generation-provider migration or new UI.
- Progress: adapter contract RED (module absent, 2 cases) → GREEN; photo/video/V2 public services RED (old Qwen path, 3 cases) → GREEN; admin switch RED (missing command) → implemented. Existing Qwen tests explicitly select the supported rollback setting. Transport invalid-response, 401, 429 retry, timeout and fallback regression tests added.


## 2026-09-29 — Personalized trend links and combined production release

### Scope and audit
- Authorized: user requests trend referral links, detailed TODO/TDD/checklist and merge into `tanyapi`.
- Fresh baseline `origin/tanyapi`: `932e48dec9de5be2f84cc92cf351377c92c3491c`; existing PR #208 head `6b919ee671882d73a2e5dfc6681d3f5a4d80b3fe`, previous CI fully green. Continue same isolated task branch for combined release.
- Existing: authenticated `/mini-app/api/prompts/link` and v1 alias; builder supports `prompt_ID_ref_CODE`; backend referral parser and frontend navigation support combined parameter. Each registered account already has its own referral code. Missing: endpoint supplies no code.
- Reuse real user context, persisted referral code, existing builder/parser, attribution and privacy middleware. No prefactor or schema/config/admin change required. No hardcoded business values.
- Product result: copying a trend link attaches the copying account's code (including partners), opens the chosen trend, and applies existing referral eligibility/commission rules. Links preserve existing eligibility: attribution requires an approved/admin/legacy partner under the existing approval guard; copying never upgrades partner status.
- Security: never accept caller-supplied referral_code/user_id, never use trend author's code. Existing template permissions and hidden prompt protection remain. Legacy links stay valid. No payment/provider mutation in link generation.
- Observability: existing HTTP logs plus attribution events (`source`, start_param, user/referrer IDs, reason) cover the flow. Tests verify rejection/idempotency; no raw initData/prompt logging.
- Telegram: links deliberately use Mini App `startapp`; Telegram trend navigation remains unchanged. Bot `/start` legacy sharing is not a new surface in this task.

### Detailed TODO / acceptance checklist
1. [x] RED: actual HTTP copy-link response contains authenticated sharer's code, not template author's or supplied spoof code.
2. [x] GREEN: minimal endpoint change reusing link builder. No referral mutation while copying.
3. [x] Security/API: invalid/missing signature rejected; missing/private template denied; public response hides prompt; no-code fallback retains plain link; v1 alias has same ownership behavior.
4. [x] Attribution: combined link attaches eligible visitor once; self-referral and reassignment rejected; repeated clicks do not duplicate bonus. Existing payment/partner suites remain green.
5. [x] UI/navigation: copy button copies exact response URL; old/new startapp parameters open same template; errors remain visible; browser E2E exercises clipboard.
6. [x] Seedance combined regression: 30,000 accepted / 30,001 rejected and no truncation; both forms Unicode-aware.
7. [x] Documentation: describe copying-account attribution, existing eligibility, legacy links and no changes to economics.
8. [x] Verification: focused backend; referral regressions; all frontend tests/build; browser E2E; changed-line Ruff; deployment shell syntax; clean diff.
9. [x] Review: Standards and Spec against baseline/spec here, fix blockers; update PR title/body to combined final scope.
10. [ ] Release: push, exact-head CI green, merge PR to `tanyapi`, record exact merge SHA.
11. [ ] Production: exact merge CI/autodeploy success; container revision/health; Mini App revision/static content; authenticated copy-link read-only smoke; prompt limit; fresh error telemetry. No paid generation or live referral mutation needed.

### Test seams and rollout
- Public HTTP (signed Telegram initData + isolated DB; mock Telegram network only), public referral service/DB interfaces, UI clipboard and start-param navigation, browser E2E, deployed read-only smoke. These are the repository-mandated public seams; no separate permission pause required under AGENTS.md autonomy.
- DB integration applies for identity/attribution; migrations N/A; payment/refund regressions apply without economic changes; provider contract remains Seedance maxLength only.
- Rollback: revert combined PR through `tanyapi` CI/CD. No manual deployment while autodeploy is healthy.
- Progress: signed HTTP test RED (missing `_ref_`) → minimal endpoint change → GREEN. Isolated referral/Seedance/privacy suites: 77 passed; frontend: 19 suites / 50 tests passed; browser E2E (clipboard included): passed. Broad-run fixture failures identified stale module DB path/schema-cache state and fixed in test isolation only. Review Standards/Spec: no blockers; requested no-code fallback test added. Release checks pending combined Gemini addition.


## 2026-09-29 — Seedance 2.5 prompt limit

- Baseline: `932e48dec9de5be2f84cc92cf351377c92c3491c` (`origin/tanyapi`). Isolated branch `fix/seedance25-prompt-limit`.
- Intended result: accept up to 30,000 prompt characters without truncation in Seedance 2.5, aligning Telegram, public/admin Mini App and provider validation.
- Audit: provider adapter and both forms enforce 5,000; Telegram checks use the adapter constant but messages duplicate 5,000. Existing provider/handler tests can be reused. No prefactor required beyond shared UI contract constant.
- Provider evidence: https://docs.kie.ai/market/bytedance/seedance-2-5 retrieved 2026-09-29; embedded OpenAPI prompt schema states `maxLength: 30000`, description “Max length: 30000 characters”.
- No-hardcode decision: this is an external API technical maximum, not a business quota; retain adapter constant and share one frontend contract constant. No admin setting, pricing, schema, migration, routing or payment change.
- Related inquiry: trend copy endpoint currently omits referral code although link builder/parser support `prompt_ID_ref_CODE`. Explanation only pending clarification of requested behavior.
- Logs: targeted scan of current/previous bot log found no prompt-length error matches. No production mutation.
- Risks: JavaScript UTF-16 length must count Unicode code points to match Python. Telegram single-message size remains a separate constraint; Mini App supports long text.
- Verification: provider payload boundary at 5,001/30,000/30,001; public scenario guard; relevant Seedance regression suites; frontend type/build checks. Existing auth/payment/provider-response/refund behavior is unchanged. No DB/migration integration required; no live paid generation required.
- Observability: preserve existing validation errors and generation telemetry; no new log of prompt text.
- Rollout: PR to `tanyapi`; production update must be verified separately after merge. Rollback through reverting the PR.
- Steps: (1) regression tests red; (2) align adapter, Telegram copy and forms; (3) tests/build/review; (4) PR and report.
- Progress: implemented adapter maximum 30,000, shared frontend constant, Unicode-aware counters and Telegram text derived from adapter constant. Public/admin forms and shared server guard accept the boundary and reject 30,001.
- Skills/guidance: Bambale0/skills `diagnosing-bugs` (reproduction/regression loop; narrowed to an outdated documented limit); Bambale0/claw README (existing architecture/config/release discipline); anthropics/skills `webapp-testing` inspected (browser guidance; component tests used here).
- Verification evidence:
  - `/root/tanya/banano_kling/venv/bin/python -m pytest tests/test_seedance_25_spec.py -q -k 'long_prompt or overlong_prompt'` before implementation: 3 expected failures, old 5,000-character rejection.
  - `/root/tanya/banano_kling/venv/bin/python -m pytest tests/test_seedance_25_spec.py tests/test_seedance_25_fullstack.py tests/test_seedance_25_new_priority.py tests/test_seedance_25_telegram_compat.py tests/test_trend_seedance_25_compat.py -q`: 33 passed.
  - `npm --prefix frontend/miniapp-v0 test -- --runInBand seedance25-prompt-limit`: 19 suites / 49 tests passed (worktree path matches the filter, so all frontend suites ran), including both forms' Unicode boundaries.
  - `npm run build` in frontend: passed, including TypeScript and static export.
  - `eslint components/forms/seedance25-public-form.tsx components/forms/seedance25-admin-form.tsx components/forms/seedance25-prompt-limit.test.tsx lib/seedance25-api.ts`: passed.
  - `python -m compileall -q` for the three touched backend modules and `git diff --check`: passed.
  - Full-file Ruff reports 12 pre-existing findings in adapter/preview. `PATH=/root/tanya/banano_kling/venv/bin:$PATH python scripts/ruff_changed_lines.py --base origin/tanyapi --head HEAD` with the five touched Python files: passed, relevant=0 / ignored_legacy=12. Initial attempt lacked Ruff in PATH; rerun succeeded. `bash -n scripts/deploy_backend_docker.sh scripts/backup_db.sh cdn.sh`: passed.
  - Initial broader pytest invocation referenced `test_video_generation_compat.py`, which exists only in the original checkout, not the baseline Git tree; no tests ran for that invocation. Corrected invocation above passes.
- Remaining verification: CI for PR, browser E2E and live generation/deployment smoke have not been run. No production update claimed. No DB/config/admin migration.


## 2026-09-28 — Seedance 2.5 feed publication diagnosis

### Incident
- Baseline: `tanyapi` at `b5cf3ecc27e55086cf39796754ca4a422b7db3f8`.
- User symptom: a Seedance 2.5 video cannot be published to the public feed from the bot; one user reportedly cannot publish the same model from Studio/Mini App either.
- Concrete production row from the screenshot: task `4d622e9b69934e975d5bcb3ca957e395`, DB id `274093`, model `seedance_2_5`, type `video`, status `completed`, result `https://tempfile.aiquickdraw.com/seedance/...mp4`, `completed_at=NULL`, not yet public/profile-visible.
- Production logs show repeated media reads for that task through `/mini-app/api/media/...`, but no nearby `POST /mini-app/api/generations/share` line tied to that task id. Separate bot logs show feed publication can be rejected before share when the callback task id points to a row the guard does not consider ready.

### Intended result
- Completed Seedance 2.5 videos can be published to the general feed and profile from both Telegram result buttons and Mini App Studio.
- Publication returns a normal feed/profile card and preserves prompt/reference visibility options.
- External provider video results are localized to durable feed storage when possible; publication does not fail merely because localization falls back for video.

### Current-state audit
- Reuse: `share_to_feed`, `publication_scope_compat.share_to_feed_scoped`, `persist_feed_result_urls`, Mini App `/generations/share`, Telegram `feedpub_*`.
- Seedance 2.5 completion is handled by `bot/handlers/seedance_25_fullstack.py` and stores `result_url/result_urls/status`, but currently leaves `completed_at` unset.
- Feed availability uses shared `_feed_result_urls` TTL policy and timestamps from `completed_at`, `updated_at`, `created_at`.
- No schema or pricing change expected.

### Test plan
- Add a focused backend regression for a completed `seedance_2_5` video with `completed_at=NULL` and a `tempfile.aiquickdraw.com/seedance/*.mp4` result.
- Verify both generic `database.share_to_feed` and scoped publication behavior remain able to return a public card.
- Run focused pytest plus py_compile for touched modules.

### Result
- Root cause confirmed for the Telegram side: Seedance 2.5 result delivery used its own send path and did not attach the standard video result keyboard, so users had no bot-side publication action for completed Seedance 2.5 videos.
- Mini App API/core publication guard accepts the reported completed Seedance 2.5 video shape; no model-specific publication block was found there.
- Fix: attach `get_video_result_keyboard(..., model="seedance_2_5")` to Seedance 2.5 result messages for direct URL send, downloaded-file send and fallback text send paths.
- Fix: set `completed_at` when the Seedance 2.5 webhook stores a successful result, keeping feed TTL/card metadata aligned with other completed generations.
- Verification:
  - `./venv/bin/python -m pytest tests/test_seedance_25_fullstack.py -q -k 'result_message_has_feed_keyboard or seedance25_model_meta or miniapp_repeat_keeps_source_lineage'` — passed, 4 tests.
  - `./venv/bin/python -m pytest tests/test_database.py -q -k 'seedance25_video_without_completed_at'` — passed, 1 test.
  - `./venv/bin/python -m py_compile bot/handlers/seedance_25_fullstack.py bot/handlers/seedance_25_public_release.py` — passed.
  - `./venv/bin/python -m pytest tests/test_seedance_25_fullstack.py tests/test_video_generation_compat.py tests/test_trend_seedance_25_compat.py -q` — passed, 14 tests.
  - `./venv/bin/python -m pytest tests/test_seedance_25_fullstack.py tests/test_database.py -q` — passed, 49 tests.
- No production write/deploy was performed during diagnosis.

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

---

## 2026-09-27 — Trend repeat price preview

### Goal
- Show the user the exact retail cost of repeating a curated photo/video trend before they upload references or launch generation.
- Keep pricing server-owned and derived from the administrator-configured model, duration, quality and resolution stored in generation_settings.

### Implementation
- Added a single backend repeat-cost estimator that resolves current pricing from the same runtime pricing functions used by trend execution.
- Image trend execution, generic video trend execution and dedicated Seedance 2.5 trend execution now reuse that estimator for the actual debit amount.
- Trend list/detail responses include repeat_cost; newly created admin trends receive the price immediately in the submit response.
- Mini App trend cards render `Повторить · <price>🍌`.
- Trend runner renders `Сгенерировать · <price>🍌`; the old photo-count label was removed from the launch button while reference counts remain in the upload UI.
- No pricing values are hardcoded in the frontend.

### Verification
- Backend pricing/trend focused suite: 24/24 passed.
- Expanded production backend suite: 996 passed, 3 skipped.
- Mini App Jest: 47/47 passed.
- Mini App ESLint: clean.
- Mini App production build/TypeScript: clean.
- Mini App critical browser E2E: passed after updating the expected repeat-price labels.
- Added regressions for dynamic backend photo/video pricing, trend-card price display and runner price display.

### Rollout
- Task branch: feature/tanyapi-trend-repeat-price.
- PR target: tanyapi with auto-merge after required CI gates.
- After deployment verify exact backend/Mini App SHA and live repeat_cost values for existing production trends.
