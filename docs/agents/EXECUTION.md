# Execution ledger

## 2026-10-01 — Seedance 2.0 photo-reference prompt regression

- Baseline: `origin/tanyapi` `1840ba0dd4f39ceadfd58023f10b0654c1fbcbb8`; branch `fix/seedance20-photo-ref-prompt`.
- Reported production symptom: Telegram Seedance 2.0 shows `Фото-референсы: 1/9`, but typing a prompt can answer `Сначала отправьте стартовое фото.` instead of launching.
- Runtime evidence: at `2026-10-01 09:59:56 UTC` user prompt reached `handle_video_prompt_text`; no video launch followed. Source inspection reproduced the contradiction: Seedance compatibility stores every photo in `reference_images` with `v_image_url=None`, while the legacy prompt guard still requires `v_image_url` whenever `video_flow_step != configure`.
- Root cause: the reference-only compatibility layer patches Seedance media/provider launch semantics, but the legacy text-prompt precondition runs before that launcher wrapper and still assumes first-frame semantics.
- Intended result: Seedance 2.0 `Фото + Текст` accepts a non-empty `reference_images` set as its required media even when the flow is still on the media step; other models retain their existing start-frame validation. Empty Seedance photo mode asks for a photo-reference, not a start frame.
- No-hardcode/schema/provider impact: no pricing, provider routing, DB schema, payment/referral, Mini App or Seedance provider payload changes. Existing `seedance_2` technical model contract is reused.
- TDD: added a regression that reproduces `v_model=seedance_2`, `v_type=imgtxt`, `v_image_url=None`, one `reference_images` URL, `video_flow_step=media`. Before fix: 1 failed / 3 passed because launch was blocked. After fix: 4 passed.
- Focused verification: Seedance reference-only, multimodal, 2.5 compatibility and prompt-flow suites — 53 passed; `py_compile` for generation and compatibility handlers passed.
- Full safe regression on the task worktree: 1081 passed, 3 skipped, 87 warnings in 44.42s. Targeted Ruff on the regression test and `git diff --check` passed.
- Rollout: PR to `tanyapi`, CI, merge, automatic production deploy, then exact deployed SHA/health and Telegram reference-only smoke. No manual paid generation unless explicitly needed; use admin/free smoke path.
- Changed-line Ruff gate: relevant=0, ignored legacy findings=93 across the two touched Python files; `git diff --check origin/tanyapi...HEAD` passed.
- Remaining: [x] changed-line lint/diff review; [x] full safe regression; [ ] PR/CI/merge; [ ] production exact-SHA + smoke/log verification.

## 2026-09-29 — Gemini photo-analysis instructions

- User clarified: improve Gemini instructions for photo analysis. Baseline fresh tanyapi cba7d59. Branch fix/gemini-photo-instructions.
- Audit: both PhotoPromptService and PromptAnalyzerV2Service route photo-only input through Gemini3.1Pro and fall back to Qwen. They currently reuse generic system prompts with editorial/photorealistic bias and conflicting reference-preservation guidance. Output contracts differ: classic structured9fields and V2 RU/EN only. Voice/video keep existing prompts/providers.
- Goal: faithful visual reconstruction in the reference medium, explicit edits take precedence over defaults, concrete composition/pose/light/material cues, no invented unseen details/EXIF/identity, equivalent RU/EN prompts, proportional detail without filler.
- Reuse provider adapter, bot_settings (audited author/time), existing parser and billing. Shared Gemini-only guidance with per-surface fixed JSON contracts; admin-only /gemini_photo_prompt view/set/reset. No schema, price, FSM, UI or provider changes.
- No-hardcode: editable analysis guidance stored via existing bot_settings with versioned default; schema/output constraints remain technical constants. Validation bounds content size; prompt revision logged without source text or media.
- Test seams preselected by AGENTS: public analysis services against local HTTP provider + real isolated settings DB; authenticated admin handler via mocked Telegram boundary; full regression; synthetic live Gemini result inspected for fidelity and explicit edits.
- Verification:1054 passed/3skipped before final trace changes. Live synthetic V2 Gemini30.0s and classic14.3s both retained two colored shapes/positions/flat2D medium, applied only requested pink background, agreed RU/EN. No customer data or credits. Spec/Standards reviews no blockers; trace-correlation suggestion implemented with RED→GREEN tests linking selected instruction revision/request/outcome and clearing Gemini revision on Qwen fallback. Added inline admin editing and unauthorized download regressions.
- Progress: public-service HTTP tests RED (configured guidance absent from Gemini request on both surfaces) → GREEN; admin tests RED (command absent) → GREEN.46 focused tests passed. Full regression and synthetic live evaluation running.
- TODO: [x] RED configured guidance reaches both public photo surfaces; [x] minimal shared builder/integration; [x] admin auth/edit/reset regressions; [ ] regressions/real synthetic eval/review; [ ] PR exact CI/merge/autodeploy; [ ] runtime SHA/health/prompt revision.
- Checklist: both schemas retained; custom guidance applies without release; default/reset works; unauthorized/empty/oversized updates rejected without mutation; Qwen/voice/video behavior preserved; user intent and image remain present; no prompts/media/secrets in telemetry; normal responsiveness retained.
- Rollout: normal PR to tanyapi, exact merge CI and autodeploy, production read-only config inspection plus synthetic photo analysis (no user balances/media). Rollback via PR revert or admin config reset. Final release evidence in PR.


## 2026-09-29 — Ordinary bot command/button latency incident

- Additional root cause before release: unconditional startup tracemalloc.start(25) traces every allocation. Synthetic JSON workload inside production container: tracing off0.0156s,1frame0.2123s,25frames0.7143s (~46x overhead). SQL/privacy optimizations alone cannot explain/fix this shared-event-loop CPU tax.
- TDD memory diagnostics:6 regressions RED on unconditional tracing/default dump/config, then explicit opt-in implementation. MEMORY_TRACING_ENABLED defaults0; MEMORY_TRACING_FRAMES defaults1, validated/clamped1..25. RSS/GC/process reports remain available without allocation tracing; dumps report tracing enabled/disabled explicitly. External pre-existing tracing remains respected.
- Additional memory Spec/Standards reviews: no blockers. Six memory regressions and combined diagnostics/privacy/completion13 passed; pre-existing runtime tracing regression added on review recommendation. New test force-added despite tests/* ignore.
- Full local suite before this addition1039 passed/3skipped; previous-head CI checks succeeded through browser E2E. Rerun affected suite/review and exact final-head CI; no merge before these changes pass.

- User reports slow ordinary Telegram commands/buttons after combined release; baseline production and origin/tanyapi `3c3b96a`. Dedicated branch `fix/bot-response-latency`.
- Evidence: healthy container occupies ~100% of one CPU; Telegram pending_update_count0; update durations reach34,649ms. Initial external health3.317s; six local health samples0.086–0.349s show intermittent rather than constant stalls.
- Twenty-second nonblocking py-spy sample: heavy Mini App bootstrap/privacy work on shared event loop. 15-minute logs:915 bootstrap requests,373 updates. Ten-minute bootstrap response median13,844bytes/max21,705bytes, so no huge response payload.
- PostgreSQL diagnosis: history query by telegram_id/created_at has no matching index; EXPLAIN ANALYZE visits~279k rows/47,869blocks,68.44ms at low contention. Concurrent completion/repeat queries use task_id OR JSON alias EXISTS and scan every row even for indexed canonical IDs; observed active queries4–27s.
- Privacy resolver calls enriched public trend list merely to compare prompt text, unnecessarily deserializing settings and computing success counters.
- Ranked hypotheses: shared event-loop work; expensive DB scans/pool pressure; Telegram network. Evidence supports first2; queue0.
- Plan: add concurrent history index (non-destructive; persist in schema setup), fast canonical task resolution retaining alias fallback and repeat-credit idempotency, lean privacy lookup preserving fail-closed/legacy behavior. No prices/provider defaults/referral economics changed.
- Public test seams: database task completion/repeat invariants + isolated DB alias cases, task API sanitization/privacy, backend regression and deployed latency/telemetry. Add regression before code for identified scan pattern where feasible. Fresh read-only EXPLAIN and update duration/CPU samples compare production before/after.
- Rollout: normal task PR to tanyapi with CI; verify exact deployment and original latency signals. No customer messages/synthetic paid generation. Temporary profiler output only under/tmp.
- Index applied online: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_generation_tasks_telegram_created ON generation_tasks (telegram_id, created_at DESC)`. PostgreSQL EXPLAIN changed parallel sequential scan~279k rows/47,869blocks (68.440ms) to index scan~15blocks (0.133ms). Schema bootstrap now keeps the index for future installs. Rollback if necessary: DROP INDEX CONCURRENTLY; retaining this additive index across code rollback is safe.
- RED canonical completion regression on200 historical tasks observed400 irrelevant json_valid evaluations across update/reward lookup. GREEN after indexed canonical fast paths:0. Original alias fallback retained.
- RED privacy regression: oldest approved recipe outside top100 leaked through legacy task sanitization; GREEN with raw recipe projection instead of enriched/paginated catalog. No prompt/settings/counter expansion needed; explicit trend/source tasks skip recipe lookup.
- Focused database/task/alias/privacy/referral/watchdog suites:85 passed. Additional persisted alias→canonical→alias completion replay: reward credited once; combined new privacy/completion tests7 passed.
- Read-only production-data privacy benchmark (8recent tasks, no user media/logged prompts): legacy un-enriched implementation11.7/8.9ms, candidate4.8/6.5ms. Actual running legacy path also computes catalog success counters, which this conservative comparison omits.
- Two independent reviews (Spec/Standards): no blockers. Nonblocking full-catalog recipe scaling remains, measured above; avoid speculative caching of privacy decisions. New ignored test file explicitly force-added for CI. Existing mock-SQL completion tests adjusted for canonical parameter count; behavior tests cover persisted completion and reward.
- Source syntax and whitespace checks; changed-line Ruff before PR. Full safe suite in progress.
- TODO: [x] history index/preflight; [x] regression RED; [x] fixes GREEN; [x] expanded focused regressions/review; [ ] full suite/PR/CI/merge/autodeploy; [ ] production measurements. Final release SHA/telemetry recorded in PR/delivery report.

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

---

## 2026-09-30 — Gemini 3.1 media analysis stays on Gemini

### Incident
- Production tanyapi logged 13 provider_failure provider=kie_gemini31 error=invalid_response events in the previous 10 hours.
- Fresh example request_id=95f5d5ee6b694ae0bcf7e7876cce41e7 received HTTP 200 from KIE, was classified as invalid_response, and automatically fell back to Qwen 3.8.
- Product requirement: when media_analysis_provider=kie_gemini31, photo/video/v2 media analysis must remain on Gemini; Qwen may only run when explicitly selected by the admin setting.

### Baseline
- Branch: tanyapi
- SHA: 0ac2d3e3f4a951b216b5fd1d8cc82297a7d42920
- KIE Gemini adapter treated malformed/empty HTTP-200 responses as terminal on the first attempt.
- Photo, video and v2 services caught Gemini runtime errors and automatically routed to Qwen.

### Fix
- Retry malformed/empty successful HTTP responses within the bounded Gemini attempt budget.
- Accept standard string content and text-block content without logging provider/user content.
- Add sanitized response-shape telemetry (keys/types/finish reason/body code only) for malformed responses.
- Remove implicit Qwen fallback when Gemini is selected. Explicit media_analysis_provider=qwen38 behavior remains supported.

### Verification
- RED regression before implementation: 5/5 focused tests failed on the old behavior.
- GREEN focused regression after implementation: 5/5 passed.
- Full Gemini media-analysis file: 21/21 passed in project venv.
- Adjacent suite exposed one pre-existing prompt_analyzer_v2 text-only Qwen test failure; the same test fails unchanged at baseline SHA, so it is outside this fix.

### Rollout
- Task branch: fix/gemini31-invalid-response-retry.
- PR target: tanyapi.
- After merge: verify exact deployed SHA, bot health, live Gemini-only media-analysis smoke and telemetry (provider_retry/provider_success, no automatic fallback provider=qwen38).

### Review
- Standards axis: bounded retry remains configuration-driven; no secrets or provider/user content are logged; response telemetry records structural metadata only; no payment/FSM/schema contract changed; no debug instrumentation remains.
- Spec axis: when media_analysis_provider=kie_gemini31, photo/video/v2 image analysis no longer falls through to Qwen; malformed/empty HTTP-200 responses retry Gemini within the existing attempt budget. Qwen executes only when explicitly selected.
- Explicit Qwen routing tests now select qwen38 through the same bot setting used in production. Existing prompt-v2 text-only explicit-Qwen routing was aligned with that contract.
- Production bot setting re-verified as kie_gemini31 after isolated tests.
- Final isolated backend gate: ruff checks passed; full pytest 1344 passed, 2 skipped, 123 warnings.

---

## 2026-09-30 — Gemini 3.1 provider-to-provider fallback

### Incident
- Production smoke after PR #211 confirmed KIE Gemini 3.1 Pro can return HTTP 200 with application body code=500.
- KIE retry remained on Gemini but two consecutive body=500 responses still caused terminal failure.
- KIE Gemini 3 Flash and Gemini 2.5 Flash channels returned application 422 (channel not supported) for this account.
- OpenRouter exposes google/gemini-3.1-pro-preview and live smoke succeeded for both image and video inputs.

### Fix
- Keep KIE gemini-3.1-pro as primary transport.
- On KIE upstream/transient exhaustion or body code>=500, fall back to OpenRouter google/gemini-3.1-pro-preview.
- Preserve media kind so image fallback sends image_url and video fallback sends video_url.
- Qwen is not part of this fallback chain.

### Verification
- Focused body-500 fallback tests cover image and video.
- Timeout fallback regression updated to Gemini->Gemini behavior.
- Full isolated backend gate: 1346 passed, 2 skipped.
- Ruff focused checks passed.

### WAN audit
- Production model is wan/2-7-image-pro through KIE.
- Latest 100 WAN rows: 89 completed / 11 failed; completed p50 31.3s, p95 38.8s, max 41.1s.
- Fresh failures on Sep 28 were KIE green-net moderation (input/output image), not transport failures.
- Existing WAN auto-retry intentionally covers timeout failures only; moderation failures were not auto-retried.

---

## 2026-09-30 — KIE-only Gemini fallback

### Requirement
- Media analysis must not use OpenRouter as an automatic fallback.
- Primary: KIE Gemini 3.1 Pro.
- Fallback: another Gemini model through KIE only.

### Evidence
- KIE Gemini 3 Flash and Gemini 2.5 Flash returned application code 422 (channel not supported) on the production KIE key.
- KIE Gemini 3.5 Flash OpenAI-compatible endpoint /gemini-3-5-flash-openai/v1/chat/completions with model gemini-3-5-flash-thinking succeeded live for both image and video inputs.

### Fix
- Removed automatic OpenRouter Gemini 3.1 fallback adapter and config.
- KIE Gemini 3.1 Pro remains primary.
- KIE Gemini 3.5 Flash is the only automatic fallback for body code>=500, retry exhaustion, malformed/empty terminal responses, or network exhaustion.
- Fallback endpoint/model/max attempts are env-configurable.

### Verification
- Focused regression: 8 passed.
- Full isolated backend gate: 1346 passed, 2 skipped.
- Ruff focused checks passed.
- No openrouter_gemini31 / OPENROUTER_GEMINI31 references remain in bot/tests/deployment/.env.example.


---

## 2026-09-30 — KIE Gemini 3.8 Flash fallback

### Requirement
- Keep media analysis entirely on KIE when Gemini is selected.
- Primary remains KIE Gemini 3.1 Pro.
- Automatic fallback must use KIE Gemini 3.8 Flash, not OpenRouter and not Qwen.

### Baseline
- Branch baseline: tanyapi.
- Baseline SHA: 028214567f2ade09dca1b5d7dac8faa8c56e82ae.
- PR #213 already removed OpenRouter from the automatic fallback chain but defaulted the KIE fallback to Gemini 3.5 Flash.
- Production container observed before this patch was still on older SHA 7545686254b36a468008a4af86b3c216448d901c, where OpenRouter fallback was still active.

### Provider contract
- Official KIE endpoint: /gemini-3-8-flash-openai/v1/chat/completions.
- Fallback model identifier retained for configuration and telemetry: gemini-3-8-flash; the endpoint-specific request body omits model.
- KIE documents the endpoint as multimodal and uses the unified image_url media envelope for media inputs.
- KIE's endpoint-specific request example omits the model field; live contract testing confirmed this matters for video on the production key.
- Existing bounded timeout/retry behavior is preserved.

### Implementation
- Default KIE media-analysis fallback model changed from Gemini 3.5 Flash to Gemini 3.8 Flash.
- Default fallback endpoint changed to the Gemini 3.8 Flash OpenAI-compatible endpoint.
- Fallback requests omit the redundant model field and rely on the model-specific KIE endpoint; the configured model name is retained for telemetry.
- Fallback trace provider changed from the stale model-specific kie_gemini35_flash label to kie_gemini_fallback; the concrete KIE model remains present in the structured provider log.
- No OpenRouter fallback is introduced.
- Fallback model/endpoint/attempt count remain environment-configurable.

### TDD evidence
- RED: body-code-500 image/video fallback regression failed because telemetry still reported kie_gemini35_flash.
- GREEN: body-code-500 image/video fallback regression passed after telemetry fix.
- RED: timeout fallback regression failed against the Gemini 3.8 endpoint while defaults still pointed to Gemini 3.5.
- GREEN: timeout fallback regression passed after updating the defaults.
- Focused media-analysis suite after implementation: 23 passed.
- Focused Ruff checks passed.
- Full backend gate from the isolated worktree before the provider-contract refinement: 1058 passed, 3 skipped.
- Live KIE 3.8 image smoke on the production API key succeeded.
- Live KIE 3.8 video smoke with an explicit model field timed out at 120s; the same 107 KB public MP4 without the model field returned HTTP 200 in 20.13s with a valid description.
- Added a regression asserting the fallback request body does not include model; RED before the fix, GREEN after the fix.
- Final full backend gate after the provider-contract refinement: 1058 passed, 3 skipped, 88 warnings.

### Rollout plan
1. Run focused lint and full backend pytest from the isolated worktree.
2. Review diff against tanyapi.
3. Commit/push task branch and open PR to tanyapi.
4. Merge only after required CI is green.
5. Verify exact production SHA, container health, and live telemetry shows KIE Gemini 3.1 primary with KIE Gemini 3.8 fallback and no openrouter_gemini31 fallback.

## 2026-09-30 — Complete PR #216: Seedance delivery and refund recovery

- Baseline: `tanyapi` at `5b33cdf86074b0314955151d76b5147824abc5ae`; reviewed PR head `f159adc13dcde099e3ee46449c93bd0de17afa66`.
- Scope: Seedance 2.5 provider completion, Telegram file delivery and failed-generation refunds. Banana changes explicitly excluded; isolated worktree preserves unrelated working changes.
- Existing: provider adapters, dedicated webhook, periodic reconciliation and request_data JSON delivery metadata. Partial: refund atomicity and delivery leases. Missing: markerless completion recovery, distinction between link and media delivery, protection against duplicate success overwriting a lease.
- Evidence: production logs show CDN timeout/connection reset followed by fallback text and a misleading delivered marker. This PR fixes the Seedance 2.5 path; legacy Seedance 2.0/Grok sender in bot/main.py is outside this PR.
- Reuse: existing DB facade, periodic reconciliation, provider lookup, Telegram adapter. No migration, provider schema, pricing, admin UI or Mini App API change. Financial invariant: at most one refund, committed with its marker; transient DB errors leave recovery eligible.
- Risks: webhook/watchdog concurrency, process death between completion and delivery, unavailable CDN, expired Telegram delivery lease, starvation by older failed deliveries.
- No-hardcode: download retry/timeout/backoff and delivery timeout/retry age use environment configuration. Delivery window uses immutable completed_at, not updated_at. No secrets added.
- Observability: task ID and delivery_status distinguish pending media, link_sent, delivering and delivered; delivery_link_sent suppresses repeated fallback texts. Existing refund logs retain task ID.
- Verification layers: backend/domain and DB integration required; PostgreSQL contention check required; webhook/reconcile and Mini App backend regression required. UI/FSM contracts and provider payload unchanged; existing CI browser E2E retained. No new migration. Production health/SHA/log smoke after CI deploy.
- Steps:
  1. Inspect PR, CI, production evidence and three GitHub review findings — complete.
  2. Independent standards/spec review via Bambale0/skills code-review — identified link-only false delivery, success replay race, retry window and missing docs.
  3. Add regressions — refund exception, link-only delivery and markerless completion reproduced failures before fixes.
  4. Fix recovery and concurrency, document settings — in progress.
  5. Focused/full checks, review final changes, push same PR — pending.
  6. Merge to tanyapi after CI, verify exact deployed SHA/health/telemetry — pending.
- Guidance: Bambale0/skills diagnosing-bugs, code-review; Bambale0/claw QA_AUDIT_CHECKLIST; anthropics/skills webapp-testing (existing browser CI, no frontend changes).
- Refinement after second review: persisting link_sent retains the delivering lease until the attempt finishes; dedicated DB regression checks a concurrent claim remains blocked. Delivery has an explicit total timeout shorter than its lease; cancellation removes partial downloads.
- Local verification: full safe backend suite `1072 passed, 3 skipped`; final focused suite after link-lease regression `87 passed`. PostgreSQL 16 isolated contention harness passed: watchdog waited on webhook row lock and observed the committed refund marker; concurrent webhook refund transactions credited once. No production writes during checks.

- Rollout audit found 200 legacy completed Seedance 2.5 tasks without delivery markers. To avoid resending previously delivered videos, completion and result_ready now commit atomically under the task row lock. Missing-marker legacy tasks are excluded from automatic replay; this supersedes the earlier missing-marker query approach. Added explicit legacy replay regression.
- Final code verification at b2e4027: full safe suite `1076 passed, 3 skipped` (39.19s); changed-line Ruff gate passed; deployment shell syntax passed. Additional regressions prove result+marker rollback and refund+credit rollback. Isolated PostgreSQL confirmed atomic completion marker, duplicate-success lease preservation and single credit under webhook/watchdog contention. Final independent spec review found no confirmed blocker.
- Excluded Banana tracked WIP is preserved as stash `fad97979e13142b792d86268f385efd308cbfb8d`; production checkout now has no tracked edits blocking CI deploy. No Banana changes are included in PR #216.
- Steps 1–5 complete locally; latest-head GitHub CI and subsequent merge/deploy verification remain release gates. Post-merge SHA, CI/deploy links and smoke evidence will be recorded in the PR delivery report.

## 2026-10-01 — Seedance 2.5 explicit video editing

- Baseline: `tanyapi` / `b5fcf18f0025c91e684233798bea06d232c177e7`; isolated branch `fix/seedance25-edit-duration`.
- Reported provider task `703fa69cddd2c08a3a2c2dcc25dc7fe7`: read-only KIE record confirmed terminal `fail`, code `400`, input duration `12`, ratio `adaptive`, one video reference. Provider classified the prompt as editing and required duration `-1`. Production image label matched baseline SHA; no generation replay or production write performed.
- Existing: adapter supports Auto, shared public Telegram/Mini App launch, atomic failure refund, reference normalization, local ffprobe validation, repeat restoration. Missing: explicit editing intent and consistent constrained settings. Reuse those seams; no preliminary refactor needed.
- Ranked hypotheses: (1) prompt-classified editing with numeric duration causes this error (confirmed by provider record); (2) source below four seconds could cause a further rejection (validate local media); (3) non-adaptive ratio could fail editing (already adaptive in this incident); (4) duplicate callback/accounting issues cannot explain provider duration validation.
- Intended result: explicit admin editing sends `-1/adaptive` with exactly one source video; ordinary reference generation retains selected settings. Editing controls explain source length 4–30 and preserved source ratio/duration. Public editing rejected before any debit or provider call.
- No-hardcode: `-1`, `adaptive`, source duration bounds and one chosen edit source are technical contract/product input constraints, not prices. Existing admin price configuration, video-reference multiplier and admin-free entitlement preserved. No DB migration/env/admin pricing change; editing stored in request_data JSON.
- Risks: provider chooses task type from prompt; KIE publishes no explicit task-intent field. Mode makes settings compatible, not a promise of provider intent. Admin external URLs/asset IDs have no trusted local metadata; provider validates duration. Public editing remains unavailable until deterministic server-probed source-duration pricing is designed. No automatic retry of failed paid tasks.
- Observability: log editing intent and effective duration/ratio; retain provider/task IDs; actionable hint for the captured provider constraint failure. Never log source URLs or full prompts for this change.
- Verification layers: provider payload, public API/admin permission, Telegram controls, request persistence/repeat, media preflight and frontend user submission require regressions. DB migration N/A (JSON flag); payment invariants preserved and failure/refund regressions run. Trends photo-only and unchanged. Backend safe suite, frontend Jest/type/build and changed-line lint required. Production smoke/SHA/telemetry only if released; no paid live generation authorized by this fix.
- Acceptance: explicit editing normalizes stale fixed settings; normal video-reference generation unchanged; malformed flags/no or multiple source videos fail prelaunch; paid users cannot bypass restriction; local source <4s fails; repeat restores intent; UI wire settings agree with backend; refund idempotency remains intact.
- Guidance: Bambale0/skills diagnosing-bugs → TDD → code-review; Bambale0/claw QA_AUDIT_CHECKLIST; anthropics/skills webapp-testing. Three subagents independently audited provider, flows/billing and frontend, then received separate file ownership for implementation.
- Steps:
  1. Inspect exact production failure, current tanyapi and provider contract — complete.
  2. Independent provider/flow/UI diagnosis and minimal scope — complete.
  3. Regression RED → implementation GREEN at adapter, launch, controls and frontend seams — in progress. Adapter 10 failures before fix, 21 tests pass after. Telegram controls four failures reproduce missing editing toggle/locks/repeat flag.
  4. Focused/full regression, type/build/lint, independent review — pending.
  5. Commit/push and PR to tanyapi; release only after CI gate — pending.
- Original source read-only ffprobe: 12.095 seconds, 720×1280, 30 FPS; one image and one video reference in actual KIE request. Source duration is valid, isolating the wrong request parameter as the cause.
- Independent Standards and Spec reviews found UI Auto-estimate mismatch and missing Mini App source-repeat enrichment. Both fixed: UI/backend share existing five-second Auto estimate; real repeat enrichment preserves strict editing flag and effective parameters. No confirmed high-severity issue remains after follow-up review.
- Final local verification: safe backend `BOT_TOKEN=<test> PYTHONPATH=. python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short`: **1122 passed, 3 skipped**, 40.69s. Initial full gate before continuity refinement: 1117 passed, 3 skipped. Public launch/continuity focused regressions: 27 passed; adapter: 21 passed; Telegram controls/compat: 8 passed.
- Frontend: `npm --prefix frontend/miniapp-v0 test -- --runInBand seedance25 video-tab-repeat feed-video-repeat`: **21 suites / 58 tests passed**. `tsc --noEmit --incremental false`, targeted ESLint, `npm run build` static export passed. `node e2e/critical-flows.mjs` passed against rebuilt export, including existing payment/trend/Pinterest journeys and new admin editing/public fixed-duration wire-payload assertions; API/provider transport mocked, no charged generation.
- `git diff --check`, backend deployment/backup/cdn shell syntax passed. Full-file Ruff has legacy diagnostics outside changed lines; final changed-line gate is the repository release check. New ignored regression files explicitly staged with `git add -f`.
- Steps 1–4 complete locally. Commit/PR and GitHub gates remain; no production release or live generation claimed at this point.
- PR #222 opened at `f9020210d6d8bf17a22928aabf982d086de38e22`. GitHub Python/deploy validation and safe backend suite passed. Secondary browser CI stopped at existing npm audit vulnerabilities (Next.js and brace-expansion), before browser execution; automatic merge disabled until resolved.
- Release-blocker refinement: Next.js minimum `^16.3.6`, locked `16.3.8`; brace-expansion patched in each existing major (`1.1.21`, `2.1.7`, `5.0.12`). Official advisories: [Next.js](https://github.com/advisories/GHSA-vcvr-r3jv-pc5j), [brace-expansion](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr). Only these dependency families updated; no force upgrade. An isolated node_modules install avoids changing the production checkout's dependencies.
- Corrected legacy admin-form reference estimate to include the existing x2 multiplier, matching shared public launch; no charge/pricing policy change. Its editing regression checks the five-second Auto estimate.
- Final dependency verification: `npm ci --ignore-scripts` passed; `npm audit --audit-level=high` reports **0 vulnerabilities**; full frontend Jest **21 suites / 59 tests passed**; TypeScript without incremental output, full ESLint, production export build (Next 16.3.8), expanded Chromium E2E all passed. Backend unchanged since the 1122-test safe gate. Generated browser export moved outside checkout; git diff check clean. New latest-head GitHub CI remains mandatory before merge.
