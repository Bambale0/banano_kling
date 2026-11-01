## 2026-11-01 — Seedance admin-test preview aspect ratio
- Baseline `tanyapi@b213dee0fb561a6d4054abfd169f340ea994e8ea`, task branch `fix/seedance-admin-preview-aspect-20261101`. Main checkout's unrelated runtime price changes are untouched.
- Incident: Telegram inline video preview appears close to square, while the saved/downloaded Seedance 2.5 video is portrait. Read-only Neironych result check for existing request `efbae843-2b47-407a-8ff1-8422319b2222` returned `done`; read-only content fetch + `ffprobe` confirmed H264 720×1280, sample aspect ratio 1:1, display aspect ratio 9:16, duration 12.064 s. No new provider generation or billing.
- Root cause in app boundary: `admin_seedance_test_lab._send_result` uploaded `FSInputFile` without supplying `width`/`height` to Telegram's `sendVideo`, leaving the Telegram client/server to infer layout. Actual iOS rendering after the fix remains to be visually verified.
- Change: read-only bounded `ffprobe` on downloaded temporary MP4; pass validated pixel-display dimensions and rotation to Telegram; on missing/bad probe results, retain previous send behavior rather than fail delivery. No video transcoding, media overwrite, model/config changes, DB migrations or user billing. Source download remains deleted after send.
- TDD: isolated reproduction `1 failed` on baseline, `1 passed` after fix (sendVideo got `None` for `width`/`height` before fix). Orientation/SAR and missing-ffprobe regression tests added. Local focused matrix: `76 passed, 12 subtests passed`; Ruff, compileall, diff whitespace and real `ffprobe` on a generated portrait MP4 (`360×640`) passed. Exact-head PR CI, production SHA and Telegram-iOS visual check pending.
- Skills: `Bambale0/skills` diagnosing-bugs, tdd; `Bambale0/claw` backend-integration. `anthropics/skills` inspected; no applicable backend/Telegram media skill available (webapp-testing covers browser UI, out of scope).
- Rollback: revert the task PR through protected `tanyapi`; no data migration or cleanup needed.

## 2026-11-01 — Explicit Seedance fallback edit intent follow-up
- Baseline ea704c3e2e07059d9b8aa2e775292157d28110eb, isolated task branch from current tanyapi.
- Confirmed edge: admin/trusted ordinary Auto reference is accepted by app with video_editing=false. Duration=-1 did not prove edit intent, but fallback inferred edit and changed the requested mode/ratio.
- RED: ordinary Auto video reference for fixed/adaptive ratios created a fallback receipt unexpectedly. Fix persists explicit application edit intent separately after the unchanged KIE request, and uses that flag or explicit wire edit type only.
- Acceptance: both immediate KIE rejection and accepted-primary terminal failure preserve ordinary Auto without fallback; explicit edit still maps duration=-1/adaptive/omni edit. Tests cover persistence through status reconciliation.
- Rollout: staged SEEDANCE_FALLBACK_PROVIDER=off in production env before first deployment, while current runtime remains baseline a2e3020c. Enable only after corrected code is verified and the earlier deployment is complete.

## 2026-11-01 — Seedance 2.0/2.5 Neironych fallback
- Baseline: a2e3020c5ebc403c2dc7b4ad5835a07dfb427d61 on tanyapi.
- Audit: public adapters use KIE only; Neironych exists only in admin lab. Reuse canonical authenticated callbacks, KIE Market polling, Seedance25 reconciler, watchdog, existing debit/refund/delivery.
- Contract evidence: Neironych live accepts seedance-2.0/2.5, POST /v1/videos/generations with Idempotency-Key, GET status and authenticated content. Provider source contract rejects generate_audio=false. Unsupported controls must retain primary failure rather than silently change the request.
- Seams: public adapters -> outbound HTTP boundary; durable routing -> Market status; watchdog refund guard. TDD RED public fallback tests then GREEN. No UI/API payload changes, no user billing changes.
- Plan: (1) persist routes/payload/lease; (2) explicit create rejection and confirmed terminal failure fallback; (3) shared polling and durable local content; (4) duplicate/uncertain/refund regression tests; (5) two paid API smokes, CI, auto-merge, exact-SHA production verification.
- Progress: 39 focused tests passed; direct 2.0 live smoke done, direct 2.5 pending. Full fallback live smoke starting in isolated container/DB using production credentials, with simulated KIE 402 and real Neironych calls. No user-account debit.
- Configuration: SEEDANCE_FALLBACK_PROVIDER=neironych by default when existing NEIRONYCH_API_KEY is configured. off disables new failover; existing routes continue polling. SEEDANCE_FALLBACK_CREATE_CODES controls explicit application rejection codes. Existing Neironych URL/timeouts retained.
- Schema: additive seedance_provider_routes table created idempotently using SQLite/PostgreSQL-compatible SQL. Stores exact private provider payload in existing private application DB; no prompt/URL/credentials in logs.
- Skills: Bambale0/skills tdd; Bambale0/claw backend-integration; inspected anthropics/skills webapp-testing (no frontend changes, browser suite delegated to existing CI). Skill-specific optional docs absent in this project.
- Verification: affected backend matrix 596 passed / 12 subtests; dedicated routing suite 20 passed on isolated PostgreSQL 17 (full native schema, per-test random schema, explicit runtime routing-table creation). New-file Ruff and diff whitespace passed.
- Independent review findings fixed: watchdog now recognizes terminal fail immediately; initial paid fallback is deferred until the receipt has durable active generation ownership; generation lock and route lease share refund lock ordering.
- Paid live evidence: direct API 2.0 b3ae3fd8-bcf3-41a9-a59b-8b69ff4e8ab0 and 2.5 d8ce7e14-35a1-4001-8f6a-0ddd85a3dca9 both done. Initial candidate sent KIE default controls and failed provider validation; corrected candidate forwards only canonical supported fields. Final route smokes: 2.0 abe0430f-a4a9-4e00-8d03-cc7fa76cb6f1 and 2.5 767fc82f-33db-40a7-9af3-03199646b96c both success, 814566 / 1693044 bytes, H264/AAC, 4.064s, public HTTP206 video/mp4. Fresh-process restart recovered both persisted routes and cached files without another paid submission.
- Pending: GitHub exact-head CI, auto-merge, exact-SHA production verification. Host gh token is invalid (401); use connected GitHub plugin for PR/CI operations. Git SSH origin remains available.

## 2026-11-01 — Seedance admin-test prompt and delivery recovery

- Baseline: `tanyapi@da1aed2f4e5dd9069db9da60a52f595aa856b6c0`; isolated branch `fix/seedance-admin-delivery-20261101` because the primary checkout contains unrelated in-progress work.
- User-visible result: a Seedance admin-test prompt sent as several Telegram messages is submitted in full, and one transient Neironych status error cannot silently stop automatic result delivery.
- Production evidence (read-only): the latest admin test uploaded two image references at 20:56 UTC; both media URLs were fetched through the production origin. Polling then terminated at 21:04:33 UTC on Neironych HTTP 502 before content download or Telegram send. The direct admin lab has no callback, generation-task row or durable delivery outbox; it stores the request ID in FSM state and runs an in-process polling coroutine.
- Root causes: `receive_prompt()` replaced the accumulated prompt on every message; `wait_for_result()` let a transient provider 5xx escape and permanently terminate the only automatic poller. Lost early prompt parts can also remove `@Image N` bindings even when the reference URLs remain in the provider payload.
- Safety: no paid generation, replay, balance mutation, provider route/config change or production data write. Existing request IDs remain the only safe recovery handle; never resubmit to recover delivery.
- Public seams: the Telegram FSM prompt handler and `NeironychSeedanceAdminService.wait_for_result()`. Tests use synthetic FSM messages and mocked provider responses; no provider or Telegram network call.
- Plan: (1) RED tests for multipart prompt accumulation and transient 502 recovery; (2) minimal append/byte-limit and polling-retry fix; (3) correlation-safe lifecycle logs; (4) focused and adjacent tests, lint/compile/diff review; (5) update troubleshooting guidance; (6) protected PR to `tanyapi`, exact-SHA CI/autodeploy and no-charge production verification using an existing request/manual status path when available.
- Rollback: normal revert through protected `tanyapi`; no migration or data rollback.
- Guidance: `Bambale0/skills` diagnosing-bugs and tdd; `Bambale0/claw` backend-integration, kie-seedance and release-hardening. Claw registry/index files named by those generic skills are absent in this repository; `AGENTS.md` controls. Anthropic's available skills have no applicable backend/provider lifecycle playbook.
- RED evidence: the handler test retained only the final Telegram prompt part, the status poll raised immediately on a synthetic HTTP 502, and the content download raised immediately on a local test server's first HTTP 502.
- Implementation: prompt parts append with a newline and a cumulative 40,000-byte guard; prompt/reference updates and submit are serialized per administrator; provider status 5xx/network failures retry within the existing poll deadline; content download has three bounded attempts with partial-file truncation; polling and delivery failures notify the administrator to reuse the same request ID. Correlation-safe logs record IDs, hashes, lengths, counts, terminal status and delivery method, never prompts or reference URLs.
- GREEN evidence: focused lifecycle/FSM/payload suite `53 passed, 12 subtests passed`; wider Seedance/admin set `505 passed, 19 skipped, 6 Windows-only cases deselected, 12 subtests passed`. The six deselected cases require POSIX `resource`, symlink privileges or POSIX path semantics and remain mandatory in Linux CI.
- Residual risk: accepted requests are recoverable manually from Redis-backed FSM with `Проверить`, but the direct lab still has no durable startup reconciliation/outbox. A container restart can stop automatic delivery until the administrator checks the preserved request ID. This release is scoped to the confirmed transient-status/content and multipart-prompt failures; a dedicated durable lifecycle is a separate schema/worker change, not hidden inside this minimal incident fix.

## 2026-10-31 — Creator image repeat pricing follow-up (#380)

- Baseline: `tanyapi@e2b91bfd8cbc607088c97f0db55819f59872f964`, immediately after Creator image pricing PR #379.
- Trigger: post-merge review found two P1 correctness gaps: legacy `nanobanana` selected the `banana_2` Creator rate although runtime generation routes it through Nano Banana Pro; Telegram image repeats reused historical `task.cost` instead of the authenticated actor's current Creator rate.
- RED: isolated tests-only branch produced 4 expected failures: legacy alias returned 9.0 instead of Nano Banana Pro 1.25 in the synthetic config; both repeat launch handlers never called the Creator price resolver; quick-repeat confirmation also displayed the historical price.
- Fix: `nanobanana` now normalizes to `nano-banana-pro`. Creator-supported Telegram image repeats resolve the actor tariff at confirmation/render and again at launch, use the current Creator quality rate, and preserve the historical source cost for non-Creator/unsupported legacy paths.
- Safety: no runtime `data/price.json` write, no price value invented, no membership/provider/database change, no paid generation. Production deployment must preserve the existing dirty runtime price file.
- Verification: exact-head CI and post-deploy read-only runtime verification are required before closing the follow-up.

## Creator image tariff: Nano Banana Pro / Nano Banana 2 / Seedream 5 Pro (2026-10-31)

- Baseline: `tanyapi@0ffac9c71e4a153be3867967ea67c60b38554224`; branch `feat/creator-image-models-20261031`; PR #379.
- Scope: add optional admin-managed Creator image price cells for Nano Banana Pro (`nano-banana-pro`), Nano Banana 2 (`banana_2`) and Seedream 5 Pro (`seedream_5_pro`) without changing ordinary prices, provider routing, memberships, balances or historical generation costs.
- Pricing policy: no automatic percentage discount and no hardcoded economic rates. Missing Creator image cells fall back to the current ordinary runtime image price and do not disable an already configured Creator tariff.
- Billing path: authenticated actor profile is resolved server-side immediately before Telegram/Mini App image debit and image-trend debit; client tariff fields remain ignored. Accepted image tasks retain the charged `unit_cost` in the existing task snapshot.
- UI/admin: Creator editor exposes Banana 1K/2K/4K and Seedream basic/high image cells; Telegram model picker and authenticated Mini App catalog use per-viewer prices without mutating shared model metadata.
- TDD RED on tests-only SHA `5b699e35257bb2371165c491d6f3ae3049376e5f`: lint passed; safe regression finished with 10 expected failures in `tests/test_creator_tariff_images.py` and 4206 passed / 117 skipped. Failures proved missing image resolver/config/display support and trend pricing ignoring the Creator profile.
- Regression hardening: an intermediate exact-head run exposed legacy isolated pricing contracts and monkeypatched two-argument standard resolvers. The fix keeps the standard call signature unchanged and applies the Creator overlay only after server-side actor resolution; tests were not weakened or rewritten to hide the breakage.
- Safety: no `data/price.json` write, no DB migration, no paid generation, no membership change. Production runtime price file must remain preserved by normal deployment.
- Release gates: required PR CI, review-thread audit, native squash merge to `tanyapi`, exact-SHA production deploy, container/backend/Mini App revision health, then read-only/in-memory runtime smoke for Creator image resolution.

## 2026-10-31 — PDF attachment in admin promo broadcasts

- Baseline: protected `tanyapi` at `0a84a897c20ebc591ef6c9e2229bf15086950017`. Scope is the existing persistent Telegram promo editor/test/delivery pipeline only; legacy broadcast code, pricing, providers, payments and user generation flows are out of scope.
- Goal: let an administrator attach a PDF to a promo, preview/manage it in the saved draft, deliver the identical payload through «Тест на админах», and only then allow the existing mass-launch confirmation.
- Architecture: keep Telegram as the file store and persist only its bot-scoped `file_id`, matching existing photo/video handling. Internal media type `pdf` maps to `send_document` in the immutable snapshot. No filesystem/object-store copy and no database migration are required.
- Safety contract: one PDF is a standalone attachment and cannot be mixed with photo/video media. Non-PDF documents are rejected in the admin editor. Existing photo/video albums and historical schema-v2 snapshots keep their current shape and hashes.
- Delivery contract: admin tests and audience sends reuse the same snapshot, receipt persistence, lease fencing, retry classification and uncertain-send protection. PDF edits invalidate prior test authority exactly like text/media/button edits.
- TDD evidence: new PDF editor/snapshot tests produced RED on the baseline (5 expected behavior failures; 81 existing focused tests passed). Minimal implementation then produced 86/86 promo editor/message passes and 104/104 passes including notification/promo delivery workers. Final focused/lint checks are recorded before publication.
- Config/schema/secrets: no new env vars, mutable limits, database columns, credentials or external API keys. Telegram's accepted PDF is reused by `file_id`; application code does not invent a separate upload size limit.
- Rollout: publish as a dedicated branch/PR into `tanyapi`. No production deploy or mass broadcast is authorized by this task. Required repository CI remains the release gate.

## 2026-10-24 — PR #375 review follow-up and authorized release

- Igor authorized publication and release. PR #375 targets tanyapi with native squash auto-merge; the earlier publication block is resolved.
- Review fixes: every editable model has a bounded prompt (same 30,000-character creation ceiling, Seedance 2.0 keeps 20,000); API advertises the limit to the editor. Text edits append a transactional content_edit event to existing append-only catalog history: actor, trend, before/after titles, revisions, prompt hashes and lengths; no private prompt or media URLs. Failed audit insertion rolls back the edit.
- Legacy card strips only the exact system count prefix before displaying the dedicated counter. Saving reloads an expanded category, so its cards show the new title. Reconciliation skips malformed tags and continues.
- Regression evidence: new Python tests reproduced missing limit, missing audit and malformed tags handling before fixes; follow-up tests verify audit rollback and append-only/privacy invariants. Frontend tests cover expanded category refresh and prefix normalization.
- Release gates remain required GitHub CI, exact-SHA autodeploy, production health and authenticated privacy smoke.

## 2026-10-24 — Seedance 2.5 repeat metrics and admin trend text editor

- Baseline: tanyapi 78270d4 (PR #374); production at inspection 15cbe76c; dedicated fix/trend-admin-editor-seedance-count.
- Audit: Seedance dispatcher installed after generic success wrapper, bypassing metrics. Existing category API already attaches admin-only successful counts; legacy cards lacked a dedicated counter. Preview editor has no title/prompt inputs.
- Reproduction: tests/test_trend_admin_content.py fails: metric registration awaited 0 times for Seedance dispatch; content route missing.
- Plan: (1) link dedicated dispatch with idempotent existing registry; (2) protected get/update content API with stale-editor rejection; (3) editor fields plus explicit legacy card counter; (4) auth, validation, frontend and build tests; (5) PR to tanyapi, required CI and native auto-merge.
- Preserve IDs, category assignments, references, pricing, providers, permissions and existing tasks. No schema/config changes. Only new repeats use changed prompt. Private recipes remain absent from public API. Wan/Genjutsu separate recipe editing is explicitly deferred; title editing supported.
- Logs record actor/trend/change flag only, never private prompt. Tests use synthetic data, no paid generations.
- Production reconciliation: 56 missing links restored (55 completed, 1 failed); second apply inserted 0. Older 13 records used source=trend without prompt_source_id, verified before admitting that legacy contract. Existing success query counts completed only.
- Release blocked: auto-review denied git push twice, requiring explicit user approval for source publication to this public GitHub repo despite verified Bambale0 ownership. No workaround, PR or code deploy performed. Full working copy preserved at /root/tanya-workspaces/trend-admin-editor-20261024.
- Validation: 49 focused Python tests; 48 Jest tests; Ruff, TypeScript and static production build passed. Mobile Chromium browser E2E passed in isolated server worktree: private prompt load, title/prompt save without preview, reopen persistence, viewer privacy, category navigation. Local Chromium download returned truncated archives. Production code unchanged; only idempotent statistics repair applied.

## 2026-10-23 — Kling 4 catalog placement and Telegram navigation

- Baseline: `ae8053d3b7ea27f1c94a8a3210198836d20ac9b0`, current origin/tanyapi. Isolated branch `fix/kling4-catalog-navigation-20261023`; production checkout and dirty runtime price.json preserved.
- Goal/spec: user screenshots show Kling 4 pinned above every family and a dense editor without exits. Put it inside Kling, follow other video editors, simplify labels/material controls and provide complete navigation.
- Audit: existing family/page renderer and back_main reusable; Kling4 typed recipe, per-mode drafts, quote/idempotency/admin checks and uploads already exist. Missing: editor exits, text/adopt cancellation, task/launch/error navigation; catalog navigation leaves input FSM active. Mini App already uses shared ModelSelect and separate administrator-gated form; API/provider/DB/retail billing unaffected. Runtime healthy at baseline; last 30m filtered log scan found no Kling4 errors. No prefactor required.
- Seams/acceptance: public Telegram callbacks + MemoryStorage; family placement/admin visibility, cancel input without recipe mutation, all nested screens have return/home, catalog exits release text/media FSM, deferred uploads cannot mutate abandoned editor, quote/launch semantics unchanged. Existing full Kling4 HTTP/lifecycle suite covers Mini App and provider contracts.
- No-hardcode/config/migration: reuse existing family identifiers, callbacks, administrator settings and recipe limits. UI labels/layout only; no new mutable policy, env, schema or admin settings. No paid live generation.
- Plan: (1) red catalog regression; (2) integrate Kling4 into family pagination; (3) red navigation/input regressions and minimal editor changes; (4) run focused and adjacent suites, syntax/lint; (5) review standards/spec; (6) PR to tanyapi/native squash auto-merge, exact CI and deploy verification.
- Observability/rollout: retain lifecycle task/cost/delivery telemetry; no new external operation or financial mutation. Verify exact container/frontend revision and health after autodeploy, inspect errors and run navigation smoke using isolated FSM. Rollback via revert PR.
- Progress: catalog test failed on original code (k4:open in Seedance); 11 additional input/task navigation cases also failed before implementation. Family-aware pagination and shared editor navigation now implemented. Optional materials grouped, user labels localized, parent returns and empty history guidance added. All 94 focused tests passed, including existing lifecycle/HTTP/admin/idempotency/media tests, adjacent catalog/Wan FSM/recovery/release-menu tests and 23 new navigation cases. Ruff and compileall pass. Mini App ModelSelect already classifies kling_4 under Kling; no client changes required. Spec review: 0 findings. Standards review identified one P2 queued-text/cancel race; deterministic regression reproduced it, and text-session validation under the actor lock now rejects cancelled/replaced inputs. Successful prompt/duration edits are also covered. PR #362 ready with native squash auto-merge armed; standards re-review passed (4 input/race tests independently rerun). CI exposed the release-menu test double lacking the now-used FSMContext.set_state method; extended that fake without changing assertions. Preserved pre-release text states without session tokens by comparing the field plus optional token under lock; red/green coverage includes saving legacy input and cancellation/replacement for both old/new sessions. Full local Wan contract suite: 361 passed, 13 expected skips, 18 subtests passed in a temporary dependency-complete test interpreter. Required CI is rerunning; production remains baseline until exact release verification.
- Verification layers: Telegram/domain and admin tests applicable; existing HTTP/provider/refund/idempotency regression suite applicable for preservation. No DB/schema migration or frontend edit, so no new DB/browser test required; required repository CI/E2E/build gates still apply to release.
- Playbooks: Bambale0/skills diagnosing-bugs and tdd; code-review standards/spec flow, Bambale0/claw PR checklist, anthropics/skills frontend-design (clear user vocabulary, restrained layout). Repo-authorized public seams take precedence over generic skill confirmation prompts.

## 2026-10-18 — Restore references and repair repeat launch validation

- Baseline: production branch and image `b9f6b68dd0b23d4233c021e2c35cbbc5ccea4fe9`; isolated worktree, existing PR #326. Consolidates the typed binding safety fix proposed in #325.
- Evidence: historical application log records generic cleanup removing `trend-assets` on October 11 at 22:05 UTC. Current baseline already excludes that directory, but previously deleted assets were never restored. Read-only PostgreSQL audit found 17 missing asset rows / 15 unique files across nine templates. Current run claims identify missing-media errors, not merely unexplained HTTP 400s.
- Recovery performed: matched exact SHA-256 and byte length against retained originals; restored 11 unique files atomically without replacing existing files or updating DB rows. Twelve asset rows now resolve across six templates. Hash verification and local HTTP HEAD passed for each. Four unique files/five rows across three templates remain unavailable; public cache requests returned 404. Production financial records and prices untouched. Private receipts remain in server diagnostics, not Git.
- Storage: disk initially 99% full, ~13 GiB free. Removed only unused Docker build cache older than 24 hours (16.42 GB reported reclaimed); ~28 GiB free afterward. No media, backups, volumes or running images deleted.
- Actual cleanup fix: recent-upload deletion defers physical reclamation. Full ownership query covers nested JSON image/video/audio/frame fields, all generation statuses, template settings, repeat selections and explicit asset rows. Invalid owner JSON aborts before filesystem deletion. Read-only production PostgreSQL query validated 145,565 owner URLs in 6.4 seconds. Existing orphan reclamation remains functional; no blanket no-op collector.
- Launch fix: exact user and template reference existence, plus typed Seedance bindings, checked before quote/debit/provider calls. Typed ImageN cannot become VideoN/AudioN implicitly. Stable error codes distinguish user uploads, template originals and unbound aliases. Logs contain actor/trend/stage/code, not private media URLs or prompts.
- RED: 19 new ownership regressions failed on baseline; four new HTTP quote/launch regressions failed before preflight. The prior no-op PR also failed three existing cleanup tests. GREEN: ownership and existing cleanup 27 passed; quote/trend suite 49 passed. Full safe suite, lint, CI, exact deployed SHA and post-release smoke still required.
- No schema, model routing, price, payment, referral, or UI permission changes. Old combined-ordinal prompts must use explicit typed aliases; no automatic guessing. Recovery never substitutes visually similar images.
- CI follow-up: hosted Ruff requires the Python 3.12 UTC alias; corrected the restore utility without behavior changes. Local full suite initially could not collect because the host test venv lacked the already-declared pypdf dependency; installed it into an isolated test-only target, not production.
- Rollout: tested PR to protected `tanyapi`, required strict four CI gates, normal autodeploy and exact-SHA verification. Keep the current production price/config modifications. Remaining source recovery stays explicitly tracked. The reviewed delivery fix from PR #314 is integrated: terminal link-only handling for confirmed oversized uploads, bounded retries and compare-and-swap delivery receipts; combined focused delivery/retention/trend tests passed (104). Full combined CI and production convergence remain unverified.

# Execution ledger

## 2026-10-15 — Mini App referral → ordinary Telegram bot /start

- Baseline `tanyapi`: `b1ee0ce818a88ba63402206b9233ad03907faf57`. PR #315, task branch `fix/tanyapi-bot-start-native-fallback-20261015`. This supersedes the initial incorrect PR iteration with a second UI link. Payments/provider investigations explicitly out of scope.
- Actual user goal: a first-time visitor enters Mini App via a referral `?startapp=...` deep link without having opened the text bot chat. The only primary CTA `Открыть бота` must open the same bot's **private Telegram text-chat Start screen**, not launch Mini App again or require a second fallback button. Telegram itself requires the human to press Start.
- Existing behavior and boundaries: authenticated Mini App bootstrap supplies `bot_username` from `getMe`; production `getMe` reported `Neuromixx_bot`; existing `botStartUrl()` safely preserves `ref_CODE` in `?start=...` with no payment/generation replay. Existing `common.cmd_start` invokes `mark_telegram_chat_available` and returns the normal text bot main menu; `needs_telegram_bot_start` is only true for positively known `never_started` rows. No backend fix or migration needed.
- Diagnosis/hypotheses: (1) primary CTA is a JS-only `openTelegramLink()` native bridge with no independent click-navigation, and iOS WebView may no-op without error; (2) bot username missing or malformed (not supported by production `getMe` observation); (3) `/start` handler fails (not supported by backend code and isolated regression). Telegram's vendored JS intercepts same-tab `t.me` anchors and feeds them back into `openTelegramLink`; a true `target=_blank` anchor deliberately avoids this interception. Actual iPhone device failure remains an unverified client-specific hypothesis.
- Small fix: make the **existing orange CTA** one validated `<a href=https://t.me/<bot>?start=... target=_blank rel=noopener noreferrer>`, no JS-only native open, no extra CTA. Keep optional Skip, return-to-app capability refresh, refs/drafts and both Mini App/photo/video flows. Invalid usernames render a disabled action; no untrusted URL navigation. No prices, credentials, invoices, payment webhooks, DB schema, provider or production runtime touched.
- Test-first evidence: new frontend text-chat-link regression failed on original PR state (primary action remained `button` and an unwanted secondary link). Fixed regression: 25/25 focused Jest; changed-file ESLint clean; static `npm run build` and TypeScript pass. Isolated backend: 33/33 `tests/test_bot_start_eligibility.py` including new first-time Mini App visitor → `/start miniapp_delivery` → private-chat availability and normal menu. Chromium browser E2E: 320/375/390/430px PASS, including real click popup URL, no native bridge, attribution, optional Skip, retained form/ref and capability return checks. WebKit iOS-like E2E was attempted but could not launch because the production host lacks the required GTK/GStreamer/AVIF libraries (no host package changes). Current-head GitHub CI and a human iPhone Telegram acceptance check remain release gates.
- Review/rollout: one small PR to protected `tanyapi`; request review and enable native squash auto-merge only after tests and no high-severity findings. Confirm exact backend/frontend deployed hashes, health, public static checksum and mock-only production smoke after merge. Real Telegram iOS on-device acceptance remains separate and must not be claimed from Playwright emulation. Rollback through PR revert if Telegram client behavior regresses.

## 2026-10-14 — iOS Telegram Mini App cannot copy Feed share URL

- Baseline `tanyapi`: `a1b1ce4ae6f8c6b52cea06c7527fa61c645339c5`. Branch: `fix/tanyapi-ios-feed-share-copy-20261014`.
- Symptom (user screenshot, iOS Telegram): Feed produced a valid exact `startapp=remix_…_ref_…` URL but copy recovery kept showing `Автоматическое копирование недоступно` after retry. Link generation, signature and ownership are separate and unchanged.
- Root cause: initial copy awaited `feed/share`, losing clipboard transient user activation; retry tried asynchronous `navigator.clipboard.writeText` first, and after rejection attempted `execCommand` too late and on an element positioned at -9999px (fragile in iOS WKWebView).
- Fix: preserve server URL byte-for-byte. On iOS wait for an explicit copy tap after resolving the share link; the shared clipboard helper immediately selects the already visible readonly input and calls synchronous legacy copy while user activation is alive, before trying standard Clipboard API. For other browsers retain existing automatic copy and fallback.
- Add a user-activated `https://t.me/share/url?url=<encoded exact URL>` link, using existing Telegram native opener with normal secure anchor fallback. Do not navigate automatically or send data without a click. Unsafe URLs do not render share/navigation links. Retain manual selection when all clipboard methods reject.
- Tests: add helper Jest regression for iOS selection, deny and empty link; feed DOM tests for click-time selection, exact referral URL and native share; mobile Chromium/WebKit E2E mocking clipboard denial and native copy, no live Telegram sessions. E2E and CI must pass before squash auto-merge. No DB, pricing, refs, payments, provider, env or production file change.
- Release gate: dedicated PR into `tanyapi`, required green CI, squash auto-merge, verified production SHA, static Mini App and health smoke; preserve concurrent draft PR #305.


## 2026-10-14 — All-model additive video-reference pricing, no presence ×2

- Baseline: `tanyapi` and prod `a1b1ce4ae6f8c6b52cea06c7527fa61c645339c5`. PR #305 `fix/tanyapi-all-video-reference-seconds-no-multiplier-20261014` (draft until CI verified).
- Supersedes incorrect output-only WAN PR #304, which was closed without merge. Clarified retail requirement: for all supported video models, **configured rate × (measured input video seconds summed over attached video references + selected output seconds)**; do not add another presence-based ×2.
- Audit: WAN 3/Prime, Motion and Genjutsu already used input plus generated video accounting; Seedance 2/2.5 and generic quote/UI used an incorrect ×2 if any video reference. Multiple references were indistinguishable. Mini App ordinary and Seedance public UIs displayed doubled prices and lacked precise quote confirmation.
- New accounting: bounded server-owned ffprobe of locally retained source video, independently measured and summed, fail-closed on unresolvable/expired URLs; source duration never inferred from count or guessed. Shared `quote_video_for_actor` and `resolve_video_quote` apply rate once with existing rounding; actor tariff/admin-free retained. No new provider parameter or upstream rate change.
- Mini App: new quote-only authenticated mode on the existing generation API validates the same recipe/media as launch; returns source/output/billable seconds, cost and quote hash, and requires current price acknowledgement before debit. Generic Studio uses two-click quote/launch. Separate Seedance 2.5 public screen uses its existing quote endpoint for all source-bearing generations and preserves its identity quote gate. All old clients submitting paid video refs without a confirmed quote get a safe stale-quote response.
- Feed and repeat: remove presence multiplier in descriptors and creator metadata; prompt-repeat and trend cards with unresolved video references show no invented final price. Normalized repeat references resolve on the backend before charging. Telegram keyboard displays base per-second rate while real quote counts source seconds.
- Risk policy: no migration of historic tasks or direct balance adjustment; previous reserves/refunds remain frozen. No production config/price writes, paid video generations or provider payload changes. Preserve dirty production `data/price.json`.
- Verification: RED production read-only test confirmed old Seedance 2 quote 20→40 for a single video despite unknown length. Added deterministic pure and actor tests for 5s generated + 7s refs at 4/s = 48 and 5s + 13s at 4/s = 72; full project CI and browser E2E required before marking ready. `Bambale0/skills` diagnosing-bugs, TDD/code-review, `Bambale0/claw` backend integration and Anthropic webapp-testing consulted.
- Release: required CI checks → ready-for-review/native auto-merge to protected `tanyapi` → exact prod SHA backend health and Mini App revision verification; **not yet deployed**.


## 2026-10-10 — Higgsfield Genjutsu reference + generation seconds billing

- Baseline: `tanyapi` `fb499599112c630e43ebb0c5b87c66d5b409c075`. Task branch: `fix/tanyapi-genjutsu-reference-plus-generation-seconds`. Draft PR #290.
- Goal: bill selected video-reference seconds plus generated-video seconds, using the existing configured per-operation/per-resolution rate. Quote breakdown and atomic actual debit must agree, including private trend repeats.
- Current audit: `contract.quote_plan` billed only source duration; `repository.begin_submission` also used only source duration. The user-facing Genjutsu editor has source clip trimming, but the provider input contract does **not** have an independent generation duration control. Generation seconds currently equal selected effective source-clip seconds. Distinct durations can be calculated by the pure duration helper, but a separate UI duration selector would be fake and was not added.
- Options considered: frontend-only doubling (rejected: billing mismatch), fake output-duration parameter (rejected: provider schema invalid), shared double-component backend accounting (selected). Supplier pricing is by input video only; this is an explicitly requested NEUROMIX customer tariff change.
- Change: shared millisecond-to-seconds function rounds each component up independently; reserve/actual charge both use the sum; quote exposes `reference_seconds`, `generation_seconds` and `billable_seconds`. A pricing version gate invalidates outstanding unused old quotes, but preserves accepted/in-flight tasks and refund accounting.
- Scope: `bot/genjutsu/contract.py`, `bot/genjutsu/repository.py`, Mini App quote types and both Studio/Trend quote views, focused backend/frontend regression tests and Genjutsu docs. Existing admin prices, DB schema, model payload, provider routing and env unchanged.
- Critical invariants: prior quote cannot be started under new pricing, atomic balance reservation remains idempotent, failed/unexecuted steps refund correctly, multi-step/variant max reserves include both duration components, and no duration is invented when metadata is missing.
- Test-first: contract, repository, and browser-visible component regression tests were committed before implementation. CI/test outcome to be verified from the final PR head; no paid generation or production runtime validation has been performed.
- Rollout: exact-head Python and Mini App CI/E2E, independent review, squash auto-merge to `tanyapi`, exact-deploy-SHA plus focused quote/charge smoke. Rollback through revert; check pre-change unused quotes and no balance migration. Live verification remains outstanding.
- Playbooks consulted: `Bambale0/skills` diagnosing-bugs, tdd, implement; `Bambale0/claw` backend-integration and release-hardening; `anthropics/skills` webapp-testing.


## 2026-10-09 — Seedance 2 ordinary price editor/quote alignment

- Baseline: fresh `tanyapi` `d766b0eeb6693de1ea84f79734efc66a3ad93789`. Isolated task branch `fix/seedance2-ordinary-quality-price-20261009`; source blobs verified against the remote tree. No unrelated referral changes are included.
- Confirmed root cause: the ordinary admin editor saves `quality_costs`, but normal Seedance 2 calls omit pricing quality while sending 720p to the provider. Quotes consequently preferred historical duration prices over the configured 720p rate.
- Fix: normalize an omitted Seedance 2 quote quality to actual provider 720p in the shared immutable quote service. Existing explicit quality, legacy fallback when the rate is absent, creator/admin precedence, reference multiplier, accepted task quote and refund contracts remain intact.
- No price file, migration, credential, membership, live generation or provider capability change. The already configured ordinary rate of 5 credits/second now produces 25/50/75 for 5/10/15 seconds instead of stale duration totals 20/40/60. Creator rate values are preserved. These are consequences of honoring saved rates, not a price migration.
- Playbooks: Bambale0/skills diagnosing-bugs and tdd, Bambale0/claw safe incremental engineering, anthropics/skills webapp-testing. Public seams: Telegram admin save, shared quote, Mini App/Telegram launch and refund, repeat/trend metadata, authenticated bootstrap and visible client refresh.
- RED: ordinary quote/admin-save/metadata suite had 9 failures and 8 passes; public launch suite had 6 failures, reproducing 20 instead of 25 and the missing frozen 720p resolution. Synthetic data, SQLite and mocked providers only.
- GREEN: 20 ordinary editor/quote regressions; 53 new public-surface tests; independent review reran 90 focused cases and approved the application fix. Existing creator coverage passed (168 passed / 15 skipped). Full frontend: 44 suites / 326 tests; ESLint, TypeScript and production static export passed. Ruff on all three changed Python files and diff whitespace checks passed. Repository price file SHA256 was identical before/after.
- Broad local backend: 2747 passed / 1 skipped / 12 subtests passed; one unrelated asset-presence test failed because this safe source materialization omits the unchanged bundled public-offer PDF/text. PostgreSQL/pool-dependent files and live provider tests were deliberately excluded. No application failure occurred in the executed pricing or payment suites. Required full remote CI remains the final release gate.
- Local browser E2E could not launch installed Chromium because the execution sandbox disallows its process socket, including the approved escalation attempt. The two new React tests verify visible focus and five-second price refresh; browser E2E must be verified by the required GitHub gate. No workaround around the sandbox restriction was used.
- Review documentation clarification applied: editing/enabling the creator overlay preserves ordinary rates, while this ordinary quote correction honors the already configured rate. Publication, exact-head CI and release are coordinated with the parent; no independent merge or deployment.

## 2026-10-07 — Resume optional bot Start offer

- Latest instruction resumes the optional offer only for explicit never-started users. Current integration baseline is tanyapi ac9365d96459a3932c4a934600cc071a2ccec63b, including durable gate removal, Seedance identity and promo fixes. The historical emergency removal below is preserved as a completed release record.
- Added lifecycle marker in the existing text state (no schema migration), bootstrap contract and mock-only regression coverage. New/unknown/blocked states remain distinct.
- Resumed backend tests: 32 focused passed, including delivery-proof bookkeeping failure isolation. On the integrated baseline: 2079 backend passed / 66 skipped (live, credential and PostgreSQL-pool checks excluded locally); 243 frontend tests / 36 suites, TypeScript, lint, export build and changed-line Ruff passed. Four-width (320/375/390/430) offline Start/Skip tests and eight media-target flows passed; screenshots inspected at 320/430. Existing critical E2E and final combined review remain pending. Release coordination belongs to the combined release owner; no independent production writes.

## 2026-10-06 — Direct bot Start gate, bounded return verification

- Baseline: tanyapi `b7c71a51727d4d5953536a50b9c0c2d15ef3dee6`; isolated branch `fix/bot-start-gate`.
- User outcome (clarified 16:28 UTC): bot delivery is OPTIONAL. Primary button opens bot Start directly, with «Пропустить» to use generation/Studio immediately. Session-only dismissal survives tab/refresh without pretending delivery permission exists; a nonblocking re-entry offer remains. Return verification is bounded and server-confirmed.
- Audit: old native callback and fetch have no deadlines; pending UI hides fallback. cmd_start marks chat available before routing. Existing refreshTasks unmounts forms via global loader, so return verification must update only the confirmed capability without loading/navigation reset.
- Scope: frontend gate/API/context and mock-only regression/E2E. No database/schema/config/payment/provider changes, no real bot messages, generations or production writes.
- Plan: RED regression → direct Start action → abortable capability refresh → timeout/cancel/return tests → 4-width mock browser coverage → lint/types/build/full tests → review → draft PR; release requires separate authorization.
- Skills: Bambale0/skills diagnosing-bugs and tdd; Bambale0/claw evidence-first workflow; anthropics/skills webapp-testing. Test seams: gate interaction, bootstrap capability update, mocked browser return journey.
- Progress: original never-callback regression reproduced RED; direct Start and abortable capability-only checks implemented. Prior-bootstrap capability revision guard prevents stale reopening; activated no longer resets a live form.
- Verification: TypeScript, lint, full frontend 34 suites / 214 tests and production export build passed. New offline browser suite passed twice at 320/375/390/430px with real 12s timeout, denial/error/cancel/return/reappearance and form/reference preservation. 320/430 screenshots visually checked: no clipping or overlap. Independent read-only review found no remaining blocker. Existing full critical E2E passed (132.7s, exit 0) with its prior forced-tab-reset assertion updated to the new preservation contract.
- Config/schema/provider/payment changes: none. No real Telegram permission request, message, generation or payment executed. Legacy native endpoint remains for older clients; new UI never calls it.
- Latest optional-flow verification: focused 27 tests and full frontend 34 suites / 216 tests, TypeScript, lint and production build passed. Independent optional-UI/backend review found no blocker. Backend generation admission and Studio retrieval remain independent of delivery capability; result retention precedes message guards. Final optional-generation mobile E2E passed all 320/375/390/430px (84.76s): Skip persists through return/tab/refresh/reload, mock image+video generation succeeds with delivery=false and zero bot calls, draft/reference DOM survives dismissal, pending checks cancel, and offer can reopen. Optional modal/banner screenshots reviewed at 320px. Final existing critical E2E rerun also passed on the optional export (132.79s).
- CI recovery: PR #262 browser workflow identified high-severity sharp/librsvg advisory GHSA-wq5f-xc86-pv6w. Raised only sharp and its platform binaries/libvips from 0.35.4 to 0.35.5 (libvips package 1.3.4) via registry.npmjs.org; Next dedupes to the same version. npm audit --audit-level=high now passes; remaining moderate dev-tool findings were not force-downgraded. Full 216 tests, lint and production build re-passed. Security gate unchanged.
- Target-link release review: 7 browser paths preserved exact media IDs/URL/DOM, but photo trend deep links exposed competing modal pointer/focus trapping. Deferred the optional delivery offer while trendToRun owns the active Radix modal; trend generation stays available and offer returns after closing the trend. No Radix protections bypassed. Committed offline media-target regression reproduced RED on original export and passed GREEN on fresh export: 8 prompt/feed/remix/profile/trend target flows in 16.7s, with exact ID/URL/DOM retention. Trend close exposes a clickable optional offer; same trend reopens after Start and Skip. Final 216 tests/types/lint/build passed; independent source review passed.
- Latest direction 18:01 UTC: user requested the completed OPTIONAL offer now. Temporary no-gate static hotfix remains live until this verified release; removal-only PR #263 is held draft. Resume PR #262 with the trend-modal deferral and media-target regression, without force-push or restoring the defective original gate.
- Latest audience constraint 18:34 UTC: offer only for known-never-opened/no-private-chat users. Frontend now requires explicit telegram_bot_start_required=true, with missing/false defaulting hidden independently of delivery availability; both values are protected against stale bootstrap responses. New lifecycle state never_started is initialized only on new Mini App users and retired monotonically by private contact/proof; legacy/blocked/unknown states are not classified as new. Backend lifecycle tests and privacy-safe mocked browser coverage are in progress.
- Remaining: exact PR CI, authorized production rollout and read-only SHA/health/static smoke verification.
- Rollback: revert this PR; no schema migration. Old Telegram clients may close the WebView when opening Telegram links; this fix preserves live-session forms, not arbitrary reload persistence.

## 2026-10-06 — Emergency removal of bot write-access UI

- User explicitly requested immediate server hotfix removing the permission window entirely; supersedes optional Start/Skip proposal in unmerged draft PR #262.
- Baseline production/backend: b7c71a51727d4d5953536a50b9c0c2d15ef3dee6. Removed only BotWriteAccessGate import/render and its unused refreshTasks binding from MiniAppShell. No replacement banner; no auth, payment, generation, ownership, database or Telegram-delivery logic changed.
- Backed up exact served static tree, shell source and unchanged nginx config at 17:37:22 UTC before mutation. Focused shell lint and production build/typecheck passed.
- Published static export to the verified Nginx root at 17:38 UTC, keeping old hashed chunks for in-flight WebViews. Served HTTP 200 and public HTML checksum matched new build (asset version 20261006173756).
- Live production-static browser smoke at 390px used fully mocked APIs with telegram_chat_available=false: no permission window/banner, Photo editable, Video accessible, zero real API calls or generations. Backend remained running/healthy with unchanged StartedAt 14:37:52 UTC.
- Existing already-open WebViews need close/reopen to load the new entrypoint. Retained backup permits a static rollback; no backend restart or nginx changes performed.
- Durable follow-up keeps the narrow gate removal plus sharp 0.35.5/librsvg security patch required by CI. Existing browser critical flows now run with telegram_chat_available=false and explicitly assert the permission UI is absent. No optional-banner/Start-gate changes from PR #262 are included.
- This source commit keeps future deployments from restoring the removed window. PR #262 remains draft/unmerged and must not be released as-is.


## 2026-10-06 — Combined video preview and Seedance reference release

- Baseline: fresh `origin/tanyapi` at `3fd259c4704ae13593018b90da4b8b0a40bb8ab9`; integration branch `fix/video-preview-trend-references`. Both reviewed task patches were applied to a separate clean checkout; only the append-only execution ledger overlapped and both task records were preserved.
- Authorized release scope: publish one PR for the two requested changes, require exact-head checks, merge to tanyapi and verify the normal CI/CD deployment. No unrelated production writes, paid generation, refunds, customer deliveries, credential changes or security changes.
- Integration change: include the new Seedance upload mobile fixture in the existing critical-flows browser gate, alongside Genjutsu preview and private-repeat permission journeys. All browser calls use synthetic fixtures; all backend tests use the repository safe suite with project environment loading disabled.
- No migration, dependency/lockfile, provider, balance or admin authorization changes. Upload limits remain model/config-derived. New upload publication deduplication remains process-local; cross-worker exactly-once behavior is not claimed.
- Component verification before integration: Higgsfield backend 1757 passed/19 skipped, 31 frontend suites/172 tests, full critical browser aggregate passed; Seedance backend 1791 passed/19 skipped, 32 frontend suites/170 tests, mobile 320/360/390/430px and independent review passed.
- Combined verification: final safe backend **1845 passed / 19 skipped**; frontend **33 suites / 192 tests**, full ESLint, TypeScript and production static export passed. Full critical browser aggregate passed including private-repeat consent, new/legacy Genjutsu links and Seedance upload at mobile widths. Deployment shell syntax and changed-line Ruff passed. PostgreSQL-specific tests remain for remote CI. Independent integration review approved both changes and the Seedance2 validation fix; the last optional frontend delta re-read was cancelled, so its verification is the author-run red/green/full suite, not a second independent sign-off. Exact-head remote CI and deployed revisions remain release gates.
- Final review fixes: reuse Seedance2 canonical limits (2–15 seconds per included video, at most 15 seconds combined, 50 MB) at publication and on assembled fixed/replacement inputs before debit; use the existing chunked Seedance2.5 video uploader; clear stale link errors after navigation. Exact user-supplied remix/feed start-parameter patterns are covered with synthetic Genjutsu cards; live metadata of those two publications was not verified because the optional read was cancelled.
- Cleanup: preserve reviewed source patches, logs and screenshots; after release validation, stop only task-owned test processes and move generated task dependencies/caches to a recoverable task archive. Never touch unrelated worktrees or runtime data.


## 2026-10-06 — Shared Higgsfield links preview before repeat

- Baseline: `tanyapi` `3fd259c4704ae13593018b90da4b8b0a40bb8ab9`; isolated `fix/higgsfield-preview-links` clone. No production checkout, credentials or live data used. Initial implementation phase stopped before publication; the combined release phase is authorized separately above.
- User-visible result: new Telegram links and already-issued published Genjutsu recipe links open the existing Feed/Profile video player first. Only its explicit Repeat button opens the unchanged own-reference recipe form.
- Preflight: ordinary video `feed_*` sharing already previewed correctly. Telegram Genjutsu buttons and legacy recipe URL/start parameters bypassed preview. Existing Feed/Profile card hydration and private recipe admission can be reused; no schema/config/admin/pricing/provider change is needed.
- API: authenticated read-only `recipe_preview` resolves publication binding to canonical privacy-filtered card for the viewer, checks active recipe and availability, and rechecks withdrawal after resolution. No private plan, source IDs, signed media or original references enter the response. Active unbound curated recipe returns explicit null to preserve its existing editor contract; malformed/withdrawn/deleted/archived bound publications never use that fallback.
- UI: AppProvider owns incoming published recipe navigation. GenjutsuEntry remains responsible for explicit studio events and owner/admin entry. Old generic remix links for Genjutsu also preview rather than selecting a different model. Standard author referral suffix is preserved on new Telegram links. Server referral handling, repeat admission and billing remain unchanged.
- Navigation: stale async results are fenced after user navigation or a newer history location. Close/repeat handoff is consumed once; Back/Forward uses current location rather than immutable Telegram launch snapshots. An empty Telegram SDK hash cleanup is not treated as new navigation.
- Test seams: authenticated HTTP/API, Telegram callback/keyboard, real AppProvider routing, existing Feed/Profile UI, static-export browser with synthetic media and denied external/provider requests. No paid generation, real publication/upload/delivery or refund tests.
- Skills: current Bambale0/skills tdd + diagnosing-bugs public-seam red/green; Bambale0/claw frontend-qa/backend-python guidance; anthropics/skills webapp-testing. Repository-specific safety instructions take precedence over generic skill steps. Repository `.agents/skills` is absent.
- Verified so far: backend focused 67 tests; final safe backend 1757 passed/19 skipped (PostgreSQL-specific coverage not run); changed Python compile and changed-line Ruff clean. Frontend 31 Jest suites/172 tests, full ESLint, TypeScript and production static export passed. No new dependency or lockfile edits.
- [x] Reproduce links and navigation races with RED tests; [x] implement resolver and preview routing; [x] unit/integration/static checks; [x] final mobile link journey (320/360/390/430px); [x] independent review; [x] preserve source patch and verification artifacts; [ ] reversibly tidy own generated files after remaining validation decision.
- Final mobile evidence: five new/legacy link variants and unavailable-state checks passed on 320/360/390/430px; 360px Back/Forward and delayed quote dismissal passed. Screenshot inspected. Review fixes cover Telegram reactivation, Entry-owned lazy/busy recipe dismissal, visible error UI, and owner/admin card capability parity. The final fixture hardening (activation waits for resolver request; video readyState) passed in the full critical aggregate after preparing the documented static export mount. Earlier cancelled calls did not run tests.
- Release follow-up: publish a draft combined PR against tanyapi under the authorized release phase and run exact-head required CI, including PostgreSQL. No production verification or monitoring is part of this task.


## 2026-10-06 — Mini App write-access gate for referral/deep-link users

- Baseline: `origin/tanyapi` / production `bc588f9d8060c396d3f8b26350345e673e4ee000`; branch `feat/miniapp-write-access-gate`.
- Problem: a user can open a photo/video flow directly from a Mini App/referral deep link without ever starting the bot chat. The generation completes and remains visible in Studio, but Telegram cannot deliver the result because the user has not granted write access (`telegram_chat_state=unavailable`).
- Product fix: bootstrap now exposes `telegram_chat_available`. Live Mini App screens show a blocking, screenshot-matched write-access modal whenever delivery is unavailable, before the user can continue generating.
- Consent path: the primary button invokes Telegram `requestWriteAccess()` from the required user gesture. On native grant, `/mini-app/api/write-access` records chat availability and sends one confirmation message as a best-effort proof that delivery is possible. If Telegram reports a terminal `chat not found`/blocked state, availability is rolled back and the UI falls back to `https://t.me/<bot>?start=miniapp_delivery`.
- Direct-link compatibility: Telegram clients where native write-access is unavailable/unsupported immediately fall back to opening the bot chat. Returning from the bot triggers a bootstrap refresh; `/start` already marks the chat available, so the gate disappears automatically.
- Scope: applies to every Mini App photo/video path, not only one referral type. Existing bot users are unaffected; missing bootstrap field defaults open during rolling deploys.
- TDD RED: frontend test initially failed because the gate component did not exist; backend tests failed because no write-access endpoint/state transition existed. GREEN: 3 backend consent/fallback tests, 3 frontend modal tests; focused Mini App/delivery/database matrix **101 passed**; full Mini App **30 suites / 154 tests passed**; TypeScript, ESLint and production export build pass; full backend **1723 passed / 19 skipped**.
- Safety/reliability: user consent is explicit; no permission bypass. Terminal Telegram send errors restore `unavailable`; transient confirmation failures do not revoke granted consent. The existing owed-result delivery recovery remains the final authority for real sends. Changed-line Ruff reports **0 relevant diagnostics** and `git diff --check` passes.
- TODO: [x] reproduce/root cause; [x] TDD; [x] backend capability + consent endpoint; [x] blocking Mini App gate + fallback; [x] focused/frontend verification; [x] final full backend suite; [x] changed-line review; [ ] PR/CI/merge/deploy; [ ] production smoke with a fresh direct Mini App user.

## 2026-10-06 — Full generation delivery audit: Seedance + images + video

- Baseline: `origin/tanyapi` / production `58bce7f968ef03aea71655b81c3517a2b5ca5dd3`; branch `fix/generation-delivery-audit`.
- Scope: every `generation_tasks` model used in the last 24h plus Genjutsu delivery, Telegram reachability, Seedance reference semantics, result durability, pending/stuck jobs and refund markers.
- Production facts: no task older than 15 minutes remains `pending`/`processing`. Seedance 2.0 has 38 completed / 1 failed; Seedance 2.5 has 85 completed in the current rolling window. Completed tasks consistently have result URLs. Seedance 2.0 runtime is reference-only: uploaded photos are normalized into reference images and the service defensively clears first-frame semantics before the provider request.
- Delivery root cause: completed results marked `delivery_status=unavailable` are skipped solely from persisted `users.telegram_chat_state=unavailable`. A read-only live Bot API `get_chat` audit proved many of those chats are currently reachable private chats, including missed Seedance 2/2.5 and image results. The state was only reset on `/start`, so stale `unavailable` became a permanent result-delivery gate.
- Delivery fix: `can_attempt_telegram_delivery` accepts an optional live probe. Owed result paths revalidate stale unavailable chats using the active bot; successful probes mark the chat available. Confirmed terminal Telegram errors remain blocked; transient probe errors do not suppress the owed result and the real send remains authoritative. Nonessential generation-start/failure notices retain the old no-probe behavior.
- Durability root cause: dedicated Seedance 2.5 success handling bypassed generic `_persist_result_url_if_needed`; 556 historical completed rows still point at `tempfile.aiquickdraw.com`, including 76 in the current last-24h window. Generic Seedance 2 and normal image/video results are already predominantly stored on `tanyapi.chillcreative.ru`.
- Durability fix: known ephemeral Seedance 2.5 result URLs are localized with `persist_feed_result_urls(require_local=True)` before the row can transition to completed. If durable persistence fails, the task remains retryable instead of committing a short-lived provider URL.
- Refund audit: provider/watchdog failures normally carry `refund_state=refunded`. Ten image tasks in the current window are immediate pre-queue launch failures without the async refund marker; their synchronous caller path credits the same unit cost back immediately. No stale provider tasks were found.
- TDD RED: stale unavailable chat rejected a live revalidation probe; Seedance 2.5 stored `tempfile.aiquickdraw.com` directly; durable-persist failure incorrectly completed the task. GREEN after narrow fixes. End-to-end KIE regression confirms an unavailable Mini App user with a reachable Telegram chat is revalidated and receives the result.
- Verification: focused delivery/Seedance/database matrix **186 passed / 10 skipped**; added KIE revalidation regression passes; changed-line Ruff **0 relevant diagnostics**; `git diff --check` passes. First full-suite run found one compatibility assertion (`probe=None`); fixed without changing behavior. Final full suite is **1720 passed / 19 skipped**.
- Review: no broad provider routing, pricing, payload shape, model defaults or failure/refund semantics changed. Live probing is limited to successful owed-result paths; generation-start and failure notifications keep the old skip behavior. Seedance 2.0 reference-only contract is untouched. Seedance 2.5 durability runs before completion, so an ephemeral-download failure remains retryable and cannot convert into a false completed result.
- TODO: [x] production DB/log/reachability audit; [x] root causes; [x] RED regressions; [x] delivery/durability fixes; [x] final full suite; [x] final review; [ ] PR/CI/merge/deploy; [ ] backfill still-live Seedance 2.5 temp results; [ ] requeue reachable users' missed completed results; [ ] exact deployed SHA + production smoke/telemetry.

## 2026-10-06 — Genjutsu provider moderation false-positive handling

- Baseline: production/origin `tanyapi` `3d7e959ef6fa2a1133ec16611e70086a29ecb213`; branch `fix/genjutsu-moderation-labels`.
- Repro: run `8fed8d02bfdf4b2bbe0be1b9d1ce8572`, step `1e86a1d2060d433d8ecdb2d571649114`, provider request `06c6f2cf-3ded-4ac3-a063-be92ba3c81b2`.
- Evidence: the live provider status endpoint returned HTTP 200 with terminal `status=nsfw` and the broader message `content safety restrictions`. The saved source and reference media were inspected and appear benign, so Tanya did not invent the terminal status and this case is consistent with an upstream false-positive. The provider does not expose the exact classifier rule.
- Billing: the reported run is an admin-free test with zero reserve. Sampled paid Genjutsu moderation failures all had full reserve refunds.
- Root product bug: user history exposed raw internal `provider_nsfw`, while the provider adapter discarded the provider reason and durable status events recorded only a correlation ID.
- Fix: retain the internal code for accounting/audit compatibility, show users `Модерация провайдера` with false-positive guidance instead of the raw code, and persist only a normalized provider reason category plus terminal provider status in event details. Raw provider text is deliberately not stored because it may contain signed URLs or user content. Identical safety-blocked requests are not auto-retried.
- TDD: provider reason regression RED when the reason was discarded; frontend regression RED on raw `provider_nsfw`; privacy regression RED when a provider URL would have survived. All are GREEN after the narrow fix.
- Verification: focused Genjutsu backend **162 passed**; Mini App **29 suites / 151 tests passed**; TypeScript, changed frontend ESLint and production build pass; full backend **1714 passed / 19 skipped**. Changed-line Ruff has **0 relevant diagnostics** and `git diff --check` passes.
- Review: the internal moderation code remains stable for accounting/notifications; user history no longer treats it as a factual content label; admin diagnostics keep the raw internal code. Provider response text is not persisted, only a safe normalized reason category. No automatic retry or moderation bypass was introduced.
- TODO: [x] live provider/status/media diagnosis; [x] billing/refund audit; [x] RED regressions; [x] narrow provider/event/UI fix; [x] focused/full local verification; [x] changed-line lint/review; [ ] PR/CI/merge; [ ] exact deployed SHA + production smoke/log verification.

## 2026-10-05 — Actual video duration and reliable terminal notices

- Baseline: `tanyapi` `f70f84738981f145c630265664e87913437a1bb9`; isolated branch `fix/genjutsu-actual-video-range`.
- User contract: default range is the complete server-probed video (0 to actual duration); optional start/end controls remain visible inline. A video outside catalog limits requires an explicit valid range, never a silent five-second or maximum-duration crop.
- Diagnosis: the previous five-second value belonged only to the optional trim form; ordinary quotes already used the source asset's actual duration. Read-only accounting investigation did not demonstrate a five-second charged output; preserve existing financial semantics.
- UI: use canonical metadata for editor, upload/import/library/restore and user-source recipes. Full valid sources quote directly without a trim call. Editing a range invalidates quote/ack and requires applying that explicit range before another quote. Prepared media resets to its own actual duration, including encoder tolerance.
- Quote safety: input revision guards reject late quote/trim responses after newer edits; source changes clear old ranges. Display actual duration plus authoritative per-step billed seconds and price. User-source recipes do not show their template price as the current user quote.
- RED/GREEN: 18 initial UI regressions failed on baseline; new and existing component tests passed after implementation. Added millisecond precision, missing metadata, stale responses, source restoration/reselection and encoder-duration boundary regressions. Independent helper sweep passed all 26001 valid integer-millisecond durations from 4 to 30 seconds.
- Frontend verification: 27 suites / 128 tests, TypeScript, changed ESLint and production build passed. Chromium browser flows at 320/360/390/430px cover both editor and recipe: a synthetic 10.056s source quotes 11 billed seconds, manual 5s trim requotes 5 billed seconds, and stale launch controls disappear. Screenshots visually verified.
- Terminal notification diagnosis: old delivery outbox was success-only, so failed/canceled outcomes had no bot notification path. New additive run-terminal outbox snapshots safe reason categories and finance-ledger totals within settlement; only future terminal transitions enqueue. No historical backfill, real test sends, refunds, requeues or paid generation calls.
- Notification verification: the full safe Python suite passed with 1678 tests and 18 skips; changed Python Ruff and 96 final notification/API regressions passed. Independent review confirmed transactional settlement/outbox insertion, serialized claims, lease fencing, bounded explicit-rate-limit retries, no replay after unknown delivery, and no historical enqueue. Existing accounting mutations remain unchanged. Eleven bounded, validated notification templates are editable through versioned admin settings; only settled refund/charge placeholders are allowed.
- Saved sources and diagnostics: ordinary owned project reads now return minimal source metadata even beyond the latest 100 uploads, after the existing ownership/private-recipe guards. Missing/foreign/non-video sources return no metadata. Editor refresh retains the active source; repeat/edit-result hydrate after prior draft save to prevent async refresh loss. Missing metadata explicitly blocks calculation. Calculation errors now have safe actionable copy and production-visible action/code/status/type logs, without request bodies, owner IDs, prompts, media or exception text. The original 16:32 HTTP 400 cannot be retrospectively attributed from the old logs.
- Final review: independent UI and backend review found no remaining correctness blocker. Added old-source restore/refresh, missing source, repeat and delayed refresh/save regressions; all 136 frontend tests passed. Final TypeScript, changed ESLint, clean production build and critical browser E2E passed. The clean build removed stale local webpack-cache reuse; final served bundle and screenshots were reverified, including full-range editor/trend at 320/360/390/430px and expanded notification settings at 320px. Dedicated PostgreSQL and exact-head release CI remain required. No live generation or real-message test is performed.
- Runtime access: public admission was initially disabled at the user's request. The user explicitly requested restoration on 2026-10-05 at 16:22 UTC before the follow-up UX release. At 16:28 UTC the configured production service independently confirmed `public_enabled=true`, `admin_enabled=true`, settings version 7, all nine verified operation/resolution pairs, ordinary creation allowed and a visible public module. Preserve this latest authorized runtime state during rollout.
- Rollout: separate logical UI/notification commits, independent review, full safe tests/schema parity and exact-head CI, then normal exact-SHA deployment and health/flag checks. No unrelated projects or branch security settings are changed.


## 2026-10-05 — Keep archived Genjutsu recipes private

- Baseline: merged `tanyapi` `4c316a1e9de479a69b66103c4ba65a6a537e708e`; isolated branch `fix/genjutsu-archived-recipe-privacy`. Existing mobile-release worktree is untouched.
- Preflight: PR #249 adds caller-owned video sources to private recipes. The previous resolver filtered out inactive recipes and treated the saved recipe project as an ordinary project. With all media caller-owned, an archived recipe could be requoted with `private_recipe=0`, exposing its private plan through the normal run response.
- Safe reproduction: fake users, fake assets, isolated SQLite and no provider calls. The user-video case returned the synthetic private prompt after archive; fixed-source control rejected the asset.
- Scope: retain recipe-project bindings and fail closed for archived or missing recipes; preserve redaction for historical misclassified recipe runs. No schema, price, balance, provider, public-enabled, or live-generation changes.
- Regression: ordinary API recipe quote/start/bootstrap, archived/missing recipe, both user/fixed source; regular projects must still quote, existing private runs remain redacted. Historical false-flag quote/run responses must be redacted while privileged admin access remains unchanged.
- RED: four new unavailable-recipe cases failed against the baseline as expected. Resolver patch then passed the focused 25-test contract/provider/repository/recipe suite.
- Verification: real pytest RED (4 unavailable-recipe cases, then 4 historical-redaction cases), then **30 passed / 1 dedicated-PostgreSQL skip** in the complete focused Genjutsu suite; changed-file Ruff, compileall and git diff --check passed. Independent review confirmed all public detailed run responses use the guarded response path. The full safe suite passed: **1582 passed / 18 skipped**, 92.91s. Dedicated PostgreSQL, frontend/browser, image and deployment verification are delegated to exact-SHA CI; production deployment remains pending.
- Additional mobile acceptance on production assets with synthetic API responses found a 320px trend fieldset wider than its 296px region (317px scrollWidth), a narrow header collision with Close, and the section's overflow-x:hidden creating an unintended vertical scroll ancestor for the sticky action. The scoped follow-up uses min-width:0 on the recipe fieldset, wraps the header title, and uses overflow-x:clip so the dialog owns vertical scrolling. Browser regression passed for editor and photo/video trend form at 320/360/390/430px, visible-control bounds, header non-overlap, actual file-picker activation without uploads, dialog scroll ownership and viewport-aligned action after scrolling. Full frontend: 27 suites / 99 tests passed, TypeScript, changed ESLint, production build and critical browser E2E passed; generated screenshots were visually checked. Independent review approved the final CSS/test diff.
- Rollout: PR #250 to `tanyapi`, independent review, exact-head CI, normal merge, exact production deployment and health verification. GitHub currently reports the base branch unprotected; settings are not changed by this task. Public rollout remains gated on separately authorized live provider coverage.


## 2026-10-05 — Genjutsu trend video/photo refs, mobile-fit studio and public launch

- Baseline: production/origin `tanyapi` `09c1cc01afb1470f98f8dbaf404364b95737d556`; branch `fix/genjutsu-trend-media-mobile`.
- Production finding — launches: Higgsfield credential, signed media storage and all Genjutsu prices are configured, but runtime settings intentionally have `public_enabled=false` and `verified_operations=[]`. This is why users can open the studio while every new public creation is blocked with `feature_disabled`; it is not a current provider outage.
- Release-gate finding: the existing admin contract correctly refuses public enablement until every exposed operation/resolution has a successful retained live result. Current production coverage is only Motion Transfer 480p. Public access will be enabled only after the missing provider matrix succeeds; prices and limits are preserved from runtime settings.
- Trend finding: private Genjutsu recipes expose only user-replaceable image references. Their source/motion video is always fixed and hidden, so a trend repeater cannot attach the video reference requested by the product flow. Provider contract itself remains one source video plus image references; no unsupported multi-video payload will be invented.
- Mobile finding: the studio renders a `snap-x overflow-x-auto` scenario carousel with minimum-width cards and then renders a second selector for the same three operations. On Telegram iPhone this creates the sideways scrolling/cropped layout shown in the report. The dialog also kept desktop modal margins inside Telegram, creating a visually nested «окно в окне».
- Contract: recipes gain a backward-compatible source binding. Existing recipes remain `fixed`; new trend recipes may declare one `user` video source slot. The caller-owned uploaded video replaces only that source, while photo slots remain typed images and fixed refs/prompts/assets stay server-private. Quote/cost is recomputed from the uploaded video's actual duration.
- UI: trend mode accepts the declared video slot and photo slots in one compact «Референсы тренда» surface. On phones Genjutsu is edge-to-edge inside the Telegram viewport (safe-area aware), with no nested desktop modal margins or horizontal overflow; desktop keeps the bounded dialog. The editor replaces the horizontal carousel + duplicate selector with one bounded three-column operation grid.
- No-hardcode/security: no price, provider route, prompt, balance rule or launch limit is moved into source. Public enablement remains runtime configuration. User asset ownership/type is validated server-side; hidden recipe assets are never returned to the client.
- Provider root cause found during live release-gate smoke: Higgsfield now returns `status_url`/`cancel_url` on `https://platform.higgsfield.ai`, while the adapter accepted only the submission origin `https://api.higgsfield.ai`. A successful POST was therefore misclassified as `provider_submit_missing_id` and quarantined. The fix fail-closes absolute handles to only those two Higgsfield origins and uses the platform origin for production status/cancel fallback; arbitrary response hosts remain rejected.
- TDD RED: backend source-slot tests failed because `RecipeStore.publish()` had no `source_binding`; frontend tests failed because recipe mode had no video input, the operation selector was horizontally scrollable, and the dialog retained mobile margins. A provider regression independently reproduced rejection of the live `platform.higgsfield.ai` receipt URL.
- Verification: Genjutsu backend matrix **22 passed**; full Mini App **27 suites / 99 tests passed**; ESLint passes from a clean generated-artifact state; production Next.js export/build passes; critical browser E2E passes at **320/375/390/430 px**, including an explicit Genjutsu no-horizontal-overflow assertion and full-width 430px mobile dialog check.
- Plan: [x] production/config/log diagnosis; [x] RED backend/frontend regressions; [x] recipe schema + source-slot backend; [x] mobile/trend UI; [x] provider receipt-origin root cause/fix; [x] final full regression + lint/build/browser E2E; [ ] deploy exact fix SHA; [ ] live admin coverage matrix; [ ] enable public runtime setting after release gate; [ ] production user-surface smoke/log review.

## 2026-10-05 — Restore photo-first defaults for Seedance 2.0 video

- Baseline: `origin/tanyapi` `2d276814151b5c8cd44f4b37524a2e53b71147a7`; branch `fix/restore-video-photo-defaults`.
- Reported production symptom: after selecting Seedance 2.0, Telegram opens `Текст → Видео`; users can attach a photo-reference but the screen still shows text mode, so the request is treated as text/reference generation instead of the familiar photo-first flow.
- Runtime/code evidence: the active advanced selector sets every ordinary model to `text`; `seedance_multimodal_compat` already documents `imgtxt` as the ordinary Seedance default, but that default is bypassed by `video_generation_compat._initial_type_for_model`. Production logs confirm Seedance 2.0 can send image references correctly at the provider boundary. Grok already has the corresponding photo-first normalization from the 2026-10-02 regression fix.
- Root cause: the newer advanced video selector bypassed the older Seedance defaulting seam. A stale Seedance FSM can also remain `text` after a photo-reference was attached, reproducing the screenshot even though the reference URL is present.
- Intended result: selecting Seedance 2.0 opens in `Фото + Текст` by default; an existing Seedance `text` session with photo references self-recovers to `imgtxt`; explicit text-only Seedance with no photo remains supported. Grok photo-first behavior is preserved.
- Scope: Telegram FSM/UI only. No pricing, provider IDs, payload schema, DB schema, Mini App API, balance/refund or Seedance 2.5 behavior changes.
- TDD: before fix, selection regressions failed `text != imgtxt` (2 failed / 6 passed in the focused red run). After the minimal fix, the focused Grok + Seedance video matrix is **131 passed**; final local full suite is **1571 passed, 18 skipped**.
- Review: explicit Seedance `Текст → Видео` remains available. Switching to text-only now clears Seedance photo/video media so stale references cannot silently turn the session back into photo mode. Mini App was audited but is not changed by this Telegram-FSM regression fix; Seedance 2.5 is also unchanged.
- Verification: changed-line Ruff **0 relevant** (89 legacy diagnostics outside touched lines ignored by the repository gate); changed Python compiles and `git diff --check` passes.
- TODO: [x] production evidence; [x] RED regression; [x] minimal fix; [x] focused/full tests; [x] changed-line lint/final review; [ ] PR/CI/auto-merge; [ ] exact deployed SHA + production smoke/log verification.

## 2026-10-03 — Profile remix retains published outfit reference

- Baseline: production/origin `tanyapi` `14588e1172a2b5b95290a179d1b3c840ebc87d6c`; branch `fix/profile-remix-retain-selected-references`.
- Production evidence: repeat task `img_051f6e19c900` launched Banana Pro with exactly one submitted reference. Its source task had two image references and `feed_reference_selection` retained only the second (outfit) image, so the provider never received the outfit.
- Root cause: `/mini-app/api/feed/remix` restored source references only when the user submitted no new files. Uploading a replacement face therefore replaced the entire reference array instead of replacing identity while preserving the explicitly published supporting reference.
- Contract: prepend submitted images and append only image URLs explicitly retained in the source publication selection and present in the canonical source task. This applies to owner and template-user repeats. Never restore an excluded face or a selected URL absent from the source; foreign repeats may inherit only this explicit public subset. Legacy private restoration remains owner-only and only as the no-upload fallback.
- TDD: endpoint regression reproduced `[new face]` instead of `[new face, retained outfit]`; after the minimal merge helper it passes. A replay against the real source snapshot resolves exactly the uploaded face followed by the selected outfit. Foreign-repeat coverage proves that an excluded source face is removed while the explicit published outfit remains.
- Impact: no schema, provider, pricing, balance, prompt or frontend contract change. Adds count-only launch telemetry without reference URLs.
- Verification: focused publication/privacy/remix matrix **45 passed**; full backend **1667 passed, 12 skipped, 4 established unrelated failures** (dispatcher attachment, two stale KIE webhook fixtures, Seedream 6000-vs-5000 expectation); compileall, Ruff on new/changed tests and diff whitespace passed. Self-review expanded the fix from owner-only to all template repeaters, but only for the explicit canonical public subset.
- TODO: [x] production evidence; [x] red endpoint regression; [x] minimal fix; [x] focused/full verification and review; [ ] PR/CI/merge/deploy/exact-SHA smoke.

## 2026-10-03 — Replaceable typed Seedance trend references

- Baseline: `origin/tanyapi` `96dfb63688339c14976816a3d7ab80cad017a91c` plus the changed-line Ruff correction from draft PR #234; task branch `feature/seedance-replaceable-reference-slots`.
- Intended result: when publishing a Seedance 2.0/2.5 trend, the author removes their identity and marks each remaining image/video/audio reference independently as hidden-fixed, user-replaceable, or excluded. A repeater uploads media matching each replaceable slot; face, clothing image and especially video references can therefore be replaced without exposing retained assets.
- Current state/root cause: the private trend v1 contract hardcodes one user photo as `@Image1`; every retained image/video/audio is persisted as `fixed_hidden`. The runner accepts image uploads only and sends an untyped `reference_urls` array, so `@VideoN` can never be replaced.
- Reuse: existing Seedance snapshot extraction/tag remapping, durable hidden asset storage, upload ownership checks, provider adapters, trend runner/idempotency and public prompt sanitizer. No new table or provider field is needed.
- Contract: reference-plan v2 stores only public-safe user slot metadata (`media_type`, provider `position`, label) in generation settings. Submitted typed slot values must exactly match that server-owned plan and belong to the authenticated Telegram user. Fixed asset URLs and source positions remain private. Provider arrays are assembled server-side in exact `@ImageN/@VideoN/@AudioN` order. V1 trends remain backward compatible.
- Security/data risks: reject missing, duplicate, extra, wrong-type and non-owned uploads; never accept client-supplied fixed URLs or provider positions outside the saved plan; preserve hidden prompt/assets and idempotency hashing. No billing, balance, referral or schema mutation.
- Public test seams: recipe compiler/assembler, admin publish HTTP contract, sanitized trend catalog payload, authenticated trend run/provider launch, Mini App publisher and typed runner uploads. Add RED regressions before implementation, then focused backend/frontend suites, full safe regression, build/lint/E2E and exact-SHA release checks.
- Rollout: keep PR draft until all gates pass; squash to `tanyapi`, verify exact merge CI/autodeploy, backend health, Mini App static revision and focused typed-slot telemetry. No paid live generation unless necessary; rollback by reverting the PR. Production is not updated yet.
- TDD/progress: compiler lacked typed slots (RED import/API), then v2 recipe and exact assembler GREEN. Publisher/runner regressions cover face + replaceable video, typed upload and API DTO. Security regressions reject missing/extra/duplicate/wrong-type slots; plan limit is 12; stale generated guards are replaced. Catalog and runtime pricing both count replaceable video. Editing replacement must match the published ceil-second duration and is rejected before debit if it would change price.
- Review: independent spec and standards reviews initially found catalog/charge mismatch, frontend format drift, duplicate URL reuse, >12-slot plans and stale guards. All were corrected; both re-reviews report no remaining blocker and confirm privacy/ownership/v1 compatibility/provider order.
- Verification so far: backend focused matrix **89 passed**; all frontend **23 suites / 66 tests passed**; TypeScript and ESLint passed; production build passed; critical browser E2E passed; Python compileall, Ruff on touched files and diff whitespace passed. Final full safe backend suite: **1665 passed, 12 skipped, 4 established unrelated failures** (order-dependent dispatcher attachment, two stale KIE webhook fixtures without `request.json()`, and the pre-existing Seedream 6000-vs-runtime-5000 expectation). The earlier feature-caused static contract failure was corrected and is green.
- TODO: [x] RED compiler/runtime typed-slot tests; [x] compiler/admin settings; [x] backend validation/assembly; [x] publisher controls; [x] typed runner uploads; [x] docs/observability; [x] final full verification; [ ] commit/PR/CI; [ ] merge/deploy/smoke.

## 2026-10-03 — Selective reference publication (Seedance included)

- Baseline: `2287c4827afb1345cae65da3e163a3234277d24b`; branch `fix/seedance-publication-reference-removal`.
- User-visible result: publication editor shows each photo/video reference separately. The author can exclude their face while retaining outfit/image/video references; excluded media is not returned by public feed/profile cards.
- Audit/root cause: publication had one `feed_references_visible` boolean, so UI/API/DB supported only all-or-none exposure. Seedance 2/2.5 uses typed image/video arrays, making this especially visible. Existing generation recipe, provider payload, prompt privacy and repeat routing remain unchanged.
- Contract/data: optional `reference_image_indices` and `reference_video_indices` on `/mini-app/api/generations/share`; task detail pairs each available preview with its stable source-list position. Backend validates those source indices before availability filtering and resolves them to stable URL selections persisted as JSON in nullable `generation_tasks.feed_reference_selection`. This prevents drift both before and after save when an earlier ref expires. Legacy null rows publish all references when enabled. SQLite/PostgreSQL additive migration; no manual SQL, config/admin, billing or provider changes.
- Privacy/security: task detail exposes only the owner's canonical publishable references; public serialization filters to saved selection. Invalid/out-of-range indices fail closed. Remix anti-transitive-reference protection remains in force.
- TDD: backend RED was `TypeError` for missing typed selection; UI RED could not find the per-reference exclusion control. Both are GREEN. Public seams are database/feed serialization and the Mini App publication component/API options.
- Verification: focused feed/privacy/API/profile matrix **105 passed**; all frontend **23 suites / 64 tests passed**; TypeScript, ESLint and production static build passed; changed Python compileall, changed-line Ruff and diff whitespace passed. Full safe backend: **1652 passed, 12 skipped, 4 unrelated failures**; isolated rerun confirms three deterministic pre-existing failures (two KIE webhook fixtures lack `request.json()`, Seedream test expects 6000 while runtime uses 5000) and the order-dependent dispatcher failure passes alone. System Python's initial database run lacked `aiogram`; project-venv rerun was green.
- Review: two-axis review found and resolved protected-task top-level leakage, malformed persisted selection fail-open, pre/post-save index drift, and the installed publication-scope wrapper path. Final standards/spec reviews report no implementation blockers.
- Remaining: PR/CI/merge and exact-SHA deploy/smoke. Production is unchanged.

## 2026-10-02 — Mini App Telegram availability and upload telemetry

- Baseline: `origin/tanyapi` / production `7c5431061f2eae448087aa56219e56873fe8aeba`; branch `fix/miniapp-chat-telemetry`.
- Production evidence: Mini App users who had never opened the bot generated repeated `TelegramBadRequest: chat not found` warnings/errors during start/result/failure notifications. Normal upload lifecycle events (`upload-start`, fallback start and HTTP 200 response) were all logged through one unconditional `logger.warning` call.
- Root causes: terminal Telegram delivery was conflated with generation/delivery failure (`failed`) or left retryable (`pending` in Seedance 2.5); client telemetry had no severity classifier. Frontend status values were checked and successful responses genuinely carried HTTP 200.
- Contract: completed generation results remain available in Mini App. `chat not found`, blocked bot and deactivated user become terminal delivery status `unavailable` with stable reason codes and no automatic retry; transient network/rate-limit failures remain `pending`. These expected availability states log at INFO without tracebacks. Upload interactions log at DEBUG, successful upload responses at INFO, and failed/network/unknown client events remain WARNING.
- TDD: public-seam regressions cover severity classification, structured Telegram reasons, DB persistence/claim behavior, Mini App start notification, image-result/failure notifications, Seedance 2.5 terminal and transient delivery, and no fallback download after a terminal send error.
- Scope: request-data delivery metadata, Telegram notification/error handling and log severity only. No schema migration, prices, balances, refunds, provider payloads, model routing or frontend wire fields change.
- Verification: focused delivery/telemetry/database matrix `143 passed`; full safe backend suite `1269 passed, 13 skipped`; Python compileall, import-order lint and diff whitespace passed. Static propagation review confirms `unavailable` is internal request metadata, old `failed/delivered` behavior is preserved, and transient failures remain retryable.
- Rollout: PR to `tanyapi`, exact-SHA CI/autodeploy, then production telemetry checks for HTTP 200 upload events and terminal Telegram availability without WARNING/ERROR or repeated Seedance retries.

## 2026-10-02 — Telegram backup part retention leak

- Baseline after rebase: `origin/tanyapi` `cb76a3b2656bb4444f29ec4f74208b29cbca12e8`; branch `fix/backup-telegram-parts-retention`.
- Production evidence: root filesystem is 81% used with 167 GiB free; project backups occupy ~58 GiB and `backups/telegram-parts` alone occupies ~53 GiB. `static/uploads` is a separate 293 GiB lifecycle concern and is not touched by this fix.
- Root cause: every backup uses a timestamped `archive_name`, but `backup_db.sh` deletes only `${archive_name}.part-*` before splitting. A new timestamp can never match chunks from earlier backups, so every Telegram transport chunk is retained permanently.
- Intended result: the dedicated part directory contains no stale/current `*.part-*` after a completed send; unrelated files are preserved. The backup archive/dumps and Telegram delivery behavior remain unchanged.
- TDD: an integration test copies the real script into a temporary project, stubs SQLite and Telegram transport, creates a stale chunk, forces archive splitting, and asserts the directory is clean. RED retained six part files. A second RED pass showed stale chunks also survived a later direct/small-archive send. GREEN removes stale chunks before either send path and current split chunks after all admins are processed, while preserving unrelated files.
- Scope: `scripts/backup_db.sh`, one integration regression and this ledger. No DB schema, generation, payment, provider, Mini App, pricing or user-data mutation.
- Safety: cleanup is limited to direct files matching `*.part-*` inside the dedicated `telegram-parts` directory while the existing backup flock serializes invocations. Non-part files are retained.
- Verification: shell syntax, Ruff format/check, diff whitespace and focused integration test passed; full safe suite after rebase `1256 passed, 13 skipped`. Five-axis review found no scope, symlink, concurrency or unrelated-file deletion blocker.
- Rollout: changed-line Ruff, rebase onto current `tanyapi`, separate PR, exact-SHA CI/deploy verification. Existing production chunks will be cleaned only after the code is deployed and no backup invocation is active.

## 2026-10-02 — Seedance private-trend implicit reference bindings

- Baseline: `origin/tanyapi` / production merge `82ccc5651e092a152e2e042b4b8e6d789896aa2e`; branch `fix/seedance-trend-implicit-bindings`.
- Production audit: checkout, container and Mini App are on the exact merge SHA; CI/deploy statuses are green; schema/indexes are present; no private-reference trends have been published yet.
- Real-data read-only compatibility check: among 250 recent completed Seedance tasks, 90 contained an identity image plus at least one additional image/video/audio reference. The compiler accepted 27 and blocked 63: 54 prompts had no explicit `@ImageN/@VideoN/@AudioN` bindings and 9 omitted the identity slot.
- Exact user-visible failure: the admin selects the creator identity and hidden outfit/object/video refs, but publication returns `Prompt must reference every retained media slot` or cannot produce a usable recipe even though the compiler's own identity guard already defines those roles.
- Root cause: `compile_seedance_trend_recipe()` validates that every retained slot is mentioned **before** appending `SEEDANCE_TREND_IDENTITY_CONTRACT_V1`, while that appended guard is the canonical source of automatically generated bindings for admin-selected assets.
- Invariant: explicit prompt references to excluded/missing media must still fail closed. Selected retained assets may be absent from the original prompt; the compiler must add exact bindings in its guard, keep `@Image1` as the sole identity source, and preserve independent image/video/audio numbering.
- Scope: compiler + focused tests + reference documentation only. No schema, prices, provider routing, billing, auth, UI controls or external API fields change.
- TDD loop: implicit prompt regression failed with `Prompt must reference every retained media slot: @Image1, @Image2, @Video1`; after moving completeness validation to the final compiled prompt, it passes. A second regression covers an explicit fixed asset with an omitted identity binding. Review then found that a blank source prompt could become guard-only; a new regression failed because no exception was raised, then passed after adding an explicit non-empty source-prompt invariant. Existing excluded-media and over-limit cases remain fail-closed.
- Verification: compiler/admin/runtime/privacy/storage matrix `105 passed`; final compiler suite `14 passed`; focused Mini App publisher/runner/idempotency `3 suites / 8 tests`; final full safe backend suite `1255 passed, 13 skipped`; Ruff format/check, compileall, changed-line gate and diff whitespace passed. Candidate compiler replay against the same production sample accepts `90/90` eligible tasks with the default first image as identity, never persists that identity, and includes every selected image/video/audio slot. All `10/10` eligible tasks from the latest 24 hours have locally available fixed assets for durable persistence. Five-axis review found no remaining correctness/security/architecture/performance blocker; empty prompts, excluded media and prompt limits remain fail-closed before provider launch.
- Production health audit: exact merge SHA across branch/checkout/container/Mini App; healthy container with zero restarts/OOM; schema/indexes present; no stale idempotency claims or orphan assets. One unrelated Telegram `chat not found` notification error occurred after a correct failure/refund commit. Disk usage is 81% with 167 GiB free.
- Rollout: focused tests, changed-line Ruff, full safe regression, PR to `tanyapi`, exact-SHA CI/autodeploy and post-deploy read-only smoke. No paid KIE generation.

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

## 2026-09-15 — tanyapi automatic merge gate

- Root cause: PRs could become fully green but stay open indefinitely because no auto-merge mechanism existed.
- Added `.github/workflows/tanyapi-auto-merge.yml`.
- The workflow runs only for non-draft same-repository PRs targeting `tanyapi`.
- It does not checkout PR code while holding write permissions.
- GitHub repository native auto-merge is enabled. `tanyapi` branch protection is `strict=true` and requires four GitHub Actions checks: Python/deployment validation, safe regression suite, Mini App browser E2E, and production Docker image.
- Regression contract added in `tests/test_tanyapi_auto_merge_workflow.py`.
- The workflow only arms native `--auto --squash`; GitHub performs the eventual protected merge, so the normal `tanyapi` push CI/CD fan-out remains intact.

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


## 2026-10-01 — KIE durable result delivery recovery

- Baseline: `tanyapi` / `origin/tanyapi` at `1840ba0dd4f39ceadfd58023f10b0654c1fbcbb8`; task branch `fix/kie-result-delivery-recovery`.
- Production evidence: KIE returned provider `state=success` and a `tempfile.aiquickdraw.com` result, while media retrieval intermittently timed out/truncated and Telegram returned `failed to get HTTP URL content`. Example Seedream task `8f4c6fc0c07ecc592fe819cf5b75a2ee` recovered on a later download attempt.
- Root cause: provider generation and webhook completion were healthy; temporary KIE CDN delivery was intermittent. Legacy KIE paths amplified the outage by treating a plain result link as delivered and, in one path, calling `complete_video_task()` even when media delivery failed.
- Scope: KIE/Kling result delivery in `bot/main.py`, shared delivery metadata in `bot/database.py`, durable localization of ephemeral provider URLs, and regression tests. No provider payload, model selection, pricing, balance/refund or frontend changes.
- Runtime contract: `success -> delivery lease -> durable localization with bounded retry/backoff -> persist canonical result_url/result_ready metadata -> Telegram media -> completed+delivered`.
- Link fallback is intermediate only: `delivery_link_sent=true` suppresses duplicate links, then delivery returns to `pending` so watchdog/reconciliation can retry the media after the lease expires.
- Ephemeral result hosts from `FEED_EPHEMERAL_RESULT_HOSTS` are force-localized for image/video delivery even with `PERSIST_PROVIDER_RESULTS=false`. Defaults: two attempts, 1s linear delay. KIE delivery lease defaults to 600s.
- Concurrency: `claim_task_delivery()` prevents webhook/watchdog double-send; `store_task_result_ready()` uses compare-and-swap on request metadata and preserves an active `delivering` lease while storing the canonical URL.
- Regression coverage: generic KIE image success + failed Telegram media/link fallback remains recoverable; Kling KIE `code=200` video path does not complete on link-only fallback; ephemeral KIE video is localized when global persistence is off; localization retries after the first transient failure; DB result-ready persistence preserves the lease.
- Focused verification: `92 passed`; focused Ruff and `git diff --check` passed; changed-line Ruff across modified Python files reported 0 issues.
- Full backend verification: `1372 passed, 2 skipped, 1 failed`. The sole failure is pre-existing/out-of-scope `tests/test_seedream_service.py::test_seedream_text_prompt_limit_increased_to_six_thousand_chars`: test expects 6000 while current `seedream_service.py` truncates to 5000. Neither Seedream file is changed by this branch.
- Review: standards/spec pass found and corrected one ordering issue in the legacy KIE payload so all three active KIE success paths now claim the lease before localization/result-ready persistence. No confirmed KIE delivery blocker remains locally.
- Release gates: push task branch, open PR to `tanyapi`, merge only with required GitHub CI green, then verify exact deployed SHA/container health and passive production telemetry. No paid generation is required for smoke.

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


## Project-wide 72-hour diagnosis — 2026-10-01

- Baseline: current `tanyapi` SHA `d5b4d27e1fdf67189da5a2f4fd70cc491bdd3f1a`; isolated branch `agent/project-debug-72h-20261001`. Production worktree and existing untracked files preserved.
- Requested window: 2026-09-28 18:42:55 UTC through 2026-10-01 18:42:55 UTC (21:42:55 Moscow). Destination: evidence-backed inventory of runtime failures, data/payment invariants, infrastructure availability and frontend critical journeys; reproduce and address confirmed defects within this scope.
- Guidance refreshed: Bambale0/skills diagnosing-bugs (evidence → minimal reproduction → regression), wayfinder-style investigation map; Bambale0/claw QA audit checklist; anthropics/skills webapp-testing.
- Investigation ownership: runtime/providers/Telegram; DB/payments/refunds; deploy/nginx/history coverage; Mini App/auth/browser; root cross-cutting observability and synthesis. All production investigation read-only. No customer generation/payment replay or balance repair is implied.
- Current audit: backend healthy at baseline. Actual application file history begins Sep30; handler retains one rotation; Docker current container begins Oct1 18:38 UTC. Need older journal/nginx/archive discovery before claiming 72h coverage. Runtime error totals include synthetic pytest fixture activity and must be separated from real production incidents. Actual DB is PostgreSQL, SQLite path is fallback only.
- Reuse: existing logs, task/provider IDs, generation/payment repositories, frontend guarded browser smoke, safe pytest suite and deployed revision endpoints. No preliminary refactor planned.
- Risks/blockers: incomplete historical application logs, test pollution of application logs, secrets/private prompts in raw logs, incomplete billing/delivery markers. Only sanitized aggregates/code evidence enter Git; private diagnostics remain in restricted /tmp directory.
- No-hardcode/config/migration: no business policy changes planned. Any retention/observability adjustment must use typed environment configuration where mutable; schema/API/UI/FSM changes only if confirmed evidence requires them.
- Verification plan: DB read-only invariants; classified log counts and coverage; health/SHA/nginx/backup metadata; browser journeys with all mutations mocked; test-first fixes at applicable public seams. Existing full regression evidence from immediately preceding release may be reused where code unchanged; new tests only for new findings.
- Rollout: findings/report first; any code fix receives focused and applicable full checks, independent review, PR to tanyapi and exact-SHA CI/autodeploy/smoke. Documentation-only findings do not require a manual production deploy.
- Steps:
  1. Establish fixed window, baseline and archive coverage — complete; application history limitation documented.
  2. Parallel runtime, DB, infrastructure and frontend investigations — complete.
  3. Correlate real incidents, reproduce actionable defects and classify resolved/external/unknown cases — complete.
  4. Apply verified fixes with regressions where justified; document limitations — complete.
  5. Independent review and local checks complete; PR, CI and exact deployment verification pending.

- Coverage established: PostgreSQL and nginx span requested72h; application files only Sep30 00:00:04..Oct1 18:42:55UTC (~42h43), first29h17 irrecoverable from available archives. Shared nginx lacks host/timing fields, so5xx subset is not full service rate. Found historical255-upstream-timeout outage Sep29 12:31:19..12:53:58UTC; missing application history prevents root-cause claim.
- Confirmed RED/GREEN: oversized saved reference photo (8 runtime failures), media→More edit (1), concurrent saved reference None row (6), insufficient log retention/test log pollution, latent telemetry credential logging. SQLite reference tests passed; actual isolatedPG16 exposed weaker initial fix, now per-user FOR UPDATE verified with observed lock contention and cap preserved. Standards review caught additional telemetry credential forms, now covered.
- Data totals:8024tasks=7494completed+530failed; no older2h nonterminal or completedmissingURL. Watchdog19/19timeouttasks laterdelivered.349completedpayments; negative balances/orphans/duplicatecommission/referral/promo keys zero. Refund history has incomplete markers; no blanket financial-clean claim.
- New critical evidence: missing/unreliable KIEHMAC lets callback payload drive status; repeated generic failure refunded twice in an isolatedpublic-handler repro. Igor clarified HMAC does not work (alreadytested). Design adjusted: allthreeKIE endpoints treat callback only as taskIDsignal and fetch authoritative provider record; no HMAC requirement. Unknown/currentID/terminal guards, pending nofail, transientlookup503, atomic genericrefund with expectedproviderID required. No manualfinancialrepair or callbackreplay.
- Verification seams expanded to provider trust/refundconcurrency/retryalias and actualPostgreSQL. No schema/businesspricing changes. Runtime log retention newtypedenv BANANO_LOG_RETENTION_DAYS defaults7minimum3; UTC sharedcleanup. README corrected toactualDocker/frontenddeployment and strict tanyapiworkflow.
- Independent review underway: Standards(ops) and Spec separate; dedicatedsecurityreview for KIE. Comprehensive sanitized report: docs/agents/PROJECT_DEBUG_72H_2026-10-01.md.

- Final local gate: `BANANO_SKIP_PROJECT_ENV=1 BANANO_DISABLE_FILE_LOGGING=1 PYTHONPATH=. /root/tanya/banano_kling/venv/bin/python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short` → **1179 passed, 8 skipped**, 66.00s. Skips include dedicated PostgreSQL-only cases; separate disposable PostgreSQL16 run `pytest tests/test_runtime72_saved_references.py tests/test_runtime72_postgres_refunds.py -q --tb=short` with guarded runtime test flags → **7 passed**. Temporary PG container/socket removed after verification.
- Focused callback/Telegram/watchdog regressions **86 passed**; independent security review **80 passed**, exact actual paid-retry helper differential: serialization bypassed creates2 provider tasks, current handler creates1 (all transport mocked). Both Standards and Spec reviews cleared final changes; previous findings (PG isolation and additional credential representations) corrected.
- Published baseline Mini App Chromium critical journeys passed with all API writes mocked, no uncaught JS exceptions; current frontend code unchanged by this patch. Existing API/auth/telemetry focused suite45 passed. New logging filesystem/subprocess suite9 passed after9 RED failures. Bash syntax of deploy/backup/CDN and diff checks passed.
- Delivery is not yet claimed: mandatory PR CI, runtime PostgreSQL CI, production exact SHA/autodeploy/health/log smoke remain. No migrations, price changes, manual financial repair, credential rotation or Nginx mutation. New technical retention environment setting is optional (default7days).

- Final changed-line Ruff gate: **0 relevant diagnostics**, 470 legacy diagnostics outside changed lines ignored by repository policy (16 changed Python files). New optional type and touched import order corrected; focused Telegram/reference suite then **8 passed, 1 PG-only skipped**. Changed runtime files compile; final diff check clean.

---

## 2026-10-02 — Seedance 2.5 provider-classified edit fallback

### Incident and root cause
- Baseline and production before this change: `tanyapi` at `efba53e0818c5f72cce58851d6b1513e271975b1`.
- Provider task `703fa69cddd2c08a3a2c2dcc25dc7fe7` used one valid 13.087-second video reference but was submitted with `duration=12`; KIE classified the prompt as video editing and required `duration=-1`.
- After the explicit-edit release, task `f8137388b44852d38c03f639e1ba26c3` reproduced the same failure with the edit toggle off and additionally required `ratio=adaptive`. This proved that the manual mode fixed only explicit intent; KIE can still reclassify an ordinary multimodal prompt server-side.

### Fix
- Before normal failure/refund handling, a matching admin-free Seedance 2.5 video task receives one atomic fallback attempt with `video_editing=true`, `duration=-1` and `ratio=adaptive`.
- The fallback is limited to pending multimodal tasks with exactly one locally valid 4–30 second source video. Legacy rows without the explicit edit flag remain eligible; malformed, already-editing, paid, wrong-model and wrong-type rows are rejected.
- A compare-and-swap claim in `request_data` deduplicates webhook/reconciler races. The successful replacement keeps the same generation row, replaces the provider task ID and stores old/new aliases so stale callbacks cannot complete, fail or refund the replacement.
- Paid tasks are not silently converted to editing because their quoted duration can differ from source duration. They retain the existing atomic failure/refund path.

### Billing invariant
- Seedance admin/test launches now persist `cost=0`, `charged=false` and `charged_cost=0`; the nominal configured price is retained separately as `price_quote` (and `admin_price_quote` on admin-only paths).
- Free admin repeats no longer reward a trend author from credits that were never charged.
- The generic watchdog now treats explicit `admin_free=true`, `charged=false` or `refund_on_failure=false` as non-refundable even if a legacy row contains a non-zero nominal cost. Legacy paid rows without these markers remain refundable.
- Production read-only audit found no pending/processing admin Seedance row requiring a cost backfill; historical terminal failures were not mutated.

### Verification
- RED reproduced the original ordering bug: the public failure wrapper refunded before any compatible retry. Separate unit and PostgreSQL RED tests proved that the watchdog credited 5 bananas to an explicitly uncharged task.
- Focused Seedance/KIE/refund/watchdog gate: **123 passed, 6 skipped**.
- Disposable PostgreSQL 16 gate: **9 passed**, including concurrent callback deduplication, atomic provider task replacement and no credit for uncharged admin tasks.
- Final safe backend suite: **1191 passed, 10 skipped**, 87 pre-existing warnings.
- `git diff --check` and changed Python compilation passed. No paid provider generation, balance mutation, old-task replay or database migration was performed.

### Rollout and observability
- New technical setting `SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS` defaults to 300 seconds with a minimum of 30 seconds; no production override is required.
- Success log: `Seedance 2.5 auto-retried provider-classified edit` with old/new task IDs and effective settings. Watchdog failure logs include actual refunded credits and whether billing markers disabled refund.
- Release gates: latest-head GitHub CI, independent PR review where available, automatic merge to `tanyapi`, exact deployed SHA/health/source verification and post-deploy error-log audit. No live paid smoke is authorized for this change.
- Residual risk: provider task creation and local task-ID attachment cannot be one distributed transaction. A hard process death in that narrow window can orphan an upstream task; CAS failures record the replacement ID and emit a critical log for reconciliation.

---

## 2026-10-02 — Prompt-repeat reward and admin billing invariants

### Release interception
- Seedance PR #224 merged as `7d9626b8cc8d1f4345a03ab5006da83afcf19299`, but its automatic deploy run `36931442700` was cancelled before the SSH/deploy step after a final financial review found a generic reward-path defect.
- Production stayed on `efba53e0818c5f72cce58851d6b1513e271975b1`; container image label, start time, public Mini App revision and health endpoint all confirmed that no partial deploy occurred.

### Root cause
- `_credit_prompt_repeat_reward_in_db()` trusted the caller's nominal `credits_spent` value. Admin generation paths skip the actual credit debit but several generic image/video repeat paths still passed the displayed positive price, so an admin repeat could credit the source author 10 RUB.
- Task completion calls the same helper again. The old idempotency sequence was `SELECT` followed by `INSERT` without a UNIQUE constraint, so launch and webhook completion could race and both award the author.
- `force_fail_task()` could also refund a legacy admin task whose row contained a nominal non-zero `cost` but lacked newer `admin_free/charged/refund_on_failure` markers.

### Fix
- Repeat rewards now require positive finite spend and a positive finite reward amount. The repeater is resolved from the database and current admins are rejected centrally, independent of the launch path.
- `prompt_repeat_events` has a partial UNIQUE index on non-empty `repeat_task_id`. Reward creation uses `INSERT OR IGNORE`, translated to `ON CONFLICT DO NOTHING` on PostgreSQL; only the transaction that inserts the event may update author balances.
- The author balance update must affect exactly one row or the transaction fails. Duplicate callbacks log the claimed task ID; admin attempts log the internal repeater ID without exposing Telegram identifiers.
- The watchdog now resolves the task owner's Telegram identity inside the same transaction and disables refunds for admins even when a legacy row has no billing markers.

### Production audit
- Read-only audit before migration: 36,985 repeat reward events, 34,431 non-empty task IDs, zero duplicate task-ID groups and no existing unique index. The index is therefore safe to create on deployment; the duplicate audit must be repeated immediately before rollout.
- Historical audit found 187 reward events (1,870 RUB) associated with current admin accounts across 36 authors. Five events (50 RUB) are explicitly marked `admin_free=true` / `charged=false`; 182 older rows predate billing markers. Some affected authors have completed withdrawals, so no automatic clawback, event deletion or balance mutation was performed.
- This release stops new admin rewards and duplicate awards. Historical reconciliation remains a separate accounting operation requiring confirmation of admin membership at event time and treatment of already withdrawn funds.

### Verification
- RED: four concurrent SQLite calls created four events and credited 40 RUB for one repeat task. Separate RED tests proved that a positive-price admin repeat credited an author and that watchdog refunded a legacy admin task.
- Focused database/task/watchdog/Seedance gate: 182 passed.
- Disposable PostgreSQL 16 workflow: 12 passed, including four concurrent connections, exactly one event / 10 RUB, admin reward rejection and admin refund rejection.
- Final safe backend suite: **1211 passed, 13 skipped**, 96 pre-existing warnings. No production writes, balance repairs, withdrawals, paid provider calls or old-task replays were performed.

### Rollout requirements
- Repeat the production duplicate audit immediately before deployment. If any duplicate `repeat_task_id` appears, stop rollout and reconcile before creating the UNIQUE index.
- Require exact-head validation, safe suite, browser E2E and production Docker image checks; deploy only the final merged `tanyapi` SHA.
- Post-deploy verify the UNIQUE index, exact image/container/public revision, health, changed runtime sources and error logs. Re-audit new admin reward events and pending admin tasks with refundable nominal cost.


---

## 2026-10-02 - Grok start-frame Telegram regression

- Baseline: `0b2263c7fed108007506cfb347ead6cb410162ab`; isolated branch `fix/grok-start-frame-20261002`.
- User-visible failure: after selecting Grok in the public video menu, a photo is rejected as text-only input; the following prompt fails for missing start image.
- Root cause: `video_generation_compat.select_advanced_video_model` uses `_initial_type_for_model`, whose default `text` incorrectly applies to both Grok image-to-video models. Legacy model-selection handlers already use `imgtxt`, so testing only those handlers misses the public-menu defect.
- Separate safety defect: the direct message launcher checks the mandatory Grok start frame after debiting credits, then compensates and clears the session.
- RED: offline production-image test container ran `pytest tests/test_grok_start_frame_flow.py -q --tb=short`: **20 failed, 7 passed**. Failures reproduce wrong initial mode, discarded photo/document, stale session rejection, and debit-before-validation for both Grok models.
- Plan: reuse the existing Grok model set; correct the actual public selector; normalize stale Grok state at screen/upload/launch boundaries without discarding media; reject missing images before any monetary/provider side effect, preserving prompt/settings. No prices, providers, model identifiers, schema or migrations change.
- Verification: real FSM and handlers through provider payload/task persistence with external IO mocked; include Telegram photo, JPEG/PNG/WebP documents, legacy state, both models and unaffected model types. Then relevant and full safe suites, lint/diff review, CI and exact-SHA deployment verification. No paid generations or production database writes.
- Mini App is not changed: this defect is the Telegram selector/FSM path. Provider payloads and shared model capabilities remain unchanged.
- Diagnosis considered: incorrect selector state (reproduced); failed media download (ruled out in the reproducer: handler exits before download); upstream rejection (ruled out: no provider request is made).

### Verification results
- GREEN: 35 Grok regression cases, including the registered aggregate router and real prompt-coalescing middleware; synthetic image bytes, Telegram IO, provider HTTP and monetary side effects are isolated.
- Focused regression gate: **129 passed** (Grok flow, advanced video contract, keyboard/provider contracts, Mini App continuity, prompt coalescing).
- Full safe suite in a disposable production-image container with networking disabled: **1304 passed, 13 skipped**, 96 existing warnings.
- First full-container run exposed three harness issues, not patched application tests: inherited `WEBHOOK_BIND_HOST=0.0.0.0` masked the configuration default, and nested pytest processes did not inherit `/testdeps` after resetting PYTHONPATH. Removing that image-level override in the test process and adding a disposable test-dependency `.pth` fixed them; the original failing config/logging tests pass unchanged.
- No production/container source edits, balance updates, paid provider calls, task replays, schema changes or routing changes were made. Release remains gated on PR checks and exact deployed-SHA verification.
- Review: original Grok model names, modes, resolutions and reference limits are preserved. Missing-photo rejection retains the prompt and settings; only the erroneous Grok input type is normalized. Other video models return unchanged from the normalizer.

## 2026-10-03 — Gemini 3 Pro Image / OpenRouter admin lab

- Baseline: `d50ea3bc2b18908d4b87b64b04f2ea9772bdaf64` (`origin/tanyapi`); isolated worktree and `feature/admin-gemini3-openrouter`.
- Result/spec: Main menu → Test → Gemini 3 Pro Image. Admin can enter a prompt, attach up to provider-declared reference limit, choose provider/aspect ratio/resolution, generate, download original, repeat, edit the previous output, and recover the last result after reopening. No bananas charged or public feed entry. OpenRouter usage is paid by the configured provider account.
- Existing: admin-only Telegram lab, OpenRouter credentials/base URL, reusable media saving, bot_settings audited persistence, durable outputs volume. Missing: image adapter and Gemini lab. Mini App has no corresponding test surface and public generation catalog must not expose the lab. No prefactor required.
- Contract checked live: GET `/images/models/google/gemini-3-pro-image/endpoints`: Studio 1K/2K/4K; Vertex 1K/2K; ten ratios; n=1; references 0–14; no streaming. Implement the dedicated POST `/images` contract; do not invent unsupported search, mask, seed, transparency or quality parameters. Iterative editing uses the saved output as an image reference.
- No-hardcode: capabilities fetched from provider; per-admin prompt/options/references persisted using bot_settings with updated_by audit; timeout configurable in lab. Fixed model ID is the identity of this model-specific screen. Existing secret config reused.
- Risks: duplicate paid POST, timeout with uncertain outcome, concurrent album uploads, stale callbacks, revoked admin access, delivery failure and restart. Consume persisted run nonce before starting; serialize admin mutations; bounded POST with no automatic retry; persist status and results before Telegram delivery; expose status/recovery. Sanitize errors and do not log prompts/URLs/keys/base64.
- Schema/API/UI/FSM: no migration/new public API; new admin FSM/router + access-control recognition; bot_settings and outputs volume reused. No payment adapter mutation.
- Observability: request UUID, admin ID, model/provider, reference count, resolution, elapsed time, provider response ID/cost when supplied, completion/delivery/error stage; runtime SHA is container label.
- Public test seams: provider HTTP adapter, Telegram handlers/FSM/auth, persistence through bot_settings, existing access middleware. Selected from repository instructions; no extra approval required.
- Verification: focused tests then safe backend regression suite, changed-line Ruff, syntax and deployment shell checks, existing Mini App E2E/Docker required CI. Frontend-specific E2E/migrations/payment/refund tests not newly required because no web UI/schema/billing changes; existing CI regressions remain required.
- Runtime preflight: production container healthy, /health 200; no existing Gemini lab telemetry. Recent runtime error count baseline: 1 in 15 minutes (not attributed to this change).
- Steps: (1) adapter contract + failing test; (2) persisted admin screen and generation/recovery flow + handler tests; (3) docs, review and safe checks; (4) PR to tanyapi with native squash auto-merge; (5) exact SHA CI/deploy + health/telemetry/smoke.
- Playbooks refreshed: Bambale0/skills implement, tdd, code-review; Bambale0/claw PR review checklist; anthropics/skills webapp-testing inspected (no new web surface).
- Progress: preflight complete; implementation starting.
- Implementation: dedicated dynamic-capability Image API adapter; persisted per-admin dashboard; prompt/ref FSM, serialized album uploads, nonce-based duplicate guard, original delivery/recovery and edit/repeat flows. Private result files; existing bot_settings storage; access middleware recognizes new FSM states.
- Red/green evidence: initial adapter test failed on missing module, then passed; handler persistence/auth test failed before router existed, then passed. Focused suite (Gemini + GPT25 + Seedance): **45 passed**. New Gemini suite: **23 passed**. Ruff, compileall and deploy shell syntax passed; full safe regression running.
- Live provider smoke: existing configured key; one text-to-image 1K/1:1 request, 2026-10-03. Success in 15.4 s; PNG 1024×1024, 762569 bytes, SHA256 `d12dc49e1a417ae44a50a2e86fda73b8af9d648112d9f0ceeddc2c8e64d45d4f`; usage.cost `$0.134436`. Image API returned no provider ID. No Telegram message or public feed entry created by smoke.
- Release gate discovery: GET branch protection required_status_checks returned HTTP 403, “Upgrade to GitHub Pro or make this repository public to enable this feature.” Cannot yet verify required strict protection. Do not bypass or report production deployment. Preparing reviewed PR/checks while investigating.
- Independent code-review (standards/spec agents): initially 2 standards and 2 spec P2 findings; all resolved and re-reviewed, no remaining blockers. Added adapter capability shape validation, safe error codes in telemetry, last_success retention across failed repeats, and metadata on original-only delivery.
- Added full registered `setup_dispatcher()` journey (lab menu → prompt → photo reference → generate) through AccessGuard with mocked transport; passes, including subscription-bypass behavior only for authorized admin lab events.
- Review red/green: 5 new cases failed before hardening, then passed; final focused new suite currently **29 passed**. Last-success recovery, preview rejection, malformed capabilities and route registration covered. Test settings cache isolated between temporary databases.
- PR: https://github.com/Bambale0/banano_kling/pull/232 (draft). Read-only branch query confirms `protected=false`, enforcement off and required checks empty. Required protection APIs/rulesets both return plan-related 403. No auto-merge armed because PR is ineligible draft and protection cannot be confirmed/restored under current plan.
- Final local safe regression after review fixes: `python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q` → **1366 passed, 13 skipped**, 74 existing warnings, 75.63 s. Changed-line Ruff at `0db4eed` → relevant=0/legacy=0, six Python files. Focused new suite 29 passed; aggregate routing included.
- Live multi-reference smoke after hardening: two generated synthetic reference images served through the actual configured `STATIC_BASE_URL` (`tanyapi.chillcreative.ru`), Image API `1K`, `16:9`, automatic compatible provider routing. Success: PNG 1376×768, 553039 bytes, 17.5 s, usage.cost `$0.136704`, SHA256 `3b3aef06f52af99158004dc2a1c0e97aa5bcd8c1a2141b492d20162719892154`. Both temporary source files removed. No real user media, DB reference rows, Telegram delivery or feed writes used. Total of the two successful provider checks: `$0.271140`.
- Preflight smoke correction: historical media.chillcreative.ru URL failed hostname certificate verification before any provider POST; actual configured reference origin is tanyapi.chillcreative.ru and succeeded. Existing media-domain documentation/certificate discrepancy is outside this change; no TLS verification disabled.
- Current implementation commits: `1db97bf`, `0db4eed`; final evidence recorded in following documentation commit. Exact final-head CI results will be attached to PR delivery report, avoiding a commit solely to record its own CI.
- Final rollout status: implementation/test/review complete; production unchanged. Waiting for final-head GitHub CI and resolution/explicit owner exception for missing required branch protection. No merge or manual deploy attempted.
# 2026-10-03 — Mini App users without a bot chat and refund-record consistency

- Baseline: `tanyapi` / production `821ec6a1f6068a939479788b7beb2697c7df0ffa`; branch `fix/miniapp-chatless-delivery-audit`.
- Intended result: a user created by opening a Mini App referral before starting the bot keeps the generated result in Mini App without any Telegram send attempt. Starting the bot later enables Telegram delivery. Provider failures keep refund crediting and task refund markers in one atomic path.
- Production evidence: two first-time referral users were created through Mini App, completed image tasks and persisted results, then received `chat not found` on generation-start, preview and link sends. Their task delivery state is terminal `unavailable`; generation accounting completed normally. In the reported 147-task window, 136 tasks completed, 134 were delivered in Telegram, two were unavailable, and exactly two completed images were successfully public in both feed and profile. There is no feed-publication failure in those rows.
- Refund audit: ordinary failed tasks record `refund_claimed=true` and `refund_state=refunded`. Four failed KIE Motion Control tasks costing 15+15+40+10 credits used the legacy Kling webhook branch, which credited balances before notification but persisted no refund marker. Logs and the application confirmation establish that 80 credits were already returned; this task must not credit them again.
- Root causes: users have no persisted tri-state Telegram-chat capability, so Mini App-created users are indistinguishable from users who started the bot. Separately, the legacy KIE Kling failure branch calls `add_credits`, sends the notification, and only then marks the task failed instead of using the shared atomic `force_fail_task` path.
- Reuse/prefactor: reuse terminal task delivery state and `force_fail_task`. Add a nullable/tri-state user chat capability: legacy rows remain `unknown` and preserve current behavior; newly created Mini App-only rows are `unavailable`; `/start` marks them `available`. Provider callbacks persist and complete chatless results before recording terminal `delivery_status=unavailable`, so Mini App retains the media while Telegram is not called. A first terminal send error also marks the current task and user unavailable.
- Security/data/config: additive users-column migration only; no provider payload, pricing, auth, admin configuration, payment, balance or referral-economics change. No retrospective credit mutation and no automatic 80-credit replay. Logs retain stable user/task/reason identifiers without secrets or media content.
- Public test seams: database user/task delivery contract; Mini App generation-start notification boundary; KIE Kling webhook failure/refund boundary. RED precedes each implementation slice.
- Acceptance: a newly created Mini App-only user causes zero Telegram sends and a terminal task delivery state; `/start` enables later sends; existing unknown users preserve behavior; KIE failure calls one atomic refund/failure operation and notification failure cannot roll back or duplicate it; the two public completed images remain public; the audited 80 credits are not credited again.
- Verification/rollout: focused regressions, SQLite/PostgreSQL migration compatibility, safe backend suite, compile/lint/diff review, PR to `tanyapi`, exact-SHA CI/autodeploy and production read-only smoke/telemetry. No paid live generation is required.
- Progress: RED reproduced three gaps: Mini App user creation had no chat capability argument, the start notifier attempted a known unavailable chat, and legacy KIE Motion failure never invoked the atomic failure/refund service. GREEN adds the tri-state column and callback gate, makes terminal task delivery update the user capability, restores it on `/start`, skips direct images/start/failure notifications, and routes legacy Motion failure through `force_fail_task` before notification. Independent reviews then found that pre-seeding terminal task state prevented generic KIE results from being persisted, dedicated Seedance 2.5 reset the terminal marker, and legacy/canonical KIE plus image-poller fallbacks could continue after `chat not found`. Corrected callbacks persist/complete first and then mark delivery unavailable; terminal errors stop file/link fallbacks immediately; Seedance last-frame terminal errors update the user capability without reclassifying an already delivered main video. Queued image-poller success/failure and Seedance/KIE webhook regressions assert zero further Telegram calls.
- Read-only publication verification: the two image rows from the reported snapshot both resolve through `get_feed_generation_card`, have `publication_scope=feed`, remain profile-visible, retain result media, and report `media_unavailable=false`. They were successful publications, not 11 publication failures.
- Verification: focused SQLite delivery/database/refund matrix **84 passed** before final additions; final targeted acceptance matrix **14 passed**; broader KIE/Seedance/Telegram matrix **67 passed**; isolated PostgreSQL 16 matrix **13 passed** including chat capability and refund idempotency. Final affected callback/database files are **128 passed**, with dedicated generic KIE, canonical/legacy terminal fallback, queued image poller, watchdog/prompt follow-up and both Seedance 2.5 delivery implementations covered; a fresh PostgreSQL 16 legacy-schema run without `users.telegram_chat_state` passed **2 tests** and proved the runtime helper adds the column. The last full safe backend run before the final three notification-only regressions is **1680 passed, 13 skipped, 4 established unrelated failures**: order-dependent dispatcher attachment, two stale KIE fixtures without `request.json()`, and Seedream test expecting 6000 while runtime uses 5000. The new webhook integration initially exposed its own fixture-path order dependency (`task_watchdog.DATABASE_PATH` imported before per-test DB setup); after pinning it to the isolated DB, the full run contains no feature-caused failure. Python compileall, changed-line Ruff gate (**relevant=0**) and diff whitespace passed. Frontend ESLint passed; all **23 suites / 66 tests** passed; TypeScript production static build and critical browser E2E passed.


## 2026-10-03 — Reference privacy and durable generation completion

- Baseline: `af11c3affb05aee79a03648690065a77ee554b88`, fresh `origin/tanyapi`; isolated branch `fix/privacy-and-result-durability-20261003`. Production tracked files unchanged; two pre-existing untracked operational files are excluded. Runtime healthy at baseline.
- Intended behavior: hidden source reference URLs never propagate into another user’s repeat request or detail response; source owners retain private inputs. Visible references retain existing repeat behavior. Successful provider output is durably persisted regardless of Telegram capability or start-notification failure. `/start`, callback retries and recovery cannot silently discard the result.
- Audit: PR #236 selected-reference retention does not consistently enforce references visibility. PR #237 conflates notification capability with terminal task delivery; generic KIE delivery claim can reject before completion persistence. No confirmed production incident is claimed.
- Constraints: no paid provider calls, old-task replay, refunds, real private media fixtures, credential changes or production-data mutations. Preserve prices, provider choices and unaffected flows. No schema/config additions intended.
- Test seams: Mini App public repeat/share/detail API with synthetic refs; Telegram generation-start and `/start`; real task persistence/claim integration and callback retries with mocked providers/transport. Existing safe suite, changed-line Ruff, compile, required Mini App E2E and Docker CI remain release gates.
- Plan: (1) red regressions per issue; (2) minimal fixes; (3) focused and baseline-comparison full safe tests; (4) independent standards/spec review; (5) draft PR and exact-head CI; (6) merge only after all applicable gates and authorization; (7) exact-merge CI/autodeploy SHA, health and read-only telemetry.
- Playbooks inspected: Bambale0/skills diagnosing-bugs, tdd, code-review; Bambale0/claw review checklist; anthropics/skills webapp-testing.
- Release blocker verified: `tanyapi` reports protected=false, enforcement off, zero required contexts. Protection endpoint returns HTTP 403 requiring GitHub Pro/public repository. Do not change access/security settings or mark a draft ready (auto-merge may merge immediately); parent notified for explicit owner decision if the gate remains unavailable.
- Progress: implementation and independent regressions in progress; baseline safe suite running on archived exact af11c3a code with sanitized environment and no production .env.

- Updated release authorization: owner explicitly approved a one-time exception to the unavailable branch-protection gate for these two fixes after successful tests/review (2026-10-03 05:44 UTC). No protection settings will change. Keep draft until exact-head checks/review pass, then release only reviewed code.
- Baseline safe suite on archived exact af11c3a: **1399 passed, 14 skipped**, 104 warnings, 77.62 s. Earlier ledger failures are not reproduced at this exact baseline; no baseline failures are waived. Read-only 20-minute runtime log summary: zero ERROR/CRITICAL/Traceback; four ordinary chatless-result retention messages. Image label confirms af11c3affb05aee79a03648690065a77ee554b88.

- Implementation: foreign image repeats intersect selected source URLs with current visibility/publication and viewer-card policy; hidden originals and provider contact-sheet derivatives cannot be retained/submitted as a foreign source. Ordinary owners retain their original private inputs. Direct task-detail reuses existing recipe redaction, complementing the already-present response middleware; no customer exposure is asserted.
- Durability: successful provider result, completed state/timestamp and recovery metadata now commit atomically before Telegram eligibility/lease checks. Start-notification failure changes user capability only. Explicitly retryable completed results reconcile from stored media without provider re-query; terminal/legacy completed results stay excluded. Callback persistence failures request retry. Late failure/callback races cannot refund or restart an already successful task. No schema/config/pricing changes.
- RED evidence: hidden-reference launch/retention failed before privacy gate; legacy detail/contact-sheet cases also red. Nine initial KIE/Kling ordering tests failed on baseline. A full-verifier processing→processing→completed failure interleaving triggered automatic retry when the final guard was removed in memory, then passed with the guard. No paid call occurred.
- Privacy focused matrix: 105 passed. Durability focused matrix: 188 passed; final durability regression file: 30 passed. Fresh isolated PostgreSQL 16 matrix: **15 passed**, including storage/delivery CAS and completion-versus-refund race. Safe aggregate before final test strengthening: **1443 passed, 16 skipped**, 157 warnings, 75.33 s; exact final aggregate rerun in progress.
- Integration test corrections preserve runtime behavior: feed removal can intentionally downgrade to profile; full withdrawal regression now calls the real remove_publication API. Reused PostgreSQL test user state required a fresh disposable database; no production fixture/data change.
- Independent standards review: approved, zero unresolved findings. Spec runtime review: no remaining blocker; final regression sensitivity corrected and rechecked. Review caught and resolved unbound retry logging, generic callback duplicate delivery, and stale-failure retry/refund races before release.
- Read-only rollout preflight 05:59 UTC: zero existing completed tasks with result URL and retryable delivery markers. Public frontend revision and backend image both af11c3a; public/local health pass. Recheck immediately before release and verify exact merged SHA after automatic deployment.


## Private ordinary image-repeat permission (2026-10-03)
- Baseline: dfdaa6f382516e158485d72dff20a871e3670cd9, fresh origin/tanyapi verified.
- Goal: independent explicit owner permission for selected source images to participate server-side in repeats without publishing their URLs or previews. Legacy publication selections are not permission.
- Reuse: publication owner checks, source availability, PR238 client redaction, server model limits and isolated synthetic tests.
- Add nullable permission snapshot; no backfill; empty selection revokes. Retain publication and Seedance rules. Never authorize inherited refs on remix children.
- Risks: descendant serialization, cached media, stale source selection, logging/provider recipe exposure, owner vs nonowner, prompt image ordering.
- Plan: (1) DB/HTTP permission and tests; (2) server assembly plus privacy boundaries; (3) owner UI and tests; (4) focused/full gates and independent review.
- Test seams: publication DB/API, remix launch provider payload, task-detail/bootstrap/history, public card/media, frontend publication journey. Synthetic data only. No paid generation, production mutation, merge or deploy.
- Rollout: draft review only after verification and authorization. New nullable schema is additive; old code ignores it.

### Private repeat verification / review progress
- Refreshed `/root/igor-skills`, `/root/claw-tools`, `/root/anthropic-skills` playbooks; used implement/TDD/code-review, frontend QA, security-review, webapp-testing guidance.
- API/DB runtime implemented: explicit nullable grant with no backfill; installed compatibility publication wrapper supports both feed/profile; owner detail returns indices; old clients clear grant. Original source and exact URL availability validated before provider use, including automatic KIE/Nexus/Wan retries and legacy child provenance.
- New descendants persist private input provenance; task/history/bootstrap/card/FSM and error boundaries redact inherited recipe. Mini App new repeats require original author publication rather than legacy child publications; owner Telegram child repeats preserve lineage and revalidate root permission.
- ImageN slot-preserving merge, combined reference-limit checks, and all-or-nothing Grok/Banana/Gemini reference transports prevent silent partial recipes. Gemini native fallback cannot drop URL-backed inputs.
- Independent review caught and closed production compatibility wrapper drop, child-owned Mini App bypass, Wan retry omission, profile-only Telegram hydration, stale UI consent after unpublish, remaining shared adapter URL logging, and partial provider transports.
- Backend full safe suite at ea6459c: **1533 passed, 16 skipped**, 81.10s; skips are pre-existing environment/live/PostgreSQL gates. Latest private API/runtime focused recheck after shared KIE log guard: **91 passed**, 5.34s. New ignored backend regression files explicitly added to Git.
- Frontend final: **25 suites / 82 tests**, full ESLint, TypeScript noEmit, production export, and aggregate browser critical flows passed. New browser coverage at widths 320/375/390/430: grant/restoration/revoke/unpublish→republish, no overflow/page errors; screenshot inspected. Mocked backend/provider; no real private assets or paid generation.
- `pip check`, compileall, deployment shell syntax, and diff checks passed; changed-line Ruff at ea6459c: 0 relevant, 603 existing diagnostics ignored by repository gate. Final exact-head aggregate gates and independent closure review follow before publication/merge.
- Release status: implementation isolated from production. User authorized draft PR publication and conditional merge after all exact-head checks/review. GitHub branch protection currently unavailable (protected=false; API403 plan restriction); parent owns explicit one-PR exception approval. Never change security settings or remove checks.
- Additive schema: feed_repeat_reference_selection TEXT; PostgreSQL schema + existing SQLite/PostgreSQL startup migration and publication compatibility ensure path. No production DB mutation performed.
- Cache restriction is prospective: cannot erase media already downloaded/cached. Full publication withdrawal clears grant; changing public preview visibility alone does not revoke separate private-use permission.

- Full safe suite at 0546425: **1536 passed, 16 skipped**, 80.68s. Independent closure review: no remaining blocking findings in reviewed scope; **91 focused security tests passed**.
- Narrow CI safety change: auto-merge command now matches the event's exact PR head SHA; no new workflow permissions or removed checks. This does not replace the all-green gate. Since pull_request_target uses the base workflow, current-PR controlled release must pause only the pre-existing auto-merge workflow after recording its state, verify every exact-head CI check/review, guarded-merge, then restore its prior state. Parent authorized this sequencing and the one-PR protection exception after user confirmation.

### PR239 CI lifecycle correction
- Remote CI exposed a real publication-editor lifecycle defect: 5-second bootstrap/focus refresh rebuilt reference arrays and triggered initialization effects, closing the editor and overwriting unsaved consent. Standalone E2E had passed; the main gate correctly blocked Docker/release.
- Added four deterministic failing React regressions and a real focus/timer refresh browser step, then fixed same-task draft-session hydration. Refresh preserves manual draft values, prunes unavailable/explicitly revoked private refs, never selects newly arriving refs, and resets on task switch/dismissal. No assertions/timeouts relaxed and no test retries introduced.
- Final frontend verification: **25 suites / 86 tests**; focused permission **17 tests on three consecutive runs**; full lint, typecheck and production build passed. Browser grant/revoke/refresh/unpublish flows passed at 320/375/390/430px on **three consecutive runs**, plus complete critical E2E gate.
- Existing backend and CI code are unchanged in this correction. Remote required checks will rerun for the new exact head before merge.

## Private-repeat PostgreSQL startup correction (2026-10-03)
- Baseline: 7d3a281e6bb1d0388ede1fedd3b1dd0329e5f43f (PR239). Code/container/frontend and exact post-merge CI were verified, but final production schema smoke found feed_repeat_reference_selection absent. Feature completion was withheld.
- Root cause: postgres_aiosqlite intentionally skips generic DDL; its separate raw _ensure_postgres_helpers migration list lacked the new field. SQLite tests covered the generic migration, while previous PG gates covered unrelated retention/refund behavior.
- Immediate recovery: one idempotent nullable TEXT ADD COLUMN, no default and no existing-value writes/backfill. Short lock attempts rolled back safely; bounded30s lock-timeout attempt succeeded. No restart or workflow/security setting changes. Read-only schema recheck passed; post-repair logs had zero errors/tracebacks/schema errors. Column can safely remain if app code is rolled back.
- Durable correction: add the same IF NOT EXISTS statement to raw adapter startup. A code-only helper test failed before the change and passes after; real-PG regression starts from absent legacy column, proves nullable/no default/no legacy grant, explicit grant persistence, and idempotent fresh startup.
- Local focused checks: 101 passed, 3 real-PG tests skipped; diff check clean. Local disposable PG launch was cancelled and not retried. The existing Runtime PostgreSQL CI job must pass the real-PG regression before this correction can merge; no equivalent local container workaround was used.
- Scope: three-line runtime migration and focused regressions only. No provider calls, customer data reads, billing changes, destructive migration, or permission expansion. Follow-up PR requires all exact-head CI/review; production schema + backend/frontend SHA revalidated after normal autodeploy.

## Full Higgsfield Genjutsu pipeline (2026-10-03)
- Task: complete the current branch as a full Genjutsu integration: Motion Transfer, Object Swap and Restyle across normal creation, saved-video editing, private Trends recipes, history, delivery and the admin control plane.
- Baseline: `ea36cf86564ed8b4ef9c2963c5326a975c15ad73` (`tanyapi` head at task start).
- User-visible result: one Genjutsu studio reachable from Telegram and Mini App, with projects/drafts, source trimming, ordered/role-labelled references, live Restyle presets, variants, chains, exact server quotes, durable status, stored results, repeat/edit/redelivery actions and admin recovery.
- Current-state audit: the branch only contained an inert Higgsfield Seedance 2.5 adapter. A separate unfinished worktree contained a substantial Genjutsu pipeline; its focused suite passed, but the catalog still used legacy `higgsfiled/...` endpoints and submit omitted the required `Idempotency-Key`. The reusable pipeline was ported into this current task branch and corrected against current official model docs.
- Contract: canonical production paths are `higgsfield/genjutsu/{motion-transfer|object-swap|restyle}/v1.0`; source duration is 4–30 seconds; Motion/Object require 1–8 ordered images; Restyle accepts 0–5 character images plus a current preset UUID; all advertise 480p/720p/1080p; Object Swap additionally requires at least 409,600 source pixels per frame.
- Architecture/data: dedicated provider, contract, media, repository, pipeline, delivery, recipe and API modules; new SQLite/PostgreSQL-compatible Genjutsu tables are created on startup. The PostgreSQL adapter exposes a narrow trusted-DDL seam because its general SQLite translator intentionally ignores DDL; the clean-deploy reference schema contains the same tables. Generation, financial and delivery states are separate. Fenced leases recover workers after restart. Provider request/status/cancel URLs, attempt ID and correlation ID are persisted.
- Finance: mutable per-operation/per-resolution prices, limits and admission live in validated/audited DB settings. Fresh installs fail closed (`public_enabled=false`, null prices, no verified operations). Quote, balance reservation, capture and refund are serialized transactionally; user request keys and provider idempotency keys prevent double charge/generation.
- Media/security: authenticated bounded uploads, ffprobe/ffmpeg validation and trimming, owner/total quotas, signed expiring provider/preview URLs, SSRF-safe bounded result download, private durable storage and server-side ownership checks. Webhook is wake-up only; authenticated polling establishes provider truth.
- Surfaces: Telegram `/genjutsu` and menu deep-link; Mini App studio/video/history entry points; completed videos can be reopened as source; private Trends expose only an opaque recipe ID and user slots; admin settings, verification coverage, reconciliation/adoption/refund/redelivery and event history are included.
- No-hardcode decisions: credentials and media origins remain env-only; model schemas are pinned to official docs; Restyle presets are fetched live; business prices/limits/availability are managed settings. Hidden recipe prompts/fixed assets never enter public Trend payloads.
- Public test seams: exact provider HTTP contract; pure plan/payload/quote contract; transactional repository; recipe privacy and substitution; runtime route coexistence/auth; Trend privacy/routing; Mini App studio component; full frontend build/browser E2E.
- Rollout: ship fail-closed, configure secrets and prices, perform paid admin verification for every exposed operation/resolution, then enable public admission. Disabling admission must not stop already accepted generation, persistence, delivery or refunds.
- Progress evidence: official contract research saved in `docs/research/higgsfield-genjutsu-api.md`; initial imported backend suite 50/50 green; red-green regressions added for canonical endpoints/idempotency/correlation, Object Swap pixel floor, configuration versioning and the native PostgreSQL DDL seam. Final focused backend matrix is 60 passed. A disposable real PostgreSQL 16 test passed repeated schema initialization, concurrent request idempotency and exact-once refund through the production adapter; the dedicated PostgreSQL CI workflow now runs it. All frontend tests are 26 suites / 89 tests passed; source ESLint and production static build passed. The critical browser E2E passes and now opens the real lazy-loaded Genjutsu studio from the shared shell. E2E exposed a malformed recipe-list response crash; the boundary now fails closed to an empty recipe list. Full safe backend is 1836 passed, 16 skipped, with six failures: the feature-caused create-hub keyboard regression was corrected and passes; the remaining five are established baseline issues (order-dependent dispatcher test that passes alone, two stale KIE fixtures, profile remix fixture and Seedream 6000-vs-runtime-5000 mismatch), each reproduced independently as applicable.
- Pending before PR: run two-axis review; commit/push; open PR to `tanyapi`; arm squash auto-merge only after exact-head CI eligibility. Paid live generation and production enablement require configured credentials/budget and are not inferred from local tests.

- Final review fixes: PostgreSQL recipe DDL now includes `verification_run_id`; recipe publication requires a completed admin-free run of the exact project revision; Object Swap validates the 409,600-pixel floor on every chain step; provider correlation is visible in admin recovery; accepted tasks are never auto-refunded on status/storage transport uncertainty and instead enter `recovery_review`; trend cards batch-load the live server-side recipe price. Current gates: Genjutsu focused backend **19 passed**, tracked safe backend **1561 passed / 17 skipped**, frontend **26 suites / 91 tests**, source lint/build green, PostgreSQL 16 Genjutsu test green, critical Chromium E2E green at 320/375/390/430 px. Fresh official docs check reconfirmed canonical `higgsfield/...` endpoints while `open.higgsfield.ai` still displays the callable legacy `higgsfiled/...` alias. Public admission remains fail-closed until paid account verification coverage and configured tariffs are present.

## Genjutsu owned-output Feed bridge (2026-10-05)
- Baseline: f70f84738981f145c630265664e87913437a1bb9; isolated feature/genjutsu-feed-bridge worktree. PR251 must be integrated separately with its source/quote/privacy safeguards preserved.
- Audit: ordinary Feed reads generation_tasks while Genjutsu results live in private assets/steps. Curated recipe_publish requires a verified admin run and must retain that gate. Existing RecipeStore already validates owned image/video replacements and explicit fixed/user bindings.
- Result: an ordinary owner may publish a completed final output and a private immutable repeat recipe; public cards expose output and opaque recipe ID only. Original prompts and inputs remain server-side. Recipe-derived runs cannot export another author's private recipe.
- Design: authenticated feed_publish API; atomic generation-task adapter + private recipe + step-idempotency binding; durable copy of final output only; exact declaration retries converge; changed declarations fail closed. Withdrawal blocks new repeats. No provider, balance, reward or price behavior change.
- Test seams: authenticated API, shared Feed DB/card helpers, RecipeStore substitution/revocation, durable media copy, Telegram button, existing SQLite and native PostgreSQL migration. Fixtures only; no paid runs, production data or publications.
- Steps: 1) failing API regression; 2) output/recipe adapter; 3) privacy, bindings, withdrawal and idempotency negatives; 4) frontend integration by separate worker; 5) full relevant gates and independent review; 6) parent-owned PR/release.
- Schema: additive genjutsu_feed_publications; startup native-DDL seam and clean PostgreSQL schema. Rollback leaves additive table unused. Public copying is outside DB transactions; deterministic output destination avoids repeat-copy proliferation.
- Progress: preflight/skills complete (Igor TDD/code-review, Claw security/release checklist, Anthropic webapp testing). No production runtime or database writes.
- Implemented: FeedPublisher copies only the validated final output, then atomically records private recipe, synthetic Feed task, step binding and a safe event. Public cards carry only opaque recipe ID/title and output. RecipeStore enforces shared Feed/Profile visibility; start admission takes the same publication-row lock used by withdrawal before reservation. Curated admin publication remains unchanged.
- Legacy routes: Telegram buttons redirect to Genjutsu before billing; generic Mini App repeat returns genjutsu_recipe_required. Synthetic rows are excluded from generic recent task history while safe owner detail remains available to the existing Profile publication editor.
- Review corrections: match existing shared-Profile semantics; do not resurrect a withdrawn/discovery-removed post on a stale publish retry; preserve completed snapshot chains/variants and full quote; put schema addition before COMMIT; retain idempotent accepted-run retries after withdrawal.
- Verification: 32 new Feed bridge tests; focused Genjutsu matrix 62 passed, 2 PostgreSQL tests skipped locally. Full safe backend suite 1614 passed, 19 skipped in 92.19s. Real PostgreSQL bridge regression added to the existing runtime CI file and must pass in CI before merge. Isolated tests used env-i, BANANO_SKIP_PROJECT_ENV=1, BANANO_DISABLE_FILE_LOGGING=1. No production data, provider/balance calls or real user publications.
- Parent owns frontend integration, PR251 conflict resolution, independent review, exact-head CI and authorized merge/release. Backend artifact is ready for that integration after remaining static checks.

## 2026-10-05: clarify hidden versus replaceable Seedance references

- Baseline: f70f84738981f145c630265664e87913437a1bb9 (tanyapi). Audit confirmed PR226/227/235 server-only fixed references and typed replacement slots are present.
- No permission, provider payload, billing, or fixed-binding behavior changes. Publisher copy now distinguishes hidden fixed references from hidden originals replaced by user uploads. Added mode-switch and fixed-preservation UI regression tests.
- Checks: isolated backend reference/admin/trend/privacy suite 78 passed on baseline; frontend publisher/runner/API/settings suite 14 passed on final edits; targeted ESLint passed. No paid generation or production publication. Browser verification remains part of the combined Genjutsu Feed integration.
- Genjutsu ordinary Feed publication is a separate implementation; do not describe this clarity patch as that bridge.



## 2026-10-06 — Direct-upload Seedance trend references (in progress)

- Baseline: `3fd259c`, task branch `feature/seedance-trend-upload-refs`, isolated checkout; production remains untouched.
- Request: add the existing hidden-fixed / user-replaceable / excluded reference choices to ordinary Trends → Add for Seedance 2.0/2.5. Preview is separate from generation references. No other models, old-trend rewrites, publication or deployment are authorized.
- Audit: generic `trends-tab.tsx` has preview/prompt/settings but no source-reference editor; generic `prompts/submit` does not compile a private recipe. Completed-task Seedance publisher already has a private compiler, durable typed assets, server-owned ordered slots, hidden prompt, exact input validation and measured editing pricing. Reuse these, not Feed grants or Genjutsu recipes.
- Existing contracts: `seedance_trend_admin_api.py`, `seedance_trend_recipe.py`, `trend_api.py`, `trend_reference_storage.py`. No database schema changes intended.
- Plan: (1) add synthetic failing API and component tests; (2) validated admin direct-upload API reusing private compiler/storage/settings; (3) model-specific source-reference editor and matching API client; (4) mobile browser upload/mode/reset/publish/repeat checks; (5) full applicable checks and independent review; (6) report patch and limitations without push/deploy.
- API: `admin/trends/seedance/publish-upload`, owner-bound typed source URL arrays, 1-based identity/fixed/replaceable selections, title/description/private prompt, separate preview and validated generation settings. Existing task-based endpoint remains compatible.
- Security: authenticate admin server-side; local owned upload and actual media validation; no raw fixed assets in responses; keep type/order/duration/provider constraints and pre-charge run validation. No paid calls, refunds, resends, production mutations or real customer media used.
- UI acceptance: controls are visible during generic Seedance creation, each selected ref can be hidden-fixed/replaced/excluded, pending uploads cannot publish, reset/cancel/model switch cannot resurrect stale references, other model forms unchanged.
- Test seams: HTTP creation API, compiler/runtime recipe assembly, rendered React interaction, browser wire request with all external providers denied/mocked. Reuse runtime pricing and provider adapters; no new prices or mutable business hardcodes.
- Operational context: related read-only production audit was completed separately; this is a verified missing feature, not a provider incident. No production logs/DB changes required for implementation.
- Review sources: repository AGENTS/README/reference contract; Bambale0 skills implement/TDD/code-review; claw PR/QA checklist; anthropics webapp-testing.
- Rollout: explicitly out of scope until separate approval.

### Verification checkpoint (2026-10-06 13:06 UTC)

- Backend focused: 146 passed. Full safe backend: 1791 passed, 19 skipped, 262 warnings in 113.47 s; `tests/ --ignore=tests/live -m "not live_smoke"`, isolated venv/database and synthetic media. No provider calls.
- Frontend full: 32 suites / 170 tests passed; API transport has 3 tests, new rendered creation flow has 13 tests. Full lint, TypeScript and production static build passed.
- Existing critical browser aggregate passed, including private Feed and Genjutsu suites. New direct-upload mobile fixture passed at 320/360/390/430 px, confirms typed wire selections and repeat form privacy.
- Visual QA found clipped long replacement text at 320 px; compact selector text plus wrapping explanation was added. Final copy-only build `20261006130258` passes focused tests/lint/build. After explicit retry approval, final mobile rerun passed all four widths at 13:07 UTC; the final 320 px screenshot was inspected, compact option and wrapping explanation are readable and controls are hit-test reachable above navigation.
- Independent review found header-only Seedance 2 video/audio validation insufficient; fixed by upload-only bounded ffprobe, file/pipe protocol allowlist, stream kind/positive duration checks, cancellation/timeout kill and reap. Focused malformed-container/audio-only-MP4 tests added. Independent read-only peer recheck completed at 13:10 UTC with no blocking specification findings.
- Standards review of frontend reported no blocking issue. Optional improvement: show the 12-replaceable-slot count before server validation.
- Source publication idempotency is best effort via per-author content fingerprint and process-local lock; concurrent requests across separate workers do not have a database uniqueness guarantee. No charge/generation occurs during publication.
- No schema migration, rates/provider changes, old-trend rewrites or production mutation. Dependencies retained for authorized subsequent combined integration; no push/PR/merge/deploy performed.
## 2026-10-06: Robokassa nomenclature (isolated, not released)

- Baseline: tanyapi 3fd259c4704ae13593018b90da4b8b0a40bb8ab9.
- Scope: new checkout Receipt for Telegram/Mini App. No production/credentials,
  provider calls, receipt registration, refunds, cabinet changes, push or deploy.
- Audit: shared adapter omitted Receipt completely; Description is not an item.
  Existing amount normalization/signature helpers and both shared callers reused.
- Invariants: one package = one item; sum equals normalized OutSum; Receipt bound
  to checkout signature; result signature/idempotent payment completion unchanged.
- Configuration: explicit receipt tax; optional method/object; no invented SNO.
  NPD confirmed by owner; RoboChecks SMZ activation unverified release blocker.
- No schema/API response changes, frontend or migration required. Receipt name
  derives from actual selected credits; prices/bonus rules remain existing config.
- Steps: (1) official docs and code audit; (2) red regression (11 passed, 1 failed
  KeyError Receipt); (3) signed encoded Receipt; (4) both callers, config guard before
  pending transaction; (5) offline decimal/negative/signature tests; (6) review.
- Test seam: public checkout URL and callback verifier, synthetic credentials only.
  33 focused service tests passed. Final combined run: 63 passed (one existing aiohttp NotAppKeyWarning), covering both checkout surfaces and invalid-config guards, existing payment/partner regressions. Ruff, py_compile and git diff --check passed.
- Observability: invalid config logged without secrets or personal information.
- Real payment/receipt/end-to-end provider smoke deliberately not run.
- Rollout: separately approve release, configure ROBOKASSA_RECEIPT_TAX=none for
  confirmed self-employed seller, verify active SMZ/My Tax integration, run normal
  CI. No automatic repair of historical payments. Existing callbacks stay enabled.

- Release continuation 2026-10-06: owner approved separate PR/merge/deploy and tax=none. Rebased on PR259 squash 2c080035; preserved both execution entries. Merge serialized after verified PR259 deployment. No actual checkout/payment is authorized by this continuation.


## 2026-10-06 — Seedance 2.5 explicit identity transfer (in progress)

- Baseline: `origin/tanyapi` b7c71a51727d4d5953536a50b9c0c2d15ef3dee6; isolated `feature/seedance25-identity-transfer` worktree. Production and the separate bot-start removal release are untouched.
- User outcome: an explicit character-replacement scenario for ordinary users as well as admins, using the APIX role-separated reference contract. Normal multimodal/reference generation remains unchanged.
- Fresh audit: Tanya already passes ordered image/video reference arrays to KIE `bytedance/seedance-2-5`; its dedicated form has no identity-role prompt contract. Explicit editing controls provider duration -1/adaptive but ordinary auto/edit is admin-restricted. APIX identity transfer assigns image identity and video motion/scene roles; its old Seedance 2 direct-video bypass is unrelated and must not be copied.
- Reuse: existing media upload/validation, source-duration probing, preset-manager rates, provider adapter, task persistence and failure/refund lifecycle. No provider migration, new tariff, schema migration, secret or production configuration change planned.
- Immutable technical contract: 1–3 identity photos of the same person plus exactly one 4–30 second source video; stable per-media ordering and @ImageN/@Video1 bindings; source-video identity must not compete with identity photos. Additional user instruction is preserved separately from the generated provider role instructions.
- Billing invariant: provider duration remains auto (-1), while paid identity uses server-measured source seconds rounded up for existing per-second pricing. Unknown/unverifiable duration is rejected before debit. Quote and launch must agree; admin-free tests are insufficient. Unrelated auto/edit restrictions stay intact.
- Security: validate roles/counts/final prompt before paid submission; do not log full prompts/media/secrets; accept only supported KIE fields; no implicit paid retry, actual generation, refund, resend or external customer communication during implementation.
- Steps: (1) red/mock provider and paid launch regressions; (2) shared server identity contract and safe billing/quote seam; (3) explicit UI with ordered role labels and mode-switch preservation; (4) focused/full backend and frontend tests, lint/types/build; (5) mocked mobile browser/visual QA; (6) independent review, draft PR. Merge/deploy require separate approval.
- Test seams: provider request capture, authenticated Mini App quote/start with synthetic media, Telegram shared validation, negative missing/extra references, ordinary 15-second reference versus auto source-length edit, stale quote or unknown-duration rejection, role-binding and mode-change regressions.
- Verification layers: DB schema unchanged; task metadata compatibility and charge/refund invariants require mocked tests. No runtime or paid quality test is claimed. Full safe suites exclude live providers.
- Guidance: AGENTS.md, .agents/README, README and current provider/reference code; primary engineering playbook discovery plus claw code-review and anthropics webapp-testing guidance.

### Implementation checkpoint (18:24 UTC)

- Provider tracer RED: identity keyword unsupported; GREEN after the shared role contract. Initial 22 provider/spec tests passed.
- Review fixed existing video-reference price multiplier omission before release: current quote/debit/persist use ceil(source seconds) × existing rate × existing multiplier, no tariff change.
- Added fail-closed owner/canonical local path validation before probing; both original and expanded prompts/tags are validated before debit. Provider receives only documented KIE fields.
- Telegram effective keyboard/repeat state preserve identity, measured quote is shown and rechecked, and callback launch attributes payer/owner to the callback actor instead of bot-authored message.from_user.
- Quote-only validates a strict boolean and cannot create/debit. Provider auto-retry explicitly excludes identity. Original prompt is persisted without the generated role prefix.
- Latest focused backend 130 passed; prior full safe suite 1921 passed / 19 skipped. Exact final full rerun in progress after repeat/quote lineage guards. Legacy Ruff comparison has zero newly introduced findings.
- Frontend full lint/type/Jest checkpoint: 197 tests passed. Mocked paid identity and ordinary 15-second reference browser paths passed at 320/375/390/430px; final repeat and validation rerun still pending.
- Owner-only task-detail hydration is reused by Feed/Profile/deep-link own repeats, with stale-route checks. No public reference metadata or database schema expansion. Mode switches clear lineage; explicit empty inputs stay empty; quote uses current prompt.
- Two Sentinel calls were canceled and not bypassed; after explicit user continuation approval, the exact calls were retried once and succeeded. No production mutation or real generation occurred.

### Final isolated verification (18:38 UTC)

- Frozen backend full safe suite: **1930 passed, 19 skipped**, 308 warnings. Repeated with a newly created `PYTHONPYCACHEPREFIX` to guarantee freshly compiled source: same result, exit 0 in 121.68 seconds. Focused backend: **130 passed**. Compilation and diff checks passed; new code Ruff clean, 17 existing modified-legacy findings exactly match baseline.
- Final frontend: full lint and TypeScript passed; **201 Jest tests passed**. Production static export rebuilt after clearing only isolated generated webpack cache because source-preserving writes retain mtimes.
- Full critical browser aggregate: **passed**, exit 0 in 187.05 seconds. Includes existing critical, private-repeat, Genjutsu and Seedance upload suites plus identity mobile at 320/375/390/430px, paid quote/start, normal 15-second reference, invalid/short/external inputs, balance, resolution, stale-price recalculation, owner/denied/foreign repeats, Close during hydration and stale/deep-link navigation. All provider/application transports mocked.
- Pixel QA: inspected fresh 320px input screenshot and 430px price/CTA screenshot. Role labels wrap, counts and source-length/price are readable, no horizontal clipping; CTA remains above bottom navigation in viewport screenshot. Screenshots are local QA artifacts, not committed.
- Independent read-only review: no remaining source-level security, financial, provider-contract or repeat/navigation blockers after fixes.
- No production service/static change, real generation, payment/refund, resend, migration or new tariff. Draft PR only; merge/deploy require separate approval.


## 2026-10-06 — Single-photo Seedance trends
- Baseline: tanyapi 7ade537898ce9250be50bfc32c7756aec8670144.
- Goal: allow one primary replaceable identity image plus prompt, with no additional template media, for Seedance 2.0 and 2.5.
- Audit: upload frontend and shared compiler both required another included reference. The version-2 slot assembler already supports zero fixed assets. Owner/type checks and excluded-reference prompt validation stay unchanged.
- Scope: remove redundant minimum-two checks; retain mandatory valid identity, overlap checks and private media handling. No database migration, config, pricing, provider or permission change.
- Regression plan: compiler and upload-to-serialized-recipe-to-repeat for both models, excluded extras, missing identity, privacy, frontend publication, existing multimodal suites, browser mocks, lint/type/build/CI.
- Evidence before fix: focused backend run produced six expected failures with “Keep or replace at least one template reference”; two missing-identity cases passed.
- Guidance used: Bambale0 skills diagnosing-bugs (red regression first), Bambale0 claw QA source-to-action contract checks, anthropics webapp-testing browser verification.
- Release plan: dedicated fix branch -> reviewed PR to tanyapi -> required green gates and native squash auto-merge -> exact deployed SHA and read-only/mocked production UI verification. No real trend publication or paid generation.
- Review found the same minimum-two rule in Studio source inspection and its publisher button; both are included so uploads and completed source tasks share the one-photo contract. Access/model/completion/repeat-origin checks remain unchanged.
- Interim verification: 1940 passed / 19 skipped full safe backend suite, 208 frontend Jest tests, static production build; final reruns follow the Studio regression additions.
- Final local verification: 1949 passed / 19 skipped full safe backend tests; 35 Jest suites / 216 tests passed; full Mini App ESLint, TypeScript, targeted Ruff, deployment shell syntax, production static build and git diff --check passed. Six mocked browser cases passed (four mobile multimodal widths plus one-photo Seedance 2.0 and 2.5). Independent final source review found no blockers.
- Security: no live trend publication or provider generation; all browser API calls mocked, SQLite tests isolated. Existing production checkout left untouched.
- Release status: PR/CI and exact production revision verification pending; do not claim deployed yet.


## 2026-10-07 — Telegram promo buttons for existing trends

- Baseline: tanyapi 8885e4b5f07012167343997159495731633c1318; isolated feature/promo-trend-buttons.
- User scope: existing Telegram admin flow, not a new Mini App editor.
- Audit: reuse notification_campaigns, notification_deliveries and bot-owned queue worker;
  existing internal API was single-text/button, Telegram FSM single media and no tested-content gate.
- Public interfaces under test (explicit user specification): Telegram handlers, normalized
  Bot API payload, campaign operations, PostgreSQL transactions, worker delivery/recovery.
- Implementation: 0–2 text+trend_id buttons; server-paginated approved/public trend lookup;
  existing prompt_link builder; albums then text+vertical keyboard; persistent draft revisions;
  queued tests for config.admin_ids through the same renderer/worker; matching tested hash
  required for launch; immutable snapshot; atomic audience materialization; persisted part receipts.
- Historical running campaigns are not converted to new drafts. New Telegram promos, including
  zero-button promos, require an admin test. Internal legacy endpoints cannot launch/test a v2
  promo around this gate. Old Telegram confirmation reopens the new editor.
- Additive migration extends existing tables. No new queue infrastructure or credentials.
  Uncertain Telegram acceptance is terminal and requires reconciliation, not blind replay.
- Provider generation, payment, balance, referral attribution and optional bot-start offer:
  unchanged. No paid generation, real admin test, mass send, production migration or release run.
- Guidance used: current repository AGENTS; existing Bambale0/skills implement/tdd/code-review,
  Bambale0/claw safety/QA guidance. External playbook updates were denied and not retried.
- Progress: first 17 real PostgreSQL acceptance tests passed on isolated localhost test DB;
  renderer/worker tests and Telegram handler tests passing separately. Independent safety review
  and broader regressions still in progress.
- Release remaining: final checks/review, publication authorization, confirmed safe smoke content
  and eligible admin recipients, real Telegram link click checks, release and exact revision check.

- Final verification: broad safe backend suite 2042 passed / 41 skipped; latest changed-path
  retest 117 passed; isolated PostgreSQL suite 27 passed including real Telegram handler→DB
  composition, revoked/no admins, edit during in-flight album, concurrent edit/launch,
  row-lock availability guarantee, remaining admin tests after launch and crash recovery.
- Independent review found and resolved ambiguous 5xx replay, revoked-admin pending deadlock,
  and availability TOCTOU. Schema constraint upgrade now runs only when its definition needs
  changing. No unresolved high-severity finding remained in the reviewed queue/backend scope.
- Deployment caveat: no mixed old/new worker versions or code rollback with active v2 work.
  Previously failed legacy attempts remain as-is; their past Telegram acceptance is unknown.
- Acceptance not yet performed: real Telegram delivery/click-through, production logs,
  GitHub publication/CI and release. Tests use synthetic recipients and mocked Bot API only.


## 2026-10-07 — Production promo lease clock correction

- PR266 deployed as 6351c208eddf248e4e2ddc01b3cef825daf6340d; Git/container/public
  revision matched and health was OK. The approved synthetic admin test exposed a runtime
  deadline bug: production PostgreSQL uses Europe/London, while leases were naive UTC values.
- Both test recipients lost the lease fence before the first Telegram part call. Persisted
  part lists stayed empty; their rows are retained as uncertain. No mass delivery rows were
  created. The separately approved upload album succeeded and its file IDs can be reused.
- Reproduced through the real pooled PostgreSQL adapter: a new 90-second lease measured
  -3510 seconds. The first non-UTC acceptance run had 11 failures / 18 passes.
- Correction uses database clock arithmetic for claims, lease renewal, completion retry
  deadlines and legacy retry scheduling. No production timezone/server setting changes.
- Regression runs exercise UTC, Europe/London and Asia/Kolkata through test-process PGOPTIONS.
  Real admin smoke must be repeated only after verifying the corrected deployed revision;
  preserved evidence proves the first campaign test never reached Telegram.

- PR266 review follow-up: fixed fifth in-flight test replacement, safe recovery of fenced
  claims before intent (including reclaiming unused fifth attempts), and prospective
  transactional revision attribution. Existing unfenced or in-flight uncertain attempts
  are not automatically retried. tested_at is serialized with its database timezone.
- Combined isolated PostgreSQL acceptance: 47 passed; focused non-PG regressions: 104 passed.
  Dynamic policy configuration was assessed as a separate operational improvement, not
  a current P1 correctness failure; validated 60/90-second technical defaults remain.
## 2026-10-07 — canonical public media origin

- Baseline: `6351c208eddf` on `tanyapi`; task branch `fix/media-public-origin-neironych`.
- User-visible result: all newly generated public media URLs use `https://tanyapp.xn--e1aikcel5c5a.online`; legacy `https://tanyapi.chillcreative.ru/uploads/*` remains readable for backward compatibility.
- Scope decision: change media origin only. Telegram/payment/provider webhook origins remain on `tanyapi.chillcreative.ru` to avoid breaking external callbacks.
- Existing infrastructure: `tanyapp.xn--e1aikcel5c5a.online` already has valid TLS and proxies `/uploads/` to backend port 1888.
- Config: production `STATIC_BASE_URL` and `GENJUTSU_PUBLIC_BASE_URL` moved to the canonical Mini App/media origin.
- Compatibility: backend local-upload resolver accepts both canonical and legacy hosts; reference ranking prefers configured canonical host while retaining old saved URLs.
- Frontend: local/provider media rewrites now use the live Mini App origin instead of restoring media to the backend hostname.
- Tests: add regression coverage for canonical and legacy local upload hosts; update Mini App media contract.
- Verification pending at time of entry: focused pytest/Jest, diff review, runtime restart/deploy path, HTTPS media smoke.

- Follow-up audit after PR #267 merge: production CI/deploy for merge SHA `4c6fab2` failed because Ruff reported `I001` on `bot/services/media_input_utils.py`; Mini App production revision therefore remained on `6351c20`.
- Additional root causes found: Motion Control uploads still built public URLs from `WEBHOOK_HOST`; legacy local result URLs were recognized only when already on the configured origin; valid legacy references could still be handed to providers with the old hostname.
- Follow-up branch: `fix/media-public-origin-neironych-followup`. Motion Control now uses `config.static_base_url`; local `/uploads/*` URLs are canonicalized onto the configured media origin while unrelated external URLs remain untouched; legacy local result URLs are rebased instead of leaking the old hostname.
- Production database read-only audit: legacy `tanyapi.chillcreative.ru/uploads/` strings remain primarily inside historical `generation_tasks.request_data` (283166 rows at audit time) and four prompt rows. No destructive bulk rewrite is used; runtime canonicalization preserves historical compatibility and new writes use the canonical origin.
- Genjutsu uses one public base for signed media and provider callbacks. Because production `GENJUTSU_PUBLIC_BASE_URL` now points at the Mini App/media origin, Nginx on `tanyapp.xn--e1aikcel5c5a.online` was extended with a signed `/genjutsu/` reverse-proxy path to backend port 1888. `nginx -t` passed and Nginx reloaded; invalid signed-media probe returns the same 403 on old and new domains, and a ranged `/uploads/` probe on the new origin returns HTTP 206 with 1024 bytes.
- Focused backend verification after follow-up changes: 88 passed, 1 skipped across config, durable-result, Seedream reference transport, saved-reference and trend API suites. Mini App: 216/216 Jest tests passed; ESLint passed; production static build passed.
- Full safe backend regression suite started after focused verification; final CI/deploy acceptance still pending.

- Follow-up TDD uncovered one more runtime override: `seedance_multimodal_compat` replaces `generation._seedance_media_inputs` at import time, so canonicalization in the generic generation helper alone was insufficient. Its reference cleaner now canonicalizes legacy local image/video URLs before runtime/provider use.
- Canonicalization is also enforced in ordinary Mini App media lists, Seedance 2.0, Seedance 2.5, first/last frames, and shared video-reference normalization. External non-local URLs remain unchanged.
- Clean-checkout-equivalent safe suite was run using only Git-tracked tests (local ignored historical tests excluded, matching GitHub CI checkout): `2056 passed, 45 skipped`. Focused media/Seedance/private-repeat tests also passed. The earlier 6-failure local run included ignored historical tests that are not present in the GitHub checkout; only the tracked Seedance regression was relevant and was fixed before the green run.


## 2026-10-07 — media migration reconciliation

- Imported the existing follow-up patch into an isolated worktree at `ac9365d`; preserved the original tracked diff and separated runtime `data/price.json`. No production checkout reset, price change, or untracked receipt cleanup was performed.
- Added a failing regression for alternate frontend upload origins, then canonicalized the already supported CDN and legacy Mini App origins at the backend boundary. Frontend display stays same-origin; provider references are normalized to configured `STATIC_BASE_URL` regardless of the supported frontend entry point. External hosts and non-upload paths remain unchanged.
- Read-only live checks: Mini App and its public `icon.svg` return HTTPS 200 with successful certificate validation; DNS resolves to 144.76.188.75. The live nginx file already proxies `/genjutsu/`; unsigned synthetic media IDs return 403 on old and new domains. No user media or signed credentials were fetched.
- Live selected public configuration: static and Genjutsu origins use the new Mini App host; webhook origin stays on the old backend host. These observations do not prove deployment of this isolated source change.
- Historical database links are retained; canonicalization is applied at runtime rather than destructive bulk rewriting. Production deployment and final exact-SHA smoke remain owned by the coordinated release task.
- Provisioning drift regression: the repository frontend installer omitted the existing live `/genjutsu/` route. Added the same reverse-proxy location to both generated server variants, with a failing-then-passing contract test and synthetic signed-media/callback URL-builder verification. The installer was not executed and live nginx was not changed.

## 2026-10-07 — hidden repeat prompt boundary

- Baseline: `ac9365d96459a3932c4a934600cc071a2ccec63b` on `tanyapi`; isolated task branch `fix/hidden-repeat-prompt-20261007`.
- Goal: hidden source recipes must not reappear in repeat fields, even from contradictory stale cards. Preserve ordinary visible owner prompts and user-authored additional instructions.
- Preflight: generic video and Seedance identity forms ignored `promptHidden`; feed/profile/deep-link callers supplied it. Image repeat already cleared source text. Server task, publication and Telegram predicates diverged.
- Regression-first: three frontend suites produced 7 failing synthetic privacy cases before the fix; ordinary controls passed. Backend API/card/FSM tests reproduced the separate stored-marker and direct bootstrap gaps. No live account data or actual recipe text was fetched.
- Frontend implementation: one repeat-preset normalizer combines card/detail privacy denials, then both video forms enforce it again on preset consumption. All three video-repeat entry points share hydration.
- Backend: shared intrinsic private-recipe classification for task APIs, Feed/Profile cards and both Telegram repeat callbacks; direct bootstrap now sanitizes history. JSON request snapshots and malformed explicit privacy markers fail closed. Focused 147 tests and broader database/trend/Genjutsu compatibility 388 tests passed, including 33 new API/card/FSM cases. compileall passed.
- Verification completed: static export build, `tsc --noEmit`, full Jest 35 suites / 224 tests; new mocked browser E2E covers Feed/Profile/deep-link, reopening and visible-owner control at 360px and 430px. Full frontend lint and existing critical browser aggregate also passed. Initial aggregate attempt lacked the required `.e2e-server` fixture; rerun after the CI preparation passed. Changed-line Ruff and final commit verification are recorded in the handoff.
- Existing playbooks used: evidence-first `Bambale0/skills` diagnosing-bugs, architecture/privacy/release discipline from `Bambale0/claw`, and isolated Playwright approach from `anthropics/skills` webapp-testing. No external playbook clones were modified.
- No schema migration, mutable pricing/provider configuration, generation submission or production checkout mutation. Only synthetic API/media fixtures are used in browser tests; external requests are denied.
- Release: local commit handoff to the single coordinated release owner; no independent push, merge or deployment. Exact deployed SHA/production smoke remain unverified.


## 2026-10-07 — Coordinated Tanya completion release

- Single integration branch starts at ac9365d and preserves the already merged promo
  database-clock fixes. Production still requires reconciliation of the captured domain
  patch before any deployment retry; runtime price and untracked receipts are preserved.
- Integrated domain commits94d28be/9a97ead, private-repeat commit36dec6e, optional Start/Skip
  packagef43f326. Code merged automatically; append-only ledger conflicts retain both sides.
- Source verification: domain2054 safe tests plus30 config/routing tests; privacy147 focused
  backend +388 broader,224 frontend tests and mobile/privacy/critical E2E passed; optional2079
  safe backend,243 frontend, TypeScript/lint/build, four-width offer flows, eight media
  targets and final critical E2E passed (job5b0404fa6e50, exit0).
- Integrated full backend/frontend/build/E2E, PostgreSQL regression and independent
  integration review remain the next gate before publication and serial release.
- No new Nginx runtime writes, provider generations, mass broadcasts or extra admin test
  content are part of this integration. Previously approved synthetic smoke is retained.

- Final integrated backend passed 2,121 tests / 66 skipped on caf53145; 47 isolated PostgreSQL campaign tests passed. All backend source, Python tests, dependency and configuration inputs remained identical after the final frontend-only fix. A redundant repeat full-backend invocation was cancelled and was not retried; the existing complete result remains applicable.
- Integrated frontend passed all 251 tests, TypeScript, lint and export. Independent review reproduced a Genjutsu/optional-offer modal collision; explicit open-state coordination fixes direct-query, startapp, prompt-linked and no-preview recipe entry without discarding drafts. Four regression scenarios passed after a fresh build. Required CI now runs all five browser suites; redundant extra checks were removed from the separate optional workflow.
- The task-owned isolated PostgreSQL container was stopped after verification; its data and all source/test artifacts are retained. No production messages, configuration or runtime checkout changes were made during integration.
- Final aggregate job_4836411f0b73 succeeded (347.6 seconds): 251 Jest tests and all five browser suites, including four Genjutsu entry regressions. Independent review has no remaining source blockers. Changed-line Ruff found zero relevant violations across 18 Python files. Production rollout and the bounded real Telegram test remain the subsequent verification step.
- PR #269 follow-up review identified the documented historical media.chillcreative.ru upload origin. Added only that exact compatibility alias, canonical/local-path/lookalike-host regressions, durable-result coverage and corrected the remaining current-topology documentation. Final full safe suite on 6858b2d passed 2,122 tests / 66 skipped (112.47 seconds); 82 focused domain tests also passed.
- Required CI exposed an E2E waiter race: an unrelated prior bootstrap response was selected during the 430px focus case. A deterministic delayed-response fixture reproduced the exact failure before the test-only correction. The waiter now follows the new marked capability request and its own response; server flag, real dialog closure, draft/referral and timeout assertions remain unchanged. All four widths passed (90.9 seconds), with no product-code change. Independent re-review found no remaining concern.


## 2026-10-07 — repeat reference integrity hotfix

- Baseline: `2fe684f78c4236ac98bfce9ef1e5fe3eabb6d952` (`tanyapi`, merged PR269); isolated `fix/repeat-reference-integrity-20261007`. Production is deliberately untouched by this task.
- User outcome: keep every authorized fixed reference in its numbered slot, or reject an incomplete recipe before billing/provider submission. Hidden display remains distinct from private reuse consent.
- Reproductions: four video wrapper cases silently dropped fixed Image3/Video3 with insufficient replacements; image `generate-image` lost the owner's selected fixed input and rejected explicit all-fixed recipes while `feed/remix` worked (four cases/two models). Another four photo cases showed owner ImageN slots could shift when a replacement was missing.
- Changes: unify image source assembly between APIs; validate input sufficiency after private recipe merge; preserve original ImageN positions for owner's selected refs. Video restoration rejects incomplete/unavailable/unreadable recipes rather than delegating a partial request.
- Domain boundary: compare known local upload identities across canonical/legacy origins; a source alias is never a new viewer-owned input. Unknown external origins remain distinct; visibility selections do not create private grants.
- Tests use synthetic URLs/assets and mocked billing/providers only. Full API/frame/order/permission and safe-suite results recorded in handoff. No real user recipe, media, generation or publication was accessed.
- No schema or mutable configuration change. Frontend unchanged. Rollout uses the single release coordinator; no independent deployment. Existing diagnosing-bugs, TDD and privacy/release guidance reused.

## 2026-10-07 — coordinated repeat-reference release

- Integrated the exact reviewed backend tree eedd8022 onto merged #269 (2fe684f). Full safe backend: 2,195 passed / 66 skipped; changed-line Ruff, compileall and independent review passed. Existing consent remains authoritative; no generic private-video grant was introduced.
- End-to-end acceptance review found a client-side blocker for all-fixed source repeats on Seedream Edit and Grok Image-to-Image. The image form now delegates source-recipe completeness to the existing backend boundary while standalone edit generation still requires its local upload.
- A rejected submission previously cleared source ID, prompt and references. Explicit accepted-submission results now preserve fully rejected drafts for correction; partial accepted batches retain accepted tasks/balance, report their accepted count and reset to avoid replay. No automatic retries were added.
- Regression-first frontend verification: both edit-model disabled-button failures and rejected-draft/partial-batch failures reproduced before the repair. Seventeen focused tests across four suites pass, including actual picker correction and manual retry with the original source ID and ordered references. Standard lint and TypeScript pass; final aggregate frontend/build result follows.
- Production remains on image/frontend 6351c208. Deployment of #269 was explicitly cancelled before SSH cutover; no new paid generations, audience broadcasts or admin tests were launched during this repair.
- Final frontend aggregate succeeded: 262 tests / 37 suites, TypeScript, standard ESLint and production export (job_232ca31b4063, 43.55 seconds). Independent frontend re-review confirms rejection recovery and partial-batch handling are fixed. Backend source/test inputs remain exactly the reviewed eedd8022 tree. No real provider or Telegram requests were used in these tests.


## 2026-10-07 — PR270 review follow-ups

- Baseline: `48766372ab33c1094d3b31eea35b29d2832277ab`; isolated `fix/repeat-review-followups-20261007`. Production remains owned by the release coordinator.
- Independently reproduced all four review reports with synthetic data: obsolete generic frame alias blocks a valid replacement; explicit complete identity inputs blocked by unused source snapshot; Telegram authorized alias rejected by raw subset checks; identity-keyed map moves an exact selected occurrence to another ImageN slot.
- Scope: validate only active/inherited video inputs; preserve identity-form explicit lists while validating omitted source-dependent types; exact stored URL wins before unique known-origin alias resolution; reject ambiguous slot aliasing; align central Telegram launch metadata to actual input URLs and preserve private redaction. No new reuse permissions.
- Before fix: six video regressions failed with five controls passing, four image/Telegram regressions failed with three controls passing. Targeted and full final results recorded in release handoff.
- No schema, frontend, grant backfill, production metadata/media, paid generation or external messaging changes. All provider/debit tests are mocked.


## 2026-10-07 — preserve admin prices during standard deployment

- Baseline: `48766372ab33c1094d3b31eea35b29d2832277ab`, isolated branch `fix/preserve-runtime-admin-prices-20261007`; production checkout/runtime remain outside this source-only task.
- Preflight: reliable SSH plus standard fallback SSH/local replaced existing admin prices when defaults changed or contained `force_apply_runtime_price=true`. Existing static tests encoded that behavior. Standard backend/frontend scripts do not reset source or publish tariffs; dated legacy hotfix workflows remain outside this bounded fix.
- Contract: standard deployment never writes an existing runtime `data/price.json`, including concurrent admin saves. Missing runtime is seeded only with an atomic create-if-absent. No tariff values, provider/payment code, security settings, schema, CI gates or timeout budgets change.
- Real Git experiments proved excluded-path `git restore --worktree` plus index-only `git reset --mixed --no-refresh`: source additions/deletions/renames update; HEAD/index match the target; runtime bytes remain untouched. Experiments also exposed a parent-path collision: a target file replacing `data/` can defeat child exclusion. The workflow rejects that target tree before any source writes.
- Implementation: require the checkout already be on `tanyapi`; reject invalid runtime JSON/non-object/file types and incompatible target path shapes; save a validated read-only recovery snapshot; always exclude the runtime path from source restoration; update HEAD/index without worktree reset. Exit traps retain backups on failure and never copy stale snapshots over later admin edits.
- First install: prepare the exact commit default in the same directory, validate it, then atomically hard-link it into place without replacement. An admin file created after the existence check wins. Existing file inode and permissions remain unchanged by checkout.
- Regression evidence: original force/default behavior produced 27 failures / 6 passing controls. The initial snapshot/restore fix still failed 15 stronger cases covering concurrent writes, forbidden copy-back, first-install races and branch switching; it was superseded before publication.
- Final verification: 91 related pytest checks passed with standard project conftest in 10.18 seconds. Coverage executes the actual workflow shell against temporary local Git repositories: force flag unchanged/changed; changed/removed defaults; clean/dirty runtime; malformed/non-object runtime; isolated admin writes before source restore and index reset; first-install seed race; source deletion/rename/addition; exact HEAD/index; inode/permissions; partial backup failure; source/index failures; later admin edits; unrelated tracked drift; parent-path collisions and wrong checked-out branch.
- Checks: Ruff passes for both changed Python test files; both YAML workflows parse; all 18 run blocks pass `bash -n`; standard backend/frontend/backup/cdn shell syntax and `git diff --check` pass. No Docker, provider, Telegram, payment or live configuration is used by the regression seam. Full app/frontend suites are not repeated for workflow-only behavior.
- Review: independent review caught a removed fallback `actual_sha` assignment; executing its actual success line reproduced four failures, and the assignment was restored. A subsequent reviewer source read was user-cancelled; no retry or alternate review route was used. Independent re-review of the stronger final implementation remains on hold for coordinator authorization.
- Failure boundary: interrupted source restoration may leave a partial source checkout, so deployment stops before service/build steps and may require checkout reconciliation before retry. Runtime prices are never restored from the old snapshot. Dated one-shot hotfix workflows remain unchanged and outside this standard-release guarantee.
- Playbooks: existing Bambale0/skills diagnosing-bugs and TDD; Bambale0/claw release-hardening; anthropics/skills webapp-testing inspected (browser QA is inapplicable to shell-only behavior). External playbook clones remain unchanged.
- Delivery: local commit only, handed to the single release coordinator. No production checkout, actual tariff, service, configuration, admin message, payment, deployment, push or PR was changed. Exact-SHA CI and production verification remain release-owner work.


## 2026-10-08 — explicit private video repeat references

- Baseline: `f5b3888da7d541ea970c37fe2c911899208f66c4` on `tanyapi`. Existing isolated branch `fix/video-repeat-reference-permission-20261008` contained a partial unpublished patch; user explicitly consolidated and authorized completing that work here. Existing edits are preserved.
- User outcome: authors of video works can choose typed references retained privately for repeats; repeat users can identify and upload their replacement slots without receiving private source URLs or hidden prompts.
- Preflight: PR239 originally added image-only private reuse consent; generic video still depended on public-display selection. PR243 withheld source media URLs from foreign cards. Author permission UI and API were partially expanded in the inherited patch, but consumer slot descriptors and complete authorization checks were missing.
- Scope: reuse the existing publication JSON grant and video recipe pipeline; distinguish legacy absent/image-only metadata from explicit typed video consent, empty revocation and invalid metadata. No grant backfill, source-media migration or new provider behavior.
- Contract in implementation: optional versioned, URL-free typed slot descriptors; fixed references stay server-side, upload slots keep original ordering and frame roles. Current source permissions and mandatory input availability must be checked before billing/provider calls. Preserve ordinary owner editing and existing photo/Trend/Genjutsu behavior.
- Verification plan: synthetic publication/API/continuity/debit regressions; typed ordering, frames, explicit empty/revocation, malformed metadata, foreign/owner, stale descriptors, legacy records and missing files; frontend author selection plus replacement forms and browser entry paths. No real generation, user media/prompt reads or external messages.
- Guidance: existing Bambale0/skills diagnosing-bugs and code-review; Bambale0/claw privacy/API/release QA; anthropics/skills webapp-testing. Existing playbook clones are read only.
- Configuration/schema: no new DB column or tariff changes intended; production `price.json` is outside this source task.
- Release: prepare tested draft PR only; merge/deployment requires the release decision and exact-head CI. No production state claim.
- Status: backend and frontend completion in progress; independent review and final checks pending.

- Regression evidence: a clean baseline component failed the new video-author permission test (missing group); the consumer initially allowed launch with required typed upload slots empty. Both regressions now pass. Pre-existing dirty patch also broke image owner-detail shape; the image-only contract is preserved.
- Frontend candidate verification: 37 Jest suites / 272 tests, TypeScript, ESLint and production static export pass. New browser scenarios pass at 320/390/430px for author selection/revocation, Feed/Profile/deep-link, ordered uploads, all-fixed recipes, source-bound model/scenario, unavailable recipes and rejected API draft retention. Existing critical browser aggregate passed in 192.05 seconds, including photo permissions, Genjutsu, Seedance uploads and identity entry/exit/navigation. Twelve frontend/CI files are frozen by hash.
- Cancellation recovery: execution paused after a cancelled isolated patch/test and status read. Fresh user confirmation allowed one exact status retry, which established that the cancelled edits had not landed; only missing changes were then applied. No production mutation occurred.
- Backend intermediate verification: 188 focused tests pass, including six generic/Seedance handler races that revoke consent, unpublish or change the source recipe during affordability checks; billing/provider calls stay untouched. Final negative matrix, safe suite and review remain pending.
- Compatibility boundary: the new versioned private contract covers image/video slots. Source audio is never implicitly granted; unsupported private-audio recipes receive a safe validation error. Existing owner and legacy paths remain separate. No automatic conversion/backfill of historical author selections.

- Backend candidate frozen: typed source plans preserve active image/video order and first/last frame roles, require exact replacement counts, validate ownership and reject ambiguous source aliases. New foreign typed recipes bind to their source model/scenario; owner repeats retain their editable legacy form. Withdrawal preserves an explicit versioned empty marker so an older client cannot revive revoked access.
- Final focused matrix: 30 new API cases cover malformed/forged consent, first/last frames, image-only multimodal snapshots, current permissions, file loss during affordability await and old-client republication. Telegram callback regression first reproduced 11 failures with one control, then all 12 passed. Selected combined suite passed 173 tests. Full safe suite and independent review are pending.
- Telegram consistency: newly created typed-repeat children carry only a contract-version marker alongside their existing source identity. Generic, advanced-video and Seedance result-repeat buttons route these new recipes to the same source Mini App replacement flow before any billing. Withdrawn source publications refuse the repeat; ordinary owner and legacy callbacks are unchanged. No private media or prompt is included in the redirect.

- Final verification: full safe backend suite passed 2,371 tests / 66 skipped in 137.32 seconds (379 existing warnings), with all 12 frozen backend source/test hashes verified afterward. Changed-line Ruff reports zero violations; changed-file syntax and diff checks pass. Frontend remains the exact verified 272-test/export/browser manifest.
- Independent review found and reproduced an inter-read withdrawal race plus a legacy-to-typed transition gap; both are closed by checking current authoritative source publication/status and consent snapshots before charging. Public typed scenario now uses the same stored-recipe inference as reconstruction. Canonical duplicate list slots that downstream providers would collapse are rejected; equal first/last scalar frames remain supported. Typed-context provider failures are sanitized before returning errors. Final focused suite: 280 passed.
- Release status: tested candidate prepared for a draft PR to `tanyapi`; merge/deployment await the user's release decision. No production checkout, prices, database records, media, generation or external message changed during this task.


## 2026-10-08 — Seedance admin dashboard reference routing

- Baseline: b07ab430de2b354a134ea4ef451be30dfcb2ba8d, branch fix/seedance-admin-routing-20261008
- Symptom: photo after choosing Seedance Reference mode opens NanoBanana quick creation.
- Evidence: open/Done callbacks set None; mode selector changes data only. Generation router runs first and its idle StateFilter correctly accepts None, clearing the Seedance data.
- Regression: offline extraction executes real callbacks and real aiogram filters without application/config/database imports. Baseline fails on the actual idle interception; fix passes eight tests, including ordered router propagation, repeat dashboard returns, mode switching, non-admin guard and unchanged idle shortcut.
- Changes: dedicated dashboard state; dashboard media delegates to existing refs/edit/frames validation; text mode gives instructions; admin test access allowlist includes dashboard. No provider/billing/data model/config/migration changes. Mini App uses separate HTTP routes and is unaffected.
- Checks: eight isolated routing tests PASS; six existing source-contract tests PASS; syntax compilation of changed Python PASS; focused Ruff PASS; diff whitespace PASS.
- Constraints: no paid generation, real Telegram sends, database access, credentials reads, or production edits. Full application tests and deployed smoke not run in this isolated diagnosis; coordinated release owner handles aggregate CI and deployment verification.
- Rollout/rollback: ordinary reviewed task PR to tanyapi under release owner; revert the scoped commit if needed. No runtime data migration.
- Playbooks: Bambale0/skills diagnosing-bugs (red-first evidence), Bambale0/claw architecture/FSM consistency, anthropics webapp-testing reviewed (browser-only workflow not applicable to Telegram handler regression).

## 2026-10-08 — Feed clipboard recovery

- Baseline: tanyapi b07ab430de2b354a134ea4ef451be30dfcb2ba8d. Isolated fix/feed-copy-fallback-20261008 worktree; production dirty data remains untouched.
- Audit: Feed awaits share API before Clipboard API and execCommand fallback. Both failures previously discarded the usable server URL and showed a generic red banner. Success did not clear stale errors.
- Outcome: retain the exact server link in a selectable mobile-width field; fresh-gesture copy retry without another share request, one-tap success feedback and separate API/clipboard failure handling. Request sequence protects against stale completions and unmount.
- No API/schema/configuration/pricing changes; no private prompt/reference exposure or URL reconstruction. No paid generation or external messaging.
- Regression: all four new component tests failed against baseline, then passed after implementation. Full frontend suite: 311 tests passed. Typecheck, lint, static export, mobile-width browser fixture and independent review pending.
- Browser coverage adds clipboard rejection plus failed execCommand, exact deep/referral link preservation, successful fresh click, single API request and 320/360/390/430 width constraints.
- Guidance: Bambale0/skills diagnosing-bugs, Bambale0/claw debugger, anthropics/skills webapp-testing. Real Telegram/iOS device behavior remains unverified.
- Rollout: parent coordinates one release after combined checks; no deployment performed by this branch.
- Final verified revision: 42 Jest suites / 311 tests, TypeScript, ESLint and production static export passed; synthetic Chromium mobile E2E passed at 320/360/390/430px. The lower-card test confirms recovery enters the viewport without locator auto-scrolling. Full check chain job_838ca54a2078 succeeded.
- Independent review identified off-screen recovery after sharing a lower card; failure-only scroll into view plus a lower-card regression addressed it. Reviewer independently verified final hashes and found no remaining code blocker. Clipboard refusal is simulated; no physical iOS device was tested.

## Seedance creator tariff (2026-10-09, implementation in progress)

- Baseline: tanyapi `12a747e0e8f940351ed060bbdb2ffb69aa6a5bfc`; isolated safe source snapshot, denied credential-bearing source excluded. Existing live checkout untouched.
- Goal: Tanya assigns/revokes separate pricing membership by Telegram ID and configures independent Seedance 2.0 / 2.5 prices in admin. Membership never grants admin access.
- Audit: ordinary pricing is live `data/price.json`; 2.0 base/duration costs; 2.5 quality rates per second, current UI supports480p/720p, runtime has1080p configuration too. Preserve all configured quality keys and existing ×2 video-reference charge. Provider models, capabilities and ordinary economics unchanged.
- Existing gap: Mini App launch recalculates stored price after provider response; replace with one immutable server quote captured before debit and supplied to persistence. Refund uses original charged amount.
- Configuration: optional `creator_tariff` section in existing price store, disabled/unconfigured when absent. No numeric creator defaults, no live rates changed, no real memberships assigned. Enable requires valid complete model/quality rates. Ordinary fallback explicit in admin.
- Migration: additive independent membership + append-only audit tables, idempotent SQLite/PostgreSQL-compatible startup schema. No deployment or production migration is authorized in this task.
- Security: authenticated actor only, server admin checks on every configuration/membership mutation, positive Telegram IDs, existing target users, no client tariff selection, no global per-user price caches.
- Steps: (1) pricing domain/config validation; (2) DB/admin controls; (3) bot/Mini App/trend/repeat quote integration; (4) viewer-scoped display metadata; (5) regression, type/build, review; (6) report patch, unresolved verification limits. Publish/merge/deploy require separate approval.
- Tests: isolated disposable SQLite and fake providers only. No paid/live tests, production SQL, credentials, real grants or customer messages. Python dependency environment isolated under this snapshot.
- Playbooks: read repository AGENTS + local test-driven-development guidance; consulted Bambale0/skills README (TDD source paths unavailable), Bambale0/claw review checklist, anthropics/skills webapp-testing. Tests written before implementation; initial test run was blocked by missing dependencies, not an observed behavioral failure. Regression sensitivity will be checked explicitly.
- Progress: pricing service covers independent model/quality rates, aliases, stable ordinary/admin-free precedence, zero/nonfinite validation, preserved reference multiplier, immutable revision-tagged quotes. First focused run: 15 passed.
- Implemented: DB membership/audit + Telegram admin editor; validated independent per-model/per-quality rates; authenticated viewer metadata; unified Seedance quote capture in Telegram, Mini App, repeats and trends; original-charge refund precedence.
- Independent review found and resolved post-provider-acceptance UI/refund races, nested repeat double-refund propagation and bot-message-vs-actor display identity. Regression tests now exercise accepted/persisted jobs with failed notifications/FSM cleanup and a subsequent single asynchronous refund, plus grant/revoke/rate changes during provider waits.
- Focused integration verification after fixes: 457 passed (59 existing warnings). New pricing rates also reject non-finite, zero/negative, too-small-to-round-positive and overflow-at-long-duration values. Adjacent ordinary-model repeat economics remain historical as before; actor-aware repeat repricing is restricted to the requested Seedance models.
- Frontend: 43 focused Jest tests, TypeScript noEmit, changed-file ESLint and production build/static export passed. Browser E2E never reached a scenario: Chromium archive download invalid; existing Chromium launch denied sandbox socket access. No restriction bypass attempted.
- Full-suite attempt cannot collect PostgreSQL-pool-dependent tests because the credential-bearing pool source is intentionally absent. Initial collection errors: test_genjutsu_postgres, test_promo_campaigns_postgres, test_result_durability_postgres, test_runtime72_postgres_refunds, test_runtime_reliability_contract, test_video_repeat_receipts_postgres. Excluded test_postgres_connection_pool_contract for the same denied source.
- Supported-suite command excludes `tests/*postgres*`, `tests/test_runtime_reliability_contract.py`, `tests/test_runtime72_saved_references.py` (three cases import the absent PostgreSQL pool), and `tests/test_public_offer_contract.py` (public offer PDF intentionally not materialized in safe source snapshot), plus all paid/live tests. An intermediate run passed2608 with only snapshot-environment failures; subsequent run exposed an old mocked pricing import, updated to exercise the real shared reference-multiplier path.
- PostgreSQL startup DDL routing is verified against the real allowed PostgresConnection adapter with a fake raw connection; a live ephemeral PostgreSQL migration run remains unverified. Independent read-only review reports no remaining code blocker conditional on the final supported-suite rerun. No publication, merge, deploy, real assignment, live configuration write or paid generation performed.
- Final supported-suite result on reviewed sources: **2648 passed, 1 skipped, 12 subtests passed**, 393 existing warnings, 140.30s. Exact command: `.venv/bin/python -m pytest tests/ --ignore=tests/live --ignore-glob='tests/*postgres*' --ignore=tests/test_runtime_reliability_contract.py --ignore=tests/test_runtime72_saved_references.py --ignore=tests/test_public_offer_contract.py -m 'not live_smoke' -q --tb=short`.
- Final static checks: changed-line Ruff passed all34 touched Python files; full Ruff passed new pricing/admin/membership/display modules and all new tests; compilation, dependency consistency and `git diff --check` passed. Patch applies cleanly to the isolated safe baseline. `data/price.json` unchanged byte-for-byte, SHA256 `65405b135cfc204b195ce8335f0da332f1a1e079b8f8c312ac7f517922036b79`.
- Delivery: reviewable patch only, no publication commit or PR. Workspace branch is based on a synthetic safe snapshot of the stated tanyapi SHA; apply the patch to an authorized real task branch before future publication. Full CI, live PostgreSQL migration and browser E2E are release gates still requiring a suitable environment. No additional code changes after the final passing test run.

### Creator tariff release verification (2026-10-09)

- Creator-only publication/merge was approved. Draft PR275 starts directly from `12a747e0e8f940351ed060bbdb2ffb69aa6a5bfc`; separate referral work is excluded.
- Added an explicitly disposable PostgreSQL16 CI service. Its15 acceptance cases verify both schema bootstrap paths, concurrent membership mutation, atomic/immutable audit, fractional quote retention, role/rate changes and exactly-once refund races. All15 plus11 fixture-safety checks passed at `52c4d0a`.
- Initial published head passed the normal full safe Python suite and existing runtime PostgreSQL suite, closing the local materialization gaps; final-head CI remains mandatory.
- Added creator browser journeys to the required main CI browser gate: distinct viewer/model prices, server half-step totals, quality/duration changes, reference factor once and no client tariff fields. No external provider or paid request is used.
- This revealed a pre-existing normal Seedance2 reference-price UI mismatch. A focused red/green regression and independently reviewed fix now follow actual submitted references, including multiple refs and scenario changes. The authoritative repeat descriptor still wins.
- The separate npm-audit gate found critical advisories against baseline test-only Handlebars4.7.9. Updated only its lockfile entry to official4.7.10 (compatible with ts-jest's existing range); no advisory suppression or gate weakening. `npm audit --audit-level=high` passes;20 moderate transitive test-dependency advisories remain. Official advisory: https://github.com/advisories/GHSA-8r5x-fm3f-whwj.
- Full frontend Jest:43 suites /313 tests passed after the dependency patch. Release remains gated on exact-head CI/browser/Docker, then exact deployed SHA and read-only smoke. Existing runtime prices and dirty/untracked files must be preserved by normal deployment.

## Clickable feed share-link action — 2026-10-09

- Fresh baseline: `tanyapi` at `45add2bd9e6a73b684cc55f73a75b5ea11cac4a9`. Isolated fix branch; held referral work is excluded.
- Screenshot/current-code audit: Feed share recovery rendered a read-only selectable input and Copy button, but no navigable link. The server-generated share URL and existing `start`/`startapp` selection are intentional and must remain byte-identical.
- Add accessible «Открыть ссылку» anchor beside Copy. A synchronous user click uses the same Telegram WebApp navigation pattern as the bot-start gate for `t.me`. Missing/throwing bridge and other HTTP(S) URLs use the native `_blank` anchor with `noopener noreferrer`; modified clicks retain browser semantics.
- Validate executable URLs without rewriting them; unsafe schemes, credential-bearing, relative, control-character and backslash URLs receive no anchor. Selectable input, automatic copy, direct Copy retry and failure feedback remain intact.
- No backend, provider, schema, pricing, referral policy, deep-link builder or generation changes. Browser fixtures intercept every API/destination and prohibit paid calls. Dedicated PR workflow covers Android/Chromium and iOS/WebKit emulation, not real-device Telegram certification.
- Regression-first: six new opening/fallback cases failed on baseline; all existing copy/manual-recovery cases continued to pass. Final unit/type/lint/build and independent review evidence follows. Publication/merge/deploy require separate approval for this fix.
- Guidance: repository AGENTS, Bambale0/skills README (specific TDD file unavailable), Bambale0/claw engineering workflow, and anthropics/skills webapp-testing.
- Local final checks: 15 focused share cases and 324 frontend tests across 43 suites passed; TypeScript, full ESLint, production static build, script syntax and diff checks passed. Official Playwright browser download failed with a truncated ZIP, so Android/iOS emulation has not run locally. The dedicated PR gate must pass before release; no browser security/sandbox bypass was attempted.
- Independent read-only review found no blocking application defect and verified the bundled SDK skips `_blank` anchors, avoiding double dispatch. Its test-hardening suggestion is applied: unrecognized API routes/actions are aborted and fail the emulation assertions rather than receiving an implicit success response. Browser execution remains pending.

## 2026-10-09 — Explicit feed links use the authenticated sharer

- Baseline: remote `45add2bd9e6a73b684cc55f73a75b5ea11cac4a9`; refreshed to `90e39dd7bac63b408fd2d064b142c8f734fe0ab0` after independent clickable-link PR #276. Safe local snapshot overlays that exact six-file PR. Backend source blobs unchanged by #276; Open UI preserved.
- Repro: signed HTTP Feed share by a different user returned the source author's code. Telegram CopyText/bfs matched that behavior. Prompt-template sharing already used the authenticated sharer.
- Scope: new explicit share-link issuance only. Reuse validated Mini App context, existing persisted user code, builders and referral parser. Never overwrite source author/card or `source_feed_gen_id`; no referral remapping, economics, payment, schema, migration, provider or config changes.
- Tests first: signed HTTP regression RED → source fix GREEN; Telegram callbacks/keyboards RED → per-sharer fix; shared-chat review found negative chat-ID risk, resolved with per-click callback instead of static CopyText; profile-only callback regression RED → existing visibility-aware increment service.
- Security: body spoof fields ignored; invalid signatures rejected before share count; no-code fallback stays plain; no-store preserved; hidden/withdrawn cards rejected. Shared caches retain author identity only.
- Observability: existing share log contains actor Telegram ID and source card ID. No extra secrets, initData, prompts or media logging.
- Skills: Bambale0/skills diagnosing-bugs + tdd (HTTP/callback/public service seams), Bambale0/claw architecture/release discipline, anthropics/skills webapp-testing guidance. Browser UI code unchanged; existing frontend clipboard tests remain applicable.
- Runtime diagnostic was cancelled. No retry or alternative live lookup; reported username/code ownership remains unverified. No production mutations, generation requests or paid tests.
- Verified: 21 new attribution cases; 203 focused backend tests; 324 frontend tests across 43 suites (including 21 clipboard/API tests); Python syntax and diff whitespace; changed-line Ruff 0 new violations (100 legacy diagnostics ignored by the normal gate). Independent review has no remaining blocker.
- All five modified pre-existing files have base blob hashes identical to real `90e39dd7`; the two remaining files are new. Full safe collection is blocked by seven PostgreSQL/runtime modules importing excluded `bot/postgres_pool.py`; no attempt to retrieve or recreate it. Broad run excluding those seven collection blockers: 2,687 passed, 18 skipped, 12 subtests passed; one failure is the absent unchanged legal/public-offer.pdf asset, and three fixture errors are additional PostgreSQL tests importing the same excluded module. No changed-feature failure was observed; this is not a full-suite pass. These missing sources were not retrieved or reconstructed.
- Publication/merge/deploy require separate approval; rollback would revert this isolated change, without data repair. Previously issued links/static Telegram CopyText buttons retain their embedded code; reopen/navigate to obtain rebuilt buttons.


## 2026-10-09: direct Seedance 2.5 character edit

- Baseline: `05199e7357a221e34c6afd5ab17e3b48f36ed4a6`; task branch `fix/seedance25-direct-edit`, isolated worktree. Production has unrelated runtime price changes; do not touch them.
- User approved the direct image + original video -> Seedance route, not LAS/Seedream/keyframe preprocessing or a provider migration.
- Current route already submits image/video arrays but prepends the long `apix-v1` prompt to all user instructions. Pure payload regression is reproducible; the cause of model-quality failure is NOT established.
- Preflight: AGENTS, README/current production layout, identity/service/public handlers, tests, APIX comparison from preceding audit, admin editable-instruction pattern and current KIE schema. Use diagnosing-bugs, Claw release discipline and webapp-testing guidance. No general refactor.
- Existing seams to preserve: owned local media validation, measured source duration, quote-before-debit, ordinary references, owner-only repeats, one provider submit/no identity auto-retry, callback reconciliation and delivery.
- New contract: direct-edit-v1; complete non-empty edit prompt is not wrapped; an empty instruction uses an admin-editable direct template. One to three same-person photos, exactly one original video. duration=-1/aspect_ratio=adaptive. Explicit edit field only for this route; KIE accepted/saved it in the earlier experiment, but upstream semantics remain unproven.
- Configuration: use audited bot_settings for the default edit template, with server-side admin command and validation. Freeze resolved provider prompt at pre-debit validation; do not read a different template after charge. Record revision/hash, not raw private prompts in logs. No DB migration, tariff/provider switch or new fees.
- Compatibility: keep public identity flags and original user prompt in task metadata/repeat data. Update UI/TG wording from additional wishes to a full optional edit instruction. Default still permits an empty instruction.
- Verification: provider contract, invalid/missing references, 1/2/3 order, full/empty prompt, admin settings, quote/launch snapshot, ordinary behavior, API/TG/repeats and frontend tests. Model quality requires separate visual acceptance and is not proven by mocked tests.
- RED: `python -m pytest -q tests/test_seedance25_direct_edit.py --disable-warnings --tb=short`: 4 failed / 1 passed. Existing prompt wrapper causes exact-prompt and direct-default assertions to fail.
- Rollout: focused tests -> appropriate regressions/frontend build/browser checks -> review -> PR to tanyapi with guarded native auto-merge -> exact SHA CI/deploy/health verification. Do not manually deploy or change production settings during implementation.
- Status: implementing; no production fix claimed, no new paid generation yet.

### Direct-edit implementation evidence

- Completed direct prompt composition, one-call KIE edit payload, frozen pre-debit prompt and hash, audited editable default/admin command, and aligned Telegram/Mini App wording. Short legacy wishes keep a concise replacement command; complete prompts naming both references are not wrapped.
- New regression file is explicitly unignored so CI receives it; no runtime diagnostics, media, secrets, build caches or unrelated production price files are part of the change.
- Focused backend: 197 passed before the final template-token edge case; original red provider assertions now pass. Full safe suite: 2,976 passed / 89 skipped / 12 subtests passed (174.10s). Final new token-boundary regression is included in the subsequent focused rerun.
- Frontend: 338 tests / 44 suites passed; ESLint, TypeScript no-emit and static production build passed. Browser aggregate is running separately.
- Review (self-review; no independent sub-agent available): standards axis uses existing audited bot_settings and admin authorization, no new billing/provider route; spec axis keeps direct image+original-video flow and ordinary behavior unchanged. Tightened template video-role token matching to reject suffix lookalikes. Existing PR #280 was inspected for overlap; no changes from it were copied or merged.
- Known limitation: these checks prove direct request composition, not model identity fidelity. The earlier KIE edit-field experiment succeeded but its visual result was not accepted by the user. No quality fix is claimed from HTTP status or unit tests.

- Final focused direct/identity rerun: 94 passed (2.64s), including the new `@Video1abc` rejection. New-module Ruff is clean; exact code-head changed-line gate reports 0 new findings / 22 unchanged legacy findings.
- Full mocked browser aggregate completed: critical flows; private reference permissions; feed/profile/deep-link repeats; Seedance uploads; identity paid/ordinary flows at 320/375/390/430px; missing/excess refs; source duration; insufficient balance; resolution requote; stale quote recovery and private repeat dismissal/navigation all passed. This is an isolated static build with mocked providers, not a real paid provider run.
- PR #281 targets tanyapi. Branch protection verified `strict=true` with Python/deploy, safe regression, Mini App browser E2E and production Docker gates. CI is running; production deployment is not yet claimed.

### Review follow-up and current-base verification
- Merged the released private-video-repeat prompt fix (#280, `23b52ad9c20ef3d78434d4da9322ea9f8e66cb29`) into this task branch without overwriting it. Combined-head full safe suite: 3075 passed, 89 skipped, 12 subtests passed.
- Read the automated Codex review and temporarily returned #281 to draft before release. Confirmed both P2 findings: compact `@img1` expansion could exceed the direct limit; the 8000-character template cap exceeded the text-only admin setter capacity.
- Regression-first reproduction: 3 failures / 4 passes on the new boundary tests before fixes. Final provider text is now checked against the 20480 direct cap after canonicalization; oversized requests fail before quote/debit/submission. Ordinary prompt behavior is unchanged.
- Restricted editable templates to 4096 characters and verified the full-size reply-to-message admin setter. This avoids adding an unnecessary document-upload surface.
- Focused combined direct/identity/private-repeat tests after review fixes: 199 passed. Identity/template module and new tests are Ruff-clean; diff whitespace check passed. Full exact-head CI must run again before release. No new paid provider task or production mutation in this follow-up.


## 2026-10-09 — Durable referral notifications and guarded delivery

- Initial diagnosis used deployed PR280 `23b52ad9c20ef3d78434d4da9322ea9f8e66cb29`; PR282 publication was based on PR281 `31d02d43dd0d2bb18904eea588ac90ea40e2fe1f`. Follow-up baseline is merged `482c424c971e86404666bc7dfc04010ba7923bc9`.
- PR279 suppressed both attachment notices and omitted the accepted-generation bonus receipt. PR282 adds a transactional, unique per-event outbox and reuses the existing safe snapshot sender. Financial terms, one-time qualification, prices and historical claims remain unchanged.
- PR282 passed all four required CI gates plus real PostgreSQL and independent review. Its exact-SHA deploy was cancelled before SSH after later review identified Mini-App-only recipient deferral and retry-claim budget gaps; no production success is claimed.
- Follow-up preserves queued receipts for known never_started recipients until private-chat lifecycle permits delivery, and counts durable send attempts rather than unstarted leases. Explicitly blocked/uncertain historical outcomes are not replayed.
- Retry policy and both templates use typed, validated existing bot_settings plus an authenticated admin read/set/reset command. Templates freeze at enqueue; lease/attempt policy freezes per claim. Invalid stored configuration falls back safely without raw payload/error logging.
- Existing registry stores last-editor/time metadata, not a new immutable audit history. No new schema beyond the original empty outbox, no live configuration changes, no paid generations, no real test messages and no historical backfill.
- New functional regressions reproduced 5 failures before correction; 114 offline notification tests now pass. Full current-base backend, real PostgreSQL, changed-line lint, independent review and exact-head GitHub gates remain mandatory before the corrected release.
- Detailed test evidence: [referral notification verification](REFERRAL_NOTIFICATIONS_20261009.md). Preserve all earlier ledger history; this is an appended entry only.

- PR283 review follow-up: six reproduced edge cases now pass. Editable templates reject code/pre overlaps after placeholder expansion. Existing schema startup adds nullable missing bot_settings audit columns idempotently, preserving legacy values without inventing historical audit metadata. Unit suite: 120 passed; new real PostgreSQL legacy-table test is required in updated-head CI. Repeated code/security reviews and exact-head CI remain release gates.

## 2026-10-10 - WAN post-#284 regression repair

- Baseline: `tanyapi` at deployed commit `6b1621b83bd7b7b1fe39a1cb3774ac49c0cf45e9`; isolated branch `fix/wan3-post-284-regressions`. Open PRs and remote branches were checked before editing; no overlapping current repair was found.
- Scope is limited to review discussions `r4237110298`, `r4237110295`, and `r4237110299`: multipart upload compatibility, late canonical results after provider-wait escalation, and visible optional-source restoration. Prices, referral terms, historical ledger entries, provider selection and schemas remain unchanged.
- Upload contract: `/wan3/upload/chunk` accepts the frontend's bounded `start_param_fallback` multipart field while retaining duplicate/unknown-field rejection and header-based signed authentication. Real multipart regressions cover image, video, audio and document chunks.
- Lifecycle contract: only `result_attention` rows carrying `provider_wait_timeout` remain eligible for canonical polling/callback leasing and success settlement. Invalid/missing/download-failed results retain their finite repair budget and operator-only queue. Settlement still claims `settled = 0`; replay cannot double-refund, double-charge, redeliver or create another paid provider task.
- Form contract: every owner or `initialRecipe` restore synchronizes `extraSource` from the saved document/link arrays. Tests cover visibility, removal, replacement, repeated link-to-document restoration and the actual quote recipe.
- Observability: existing timeout escalation, canonical polling, settlement and delivery logs remain the source of task/provider correlation; no new sensitive payload logging was added.
- Test plan: focused signed HTTP/multipart, timeout-late-result/delivery, callback authentication, bounded invalid-result/download repair, frontend form/API Jest, TypeScript, ESLint, production build, then exact-head CI and review. No paid generation or third-party message is permitted.
- Rollback: revert this isolated commit/PR. No migration or data repair is required. Merge and deployment remain explicitly out of scope until the parent verifies the draft PR head and gives the next release instruction.
- Local verification: 19 focused backend regressions passed; Python compilation and Ruff passed; full frontend Jest passed 49 suites / 355 tests; TypeScript passed; changed frontend ESLint had 0 errors and 2 pre-existing hook-dependency warnings; Windows-equivalent Next.js static production build passed. The repository's Unix-style `npm run build` wrapper cannot set `NEXT_EXPORT` under PowerShell, so the same locked Next command and post-build Telegram patch script were run explicitly. Exact-head GitHub CI remains required.


## 2026-10-10 - Bound WAN timeout polling and clear successful diagnostics

- Baseline: PR285 squash `b5d0ce427baad370ade9dc0b2ab4f37317810a2d`. Follow-up addresses review discussions r4237287138 (P1 unbounded attention polling) and r4237287141 (stale error metadata).
- Active submitted/unknown/settlement-pending work has precedence over attention backlog in each batch. Timeout attention remains automatically polled for a configurable 24-hour window after the normal provider pending limit, with age-based delay from 300 to 3600 seconds by default. Existing positive_setting configuration validation is reused. No production environment settings are changed.
- After that window the row remains operator-visible, unsettled, and eligible for authenticated callbacks or explicit canonical task reconciliation. The finite automatic window does not refund, drop, replace, or resubmit a task. Polling-only late results need explicit operator review. Invalid-result attention stays excluded.
- Successful settlement atomically clears obsolete error_code, error_message and next_attempt_at. Existing settled=0 transactional fences remain unchanged. Prices, referrals, historical financial records, schema, and paid provider POST paths are unchanged.
- Local checks: Python compilation passed; exact scheduler/lease/defer methods executed against synthetic in-memory SQLite with no application imports, covering active-first batch ordering, finite automatic window, explicit late canonical lookup, and three bounded backoff ages. This is not a full application integration-suite claim.
- Added application integration regressions for active priority, aged attention exclusion, preserved explicit reconciliation, configured backoff, signed callback beyond automatic window, and cleared completed diagnostics. Full safe suite, WAN PostgreSQL contract, Docker, browser CI, and independent review are required on the published head before merge.
- Verification boundary: forbidden PostgreSQL pool/runtime sources were not read or imported. No production DB, filesystem, service, or configuration changes were performed. Existing standard deployment of the baseline continues independently.
- Rollback: revert this follow-up; no migration or financial data repair is needed.

- Independent review found the expired-window/future-backoff callback boundary: returning 200 could lose the only late completion signal. Corrected by persisting a unique callback_pending marker after authentication, respecting lease/backoff, and allowing one marked canonical lookup beyond the age window. An older in-flight pending poll preserves a newer marker. Added signed HTTP deferred-callback and marker-race/consumption regressions; exact-method synthetic SQLite checks pass. Pending/unconfirmed canonical outcomes consume the notification and retain operator attention rather than restarting unbounded automatic polling.

- Second review correction: unconfirmed/transport-error/malformed/wrong-lineage observations must preserve the authenticated callback marker, retrying under the capped delay until a valid canonical observation is available. Only validated canonical pending consumes a marker. Signed HTTP tests cover deferred success after transport errors, malformed payloads, wrong task IDs and wrong models. No lease bypass or provider resubmission was introduced.


## 2026-10-10 - WAN direct Telegram references and clear duration/upload controls

- Baseline: tanyapi 65dbe01ffb0fd4bf477a3800a76c6e7e08fcf18f; fresh branch/PR audit found no duplicate WAN task. Existing operator-recheck work remains outside this release.
- Evidence-first audit: Telegram media handler registered eight distinct State filters with AND semantics, making every intended media state unreachable. Dashboard had no direct media intake. Concurrent album/state writes could overwrite references or prompts. Unicode-only filename stems lost their extension separator. MiniApp duration was a select and upload feedback appeared only near the cost block.
- User-visible result: open WAN and attach mixed media or an album immediately, type a prompt, inspect the actual duration, calculate price, then explicitly confirm launch. The compact Telegram keyboard has a single minus/current-seconds/plus row and sound control; advanced frame/edit roles and all provider fields remain in Settings. MiniApp gets a range slider with separate Auto and field-local upload progress/error/cancel/retry.
- Implementation: (1) OR StateFilter and direct dashboard intake; (2) per-actor serialization, pre-lock draft identity/reset fencing, message ordering and atomic quote commit; (3) automatic scenario from actual references without guessing frame/edit roles; (4) preserve advanced snapshots and safe Unicode filename suffixes; (5) duration controls invalidate quotes; (6) field-local uploads with bounded cancellable requests and stale-response suppression.
- API/schema/config: no schema or route/body changes, migration or production config changes. Client upload/import accepts an optional AbortSignal. A 15-minute per-request budget matches the existing MiniApp media budget rather than imposing a short whole-file deadline. Provider 2..30/Auto duration bounds and authoritative combined source-plus-output <=30-second server quote validation are unchanged; unknown source duration is not invented by the UI.
- Provider/payment impact: no generation before explicit quoted-cost confirmation; prices, referral rules, debit/refund paths, paid provider POSTs and historical financial data unchanged. Client cancellation discards late UI attachment; it does not promise server-file deletion.
- Observability: immediate safe Telegram progress/error messages and kind/count logs without prompt, file URL or provider secrets. MiniApp progress uses acknowledged chunks; retries retain only unfinished files.
- Local verification: Telegram actual aiogram filters and isolated public handler seams: 48 passed; changed Python Ruff passed. MiniApp focused Jest: 37 passed/3 suites; selected dependency-closure typecheck passed; lint 0 errors with 2 pre-existing hook warnings; isolated production fixture build/export passed. No application DB/bootstrap imports or paid calls were used. Full application/CI checks remain required on the exact published head.
- Independent review: Telegram v2 patch 8846094c05ccbc4c96bc989ecd6ca4df4b42a53deb4c64e08efc5394e73be70d clean with independent 48-test rerun; frontend spec/standards reviews clean after fixing equal-value recipe reselection. Combined exact-head review is a release gate.
- Verification limits: local Chromium launch failed with socket() Operation not permitted, including the permitted escalation attempt. No browser, mobile WebView, real-device or production/provider pass is claimed. No alternative path is used to bypass that restriction; normal repository CI remains required.
- Rollout: dedicated draft PR to tanyapi, exact-head safe-suite/browser/Docker gates and clean combined review; parent coordinates the single merge owner under user authorization. Verify installed backend and frontend SHA after normal deployment. Rollback is an isolated revert with no migration or financial repair.


- Exact-head CI follow-up: fixed full-repository import ordering. The existing edit-source-removal regression exposed constructor defaults enabling Auto on explicit advanced recipes; constructors now pin first_frame/first_last/edit, with explicit Auto remaining available. Added legacy recipe/intent regressions; isolated Telegram count is now 52 passed. WAN browser E2E was updated from the removed select to exact slider/switch roles, retaining all old payload assertions and adding duration bounds/manual restoration/locked retry assertions. Node syntax and patch checks passed; normal exact-head CI and delta review remain required.


## 2026-10-10 — WAN post-review UI and upload-session guards

- Baseline: merged PR287 `0bedef3db0131a463e1a1372499c7822951c37e6`. Its production deployment run38052967637 was cancelled before SSH on user request; read-only verification confirmed production remains65dbe01f, healthy with zero restarts. This follow-up addresses all four postmerge P2 findings, not the paused operator extension.
- Telegram: unchanged duration/Auto callbacks acknowledge without replacing the message or invalidating a valid quote; identical duration-screen rendering tolerates Telegram's unchanged-message error. Image/video/audio slot limits are validated before any download/import, while explicit source replacement remains available. In-flight and queued inputs check current FSM/model and draft identity; exiting to model picker rotates the reset token before continuing the existing generic route. Stale setting callbacks outside WAN do not reopen it; explicit WAN entry still works.
- Telegram verification: 68 isolated real-aiogram/handler regressions passed, including endpoints, all reference limits, source replacement, queued media/prompt/options during model/state departure and genuine reentry. Independent frozen-diff review is clean; Python lint passed.
- Client protocol: capture a random32hex upload ID and metadata before init; same-ID recovery establishes unknown init outcome before owner cancellation. Await cleanup before creating a fresh reservation. Per-owner sessionStorage contains only upload ID/phase/file metadata, never auth/initData/tokens. Account changes never authorize cleanup of another owner's reservation. Cancel while init is pending remains visibly cancelling until its bounded request resolves; cancellation then removes only unfinished server work. Unknown outcomes stay fail-closed through explicit retry instead of guessing expiry or making new IDs.
- Client verification: 57 tests across4 suites, selected TypeScript closure, changed-file lint (0 errors;2 pre-existing hook warnings), and node syntax check passed. E2E fixture now echoes chosen IDs and supports cancel. Independent frontend review is clean. Browser launch was not retried after the known local socket restriction; standard repository browser CI remains a gate.
- Release gate: publish a dedicated draft PR, complete exact-head normal CI and combined internal review, then mark ready and await the already configured automated review before merge. All remarks must be closed; parent coordinates the single merge owner. No paid provider generation, production data/config mutation or unrelated changes are included.
## 2026-10-10 — WAN upload cancellation and uncertain-init recovery

- Baseline: `tanyapi` `0bedef3db0131a463e1a1372499c7822951c37e6`. Narrow backend follow-up for owner-cancelled temporary Mini App uploads exhausting the five unfinished-session slots. Client changes are coordinated separately.
- Evidence-first audit: client abort did not alter server reservations; storage already has owner-scoped session rows, a global quota lock, per-row chunk/finalization locks, assembly stamps, and bounded retention. These existing mechanisms are reused. No migration, credentials, security setting, provider/payment operation, generation/history mutation, or production state change is added.
- API: existing signed Telegram auth protects new `POST /mini-app/api/wan3/upload/cancel` (`upload_id`). It returns `ok: true` and `status: cancelled`, `completed`, or `not_found`. Foreign and unknown IDs are indistinguishable. Owner terminal/completed replays are safe; completed media is never deleted. Malformed IDs are rejected before any session query/mutation.
- Init accepts optional lowercase 32-hex `upload_id`. Existing matching owner, normalized filename, kind, size and content type replays an open/unexpired reservation without consuming another quota slot or extending expiry. Existing foreign/changed/expired/terminal IDs return generic HTTP 409 `upload_session_conflict`. Older callers can omit the ID. Existing primary-key rows remain durable, including after retention.
- Recovery rule: after an uncertain init result, replay the same ID and metadata until success or explicit `upload_session_conflict`, then cancel. `not_found` alone never establishes that an earlier request cannot arrive later. No blind new-ID retry, server-side tombstone, new status endpoint, polling process, or guessed TTL clearance is introduced. Quota/disk/auth/transport failures are not a durable fence; the client retains pending metadata for explicit bounded retry.
- Concurrency: cancellation takes the existing global storage lock then owner row lock. In-flight chunks finish under their existing row lock. A cancelled assembling session fails the existing status/lease check at final persistence and cannot reopen in the completion error path. Final persistence winning the lock returns `completed`; cancellation does not remove media or history.
- An additional deterministic regression reproduced HTTP task cancellation during `copy_atomic`: its thread could finish after transaction rollback and create an untracked final file. The shared `save_owned_file` boundary now shields its final DB/copy transaction and waits before propagating request cancellation. This covers chunk completion, URL imports and Telegram callers without duplicating wrappers, retaining the owner/quota lock until persistence finishes. Probe cancellation behavior remains unchanged. An import-specific actual `task.cancel()` regression verifies that `discard_import` removes only temporary files after successful final persistence and preserves completed media. No network or provider call is added. Existing size/probe bounds remain; copy/fsync still has no hard wall-clock bound under a stalled filesystem, so waiting is necessary to prevent an orphan writer. Host/process termination is outside the guarantee.
- Session and byte capacity remain distinct: cancellation immediately releases the five-session admission slot; cancelled declared bytes stay reserved until existing retention actually removes the temporary directory. Retention now considers cancelled sessions after the existing assembly-lease grace period, without waiting for their original expiry. Removal failure keeps the reservation and retries later. Repeated cancel does not renew the cleanup grace.
- Observability: retained session status/updated_at show cancellation; existing HTTP boundary retains sanitized errors. No signed initData, file content, public media URL, prompt or credentials are logged.
- Verification: 28 exact-method/service regressions pass against synthetic temporary SQLite and mocked auth. They cover six cancel/retry cycles; max-five live sessions; same-ID concurrent init; Cyrillic normalization; owner/metadata/terminal/expiry conflicts; missing/foreign/replayed cancel; byte-quota accounting; deferred and failed physical cleanup; chunk/assembly/final-copy races; task-abort during chunk and import copy; preserved completed media and generation history; signed-auth enforcement; and endpoint registration/conflict-code mapping. Focused syntax compilation and Ruff pass.
- Added normal-CI HTTP coverage in `tests/test_wan3_http_flow.py`: actual HMAC-signed aiohttp requests and real isolated application storage, missing/expired/forged auth rejected before cancellation, forged body owner IDs ignored, same-ID init replay, owner cancel/replay, foreign/unknown equivalence, terminal init fence and unchanged balances. These four cases were authored and syntax/lint checked, but deliberately not executed locally because the normal app test fixtures import the restricted database runtime.
- Verification boundary: locally executed tests use mock auth only and execute unchanged selected storage/API definitions and allowed file/policy/retention/schema code with synthetic dependencies; they do not import the application database or restricted PostgreSQL runtime. No real PostgreSQL integration, full application suite, browser, deployed smoke, or production pass is claimed. Exact-head normal CI, frontend integration and independent review remain release gates.
- Guidance: repository AGENTS, README, `.agents/README`, recent execution ledger, and relevant source/schema were read. `Bambale0/skills` README was available, but diagnosing-bugs/TDD paths and targeted searches returned no matching skill; evidence-first regression-first workflow followed repository guidance. `Bambale0/claw` AGENTS and `anthropics/skills` webapp-testing were inspected; browser work belongs to the frontend sibling. No external helper code was executed.
- Rollback: prefer a forward correction. A blind full revert is unsafe while cancelled rows/files remain, because older code neither cleans cancelled directories nor counts their reserved bytes. If rolling back client/API behavior, retain forward-compatible cancelled-state retention and byte accounting until normal cleanup has drained those temporary files, then assess reverting the remainder. No manual production cleanup or DB change is performed here. No schema reverse migration or release has been performed by this worker.


## 2026-10-10 - Seedance default Telegram video catalog tab

- Baseline: tanyapi `0bedef3db0131a463e1a1372499c7822951c37e6`. Prepared separately from PR #288; publication/merge must wait for the parent's release gate because the baseline still contains superseded WAN behavior.
- Evidence: the screenshot matches `video_generation_compat.show_complete_video_model_selection`; a new `create_video_new` explicitly rendered family `all`. Existing family tabs, pagination and model-specific routes are already implemented and reused.
- Change: only the fresh-entry family argument becomes `seedance`. No model is automatically selected; `video_change_model`, explicit family/page callbacks, trends, repeat and deep-link model restoration are unchanged.
- Scope: Telegram presentation-only default. Mini App, provider routing, availability, pricing, payments, database, migrations, persistent settings and runtime configuration are unchanged. No new operational control or hardcoded provider/model choice was introduced.
- Verification: regression first failed (`all` versus `seedance`), then 19 isolated public-handler tests passed using real aiogram and the actual capability table. Coverage includes fresh/repeated entry, all four general-catalog pages, seven family tabs and preservation of existing model/media/navigation when changing models.
- Checks: syntax compilation passed. Ruff passed with the full-repository `bot` namespace explicitly classified as first-party for this sparse source copy; the unconfigured sparse copy misclassifies missing sibling modules equally on baseline and candidate.
- Safety/limits: dependency stubs isolate application bootstrap, DB and provider imports. `bot/postgres_pool.py` was never read, restored or imported. No runtime, database, paid generation, production smoke or deployment was run. Full normal CI and independent review remain release gates.
- Rollback: revert this presentation-only change; no migration or financial repair.

- Release coordination: user approved including this isolated catalog change in PR #288 at 13:34 UTC; applied on the fully green WAN head `87072dace66147d9ad4f1c9b2def362d5c54f5b5`, preserving every existing WAN fix. Fresh exact-head CI and automatic review remain required.

## 2026-10-10 — Tanya WAN standard, measured video-reference quotes and safety

- Baseline: origin/tanyapi aa64bb8b8ee90559bec695fc5466ff3df8cbe9d3. Dedicated sparse worktree and agent/tanya-wan3-videoref-20261010. Live checkout has unrelated dirty data/price.json, diagnostics/receipts and restart_check.py; untouched. Restricted database pool module is excluded from checkout, reads and imports.
- Scope: ordinary KIE wan/3-0-video with separate model/admin rate; measured input plus explicitly selected output seconds retail quote; removal of old videoref multiplier; Motion finance safety; Seedance uncertain delivery. Do not change historical accepted quotes/ledger, admin rates, live configuration, or other bots.
- Preflight: Prime already provides durable launch/quote/media lifecycle. Standard WAN must reuse it with immutable model identity through recipe, quote, submit, recovery and delivery. Motion presently trusts client duration and refunds any exception, including admin/no debit and accepted submissions. Seedance send timeouts fall through to file/link and are requeued.
- Decisions pending: Auto and Omni output without independent selector require an explicit reserve/settlement policy; no fabricated output duration will be introduced. Motion duration must come from trusted measured source and documented provider constraints.
- Vertical slice 1: Seedance public/admin URL, downloaded media and link send exceptions now permit fallback only on explicit Telegram API rejection. Unknown acceptance raises a typed uncertainty outcome; outer dispatch records uncertain, which blocks automatic claims/replay. Auxiliary photo uncertainty does not retry as a link. Stored generated results and balances are unchanged.
- Evidence: isolated selected-function public send and dispatcher tests initially reproduced four failures (timeout retried and dispatcher pending). After change the isolated tests pass; no application/database/bootstrap imports, paid generation or real messages run. Full application CI remains a release gate.
- Guidance: read AGENTS, README, local agent instructions, execution ledger, Bambale0/skills diagnosing-bugs/TDD/implement and Bambale0/claw QA checklist, anthropics/webapp-testing. Shared skills updated only after specific user authorization.
- Remaining: Motion durable receipt/refund and trusted duration; shared pricing/frontends; WAN standard; exact-head tests and independent review; draft PR then release gates. No merge/deploy yet.

- Delivery review follow-up: explicit Telegram 429 is retryable rejection with persisted retry_after deadline honored by atomic claim; it does not trigger immediate fallback or permanent uncertain. Timeout before any active send remains pending, while in-flight send timeout remains uncertain. Nine isolated behavior regressions pass and changed Python parses; database claim/deadline integration requires normal CI.

## 2026-10-10 — Ordinary KIE WAN3 and fixed WAN retail quotes (review pending)

- Ordinary wan_3 / wan/3-0-video is a separate immutable model using the existing shared WAN lifecycle and media contract (14 provider fields, all seven scenarios). No duplicate worker/table or storage split.
- Model identity is preserved through quote, rate lookup, intent/task, provider submit/recovery, status, delivery, Telegram drafts, owner restore, public repeats and curated trends. Prime legacy recipe fingerprints preserved.
- New WAN fixed-duration quote v2 freezes input measured video seconds + selected output seconds at current admin model/quality rate. Auto retains the documented 30-total-second reserve; old accepted quote snapshots retain legacy settlement.
- Mini App recalculates eligible quotes after settings/reference edits; launch remains explicit. Separate ordinary admin quality selectors added without writing rates. Read-only production check found ordinary wan_3 rates absent; launch remains missing_rate until admin assigns rates.
- Verified locally: nine isolated backend contract/identity/rate/legacy/settlement tests; full existing frontend Jest suite 393 passed before one additional ordinary-editor journey (targeted suite20 passed); TypeScript passed, ESLint zero errors (existing hook warnings). Full lifecycle tests added for CI, not locally run because restricted pool module must not be imported.
- Independent exact-head review and full CI are required before publication release. No paid generation, real Telegram message, live checkout edit, secret read or history repricing.

- WAN review follow-up: ordinary now enters full publication reference contract, Telegram continuity redirect, internal admin replay lifecycle, strict quality tariff, and trend editor guard. Added ordinary first/last/audio, own/public redirect and admin replay regressions. Actual Chromium against local production static build passed all 14 Prime+ordinary scenario journeys plus model navigation and unknown-ack retry. Start hit-test remains mandatory after quote layout settles; safe-area bottom padding added. Interrupted Prime upload -> ordinary switch component test passed.

## 2026-10-10 — Tanya Motion durable launch safety (review pending)

- Scope: owner-bound measured source + locked output quote, atomic receipt/debit and proven-rejection refund; no historical balance changes.
- Accepted-but-unbound receipts recover through watchdog without browser presence. Unknown provider acceptance is held, never retried or refunded automatically.
- Watchdog/callback failure requires terminal provider evidence for new Motion receipts; frozen charged amount survives later role/price changes.
- Mini App persists original request identity before sending, restores status across reload, and uses identity-CAS cleanup so late responses cannot clear a later launch.
- Local checks: 27 isolated Python tests on synthetic SQLite/pure functions; 5 real PostgreSQL16 fixture transaction tests (BIGINT, concurrency, refund rollback, pending guard); 3 Jest pending-state tests; TypeScript and changed ESLint passed.
- PostgreSQL fixture used a temporary network-disabled container and test-only asyncpg cursor shim, not application adapter/full application CI. Created container removed after tests. No provider calls, actual Telegram sends or production DB access.
- Independent review and full exact-head CI required before merge/release.


## 2026-10-12 — Protect author trend assets from generic upload cleanup

- Baseline and deployed SHA: `87087c244bd11127c60f86e19c04e0fbc2b95659`; isolated branch `fix/tanya-protect-trend-assets-20261012`.
- Incident evidence: the production generic cleanup logged deletion of 15 trend asset files on October 11. The managed author-template directory was absent from its excluded roots.
- Narrow fix: add `trend-assets` to the existing generic upload-cleanup excluded roots. No TTL, billing, ownership, database, provider, restore, or deployment-script changes. Existing missing assets remain unavailable; this patch prevents further generic TTL deletion only.
- TDD: the actual cleanup loop and removal function, extracted without application imports, run against temporary synthetic directories. Before the fix: one preservation regression failed, two ordinary-cleanup/protection regressions passed. After the fix: all three regressions passed; focused Ruff and whitespace checks passed.
- Tests preserve aged image/video/audio assets and empty shards, existing refs/feed/WAN/public-result protection, remove expired ordinary uploads (including similarly named directories), and preserve recent ordinary uploads. Production cleanup is never invoked by the tests.
- Fresh playbooks were read through GitHub connectors. Shared local playbook git refresh was denied and was not retried; no claim of a successful local refresh.
- Release gates: independent exact-head review, required CI, user-facing pre-release report, guarded deployment and exact SHA/health verification. No recovery from unverified media backups; no PR294/helper changes included.

## 2026-10-12: preserve legacy Seedance 2.5 repeat image slots

- Baseline: tanyapi 1af61b3f1e275fdc2f0507ef03ba27ec7f5c5e2c; separate fix branch.
- Confirmed synthetic defect: generic Photo+Text repeat with one viewer photo replaced the entire legacy multimodal image list. A retained Image2 prompt binding then failed validation.
- Scope: non-owner, legacy selection=None, multimodal S2.5, generic imgtxt, source list with multiple images. Replace Image1 only; retain Image2..N on the server in canonical order and private provenance. Multiple replacement images and collisions with retained slots fail closed. Explicit grants, owner edits, identity/editing and frame scenarios keep their existing contracts.
- No schema/config/rate/provider/payment changes. No restoration of missing assets. The author-specific live examples are not yet linked to this synthetic reproduction.
- Existing authenticated restoration and before-charge permission recheck remain unchanged; no hidden references or author prompt are returned in response/errors.
- TDD: isolated actual-function regression initially 3 failed / 3 passed. Added installed HTTP-entry tests for preservation, excessive replacements, unavailable retained input, owner editing and revocation; exact/known-host alias collisions covered in CI.
- Local tools: pure AST tests only, no application/database imports. Full HTTP/backend/browser regression runs require CI.
- Guidance: local diagnosing-bugs (Bambale0/skills), debugger (Bambale0/claw), webapp-testing (anthropics/skills). Previously denied shared playbook refresh was not retried.
- Rollout: draft PR to tanyapi; independent exact-head review and full required CI; parent sends pre-release report before merge/CD. No paid production smoke.

## 2026-10-12: visible legacy repeat follow-up

- Base fcea07bdd203dd446acdd09c60fcd4ee04d084c7. Review P2 reproduced: visible legacy publications with null selection submit all displayed images; the new hidden-slot guard rejected them.
- Minimal correction: apply the first-photo-only protection only when the source references are hidden. Server-owned visibility is used; browser fields cannot bypass it. Existing visible legacy all-or-nothing behavior is preserved.
- RED: 2 new visible cases errored / 10 prior hidden cases passed. Full installed HTTP-entry regression covers unchanged visible lists and complete visible edits.
- Review P1 task-detail exposure was not reproduced on the actual HTTP path: miniapp_task_detail calls the existing privacy sanitizer, which recognizes persisted source_feed_gen_id and removes hidden links/prompt. Added actual HTTP handler tests using real S2.5 request-data assembly, with both successful and failed privacy lookup. No production privacy change needed for this reported path.
- No database, pricing, media restoration or provider-call changes. Local verification uses isolated functions; full app tests run in CI without local forbidden-adapter imports.
- Release gates remain independent review, exact-head full CI, parent pre-release report and guarded CD/runtime verification.

## 2026-10-13: legacy repeat required-slot descriptors

- Base 730faded29c4bd047f27837c923587954a25880e. User-confirmed shape: four existing source images; visible legacy selection retains positions3 and4, while the viewer supplies only one image. Backend correctly requires two replacements. The old card omitted descriptors and the generic form misleadingly marked uploads optional.
- Added display-only bridge for closed retained-tail S2.5 multimodal legacy selections. It reuses existing capability/alias/pricing validation and returns only index/role/binding. The temporary typed-shaped validation copy is never persisted and never authorizes launch. Original legacy grant, selection and before-charge checks remain unchanged.
- Existing renderer now receives upload0/upload1/fixed2/fixed3 and cannot submit one upload. Optional trailing/no-retained layouts keep their existing UI rather than silently adding required uploads. Identity/editing/frame/audio scenarios are not promoted by this narrow bridge.
- Additional independently reproduced hidden video-mode edge: one photo lost Image2 when v_type=video. Existing hidden first-photo protection now covers imgtxt and video, preserving frame/identity/editing exclusions.
- Pure tests: video-mode regression RED2FAIL/12PASS before correction, GREEN14PASS after. New pure descriptor helper6PASS. Installed HTTP, real DB card/grant persistence, aliases and actual component upload-order regression added for CI.
- UI test written separately; no local Jest dependency available in this sparse worktree. Full application tests are CI-only to avoid forbidden database-adapter imports.
- Exact user source checked read-only: all four files present, no recovery needed for that source. No production data/rates/permissions/media changed; no paid requests.
- Skills: evidence-first diagnosing-bugs, scoped debugger and actual-component testing. Unknown/cancelled reads were not bypassed; focused source access resumed only after explicit permission.
- Rollout: separate draft PR, independent review, full CI, parent pre-release report, guarded release and exact runtime verification. Do not equate an unrelated synthetic fix with all user reports being resolved.


## 2026-10-13 WAN mobile chunk transport

Base b0c77f579fbf7824846c98f59e5bbe2d2e88b8f2. Scoped diagnosis, implementation, test and release plan: [WAN chunk transport](WAN_CHUNK_TRANSPORT_2026-10-13.md). Shared playbook refresh remains blocked by the earlier access denial; existing relevant guidance was read. Candidate patch transferred with verified SHA256 9cb74dfbb25fd7e599ed6def4c7f97cf6f6577ffcbd005be2151b4aa1cb91958. Local actual-route isolated suite: 12 passed. Added a narrow documented S102 waiver for trusted AST extraction; no app/database import. Full CI and exact runtime verification remain release gates. Real iPhone upload confirmation remains necessary after deployment.

## 2026-10-13 WAN manual trend publication

Baseline ca3df2da85856ee593777a30555ee7e474fc6946. Observed generic prompt submission creates a WAN catalog row without a private recipe; repeat-plan then returns 404. No historical rows are changed or reactivated.

Implementation: strict complete recipe and explicit replacement keys for both WAN models; administrator check; media ownership/type/hash validation and atomic public-card/private-recipe insertion under the same storage lock as retention. Existing retention pins recipe_json, so saved references remain protected without global TTL changes. Public cards contain only presentation and slot metadata. No generation, payment or provider request is used by publication. External link slots and template user fields are rejected explicitly rather than silently discarded. Existing generated-task publisher remains available.

Coverage: pure contract tests and existing chunk HTTP regression run locally without application/database imports. Full application tests cover both models, public privacy, compiled replacement order, foreign/nonadmin rejection, rollback, retention and no reactivation. These require official CI. Frontend implementation and independent final review pending. Relevant previously read diagnosing-bugs/debugger/webapp-testing playbooks used; shared checkout refresh remains unavailable after prior denial. Release requires exact CI/review and a user-facing report before merge. Real user publishing/repeat UI smoke remains distinct from paid generation.


## 2026-10-14 PR305 release verification

- Isolated worktree at /root/tanya-workspaces/video-billing-pr305; live tanyapi checkout and data/price.json untouched. PR source head 1d7e0916; tanyapi later incorporated PR308.
- Resolved review findings: M4V/WebM local duration measurement; duplicate video normalization; stale quote refresh in Mini App; Telegram repeat missing-reference handling; explicit trend video quote-only and second-click approval to prevent unconfirmed debits.
- Trend hash binds actor, trend, saved recipe, resolved hidden and uploaded references, quote seconds/rate revision. A missing/stale hash fails 409 before balance deduction and finalizes an idempotency claim.
- Verified local Next.js static production build, TypeScript, targeted Jest and all 62 Jest suites / 476 tests, and Playwright repeat references flow at 320/390/430 px. Added backend hash, no-debit, format and dedup regression tests.
- Host pytest blocked by missing aiogram: required Python CI must prove backend. No production price/config/migration/provider changes, no paid generation.
- Remaining: exact-PR CI (including browser, PostgreSQL, bot, Docker), review, native squash auto-merge to tanyapi, exact-SHA deploy and postdeploy health/telemetry smoke. Do not claim deployed before checks.


### 2026-10-14: final Python CI gate after 9561e8d

- GitHub TG CI 1894 failed only in safe regression suite: 3721 passed, 110 skipped, 10 failed. Two were private Seedance trend contract tests that bypassed the new mandatory preview-and-approval request; eight were isolated pure pricing tests whose module stub did not implement the existing normalization dependency.
- Regression repair (test-only; production code unchanged): update the isolated reference-policy stub to deduplicate and trim as the real public interface does; for valid private video trend tests obtain the server's quote first, assert preview does not launch or debit, then explicitly pass the hash. Invalid/oversize videos remain fail-closed. Do not bypass the actual approval gate.
- Host Python unittest of isolated pricing tests: 8/8 passed; compileall passed. GitHub Python CI rerun is authoritative for full bot tests. Existing dirty production price.json and diagnostics remain untouched.


### 2026-10-14 CI 1895 final browser regression

- Safe backend regression passed: 3731 passed, 110 skipped; standalone Mini App browser E2E and other checks passed.
- GitHub CI job 115898452976 failed only in e2e/creator-tariff.mjs:75: it still asserted the deleted presence multiplier (40 bananas) instead of a server-measured reference video quote.
- Updated synthetic creator tariff browser test to quote 18 input seconds plus output with model/viewer rate, check read-only quote produces no launch, require hash on launch, refresh quote when prompt changes, and assert no client-controlled tariff. Local Chromium E2E passed all four combinations (standard/creator with Seedance 2/2.5).
- Production remains on 177cf068 until protected branch checks pass, native squash merges PR305 and exact deploy is verified. No paid generation and no runtime price.json changes.

### 2026-10-14 Trends links — iOS clipboard denial after async URL retrieval

- Production SHA before fix: `8d8aef6839705a3598695b0f7d0c6569fa1a34b5`. User screenshot shows red error `Не удалось скопировать ссылку` on iPhone Telegram Mini App -> Trends -> Link. This exact string was produced by `handleCopyLink` after awaiting authenticated `/prompts/link` and then calling clipboard methods. The async POST consumes iOS WebView's transient tap activation; WKWebView can deny both `execCommand('copy')` and Clipboard API, while Trends had no manual or native share recovery. Feed already had a recovery UI.
- Fix scoped to Trends: preserve authenticated backend-owned exact referral deep link; open accessible share dialog, show selectable readonly link and fresh direct-copy gesture on iOS, native OS share, Telegram forward or open link, honest clipboard failure rather than false copy success. Keep Android automatic success. Reject invalid/executable links; invalidate late API responses on dialog dismissal and offer API retry. Emit `trend-share-clipboard-denied` client telemetry without logging referral token or URL.
- Regression proof: targeted test originally failed with the exact red banner and no usable share dialog; after fix, 8 targeted tests pass. Full Mini App Jest: 63 suites / 486 passed, local Next 16 production static build, TypeScript and changed-file lint passed. Chromium Android synthetic Playwright share flow passed. Standalone iOS WebKit requires libraries missing on production host, so protected GitHub CI now installs Chromium+WebKit and runs dedicated `e2e/trend-share-clipboard.mjs` in addition to `critical-flows.mjs`.
- No database/payment/provider changes, no paid generations and no mutation of live runtime files. Release must be PR against `tanyapi`, native protected squash auto-merge, exact-SHA production deploy and health/revision/telemetry smoke. Real iPhone WKWebView acceptance may differ by Telegram/OS; users always retain manual and native share recovery even when programmatic clipboard is forbidden.


### 2026-10-14 — Tanyapi private trend variable binding and Seedance launch
- Production complaint: editing birthday digits on a photo/video trend left the original visible digits in the private base prompt and appended only user instructions; user then saw contradictory output. The original hidden scenario was retained by storage, so replace in place rather than overwrite prompt.
- Read-only audit of production templates: 8 video + 3 image trends had configured viewer variables without token bindings; in-memory dry-run of new prompt renderer successfully substituted the unambiguous original visible digits for all 11 while preserving timecodes and reference aliases.
- Admin can set private original_value for ambiguous or text fields. Public user_fields sanitizer strips original_value; viewers only see labels/inputs. Legacy {{token}} stays compatible, unbound nonnumeric fields retain original prompt with appended authoritative change instructions.
- Found independent prod HTTP 500 after /trends/run pricing: Seedance 2.5 wrapper rejected billing_quote kwarg; now accepts and forwards verified quote, without duplicate price calculation. Seedance 2.5 quote uses own resolution and edit duration.
- Synthetic tests for prompt renderer, wrapper/provider payload, pricing, privacy and existing trend integrations; full Mini App Jest, TypeScript, ESLint, and production export build. No paid calls, DB updates or production price modifications.


---

## 2026-10-15 — PR #312 trend showcase release hardening

- **Baseline:** feature bc1aeb1cb1c2623754e5728718134545e40b78b6, tanyapi production b938e8b924837d0a2af22ddf3b11f0d7b5c7dffe.
- **Goal:** finish editor-managed trend folders and live video tiles; merge safely and verify exact backend/Mini App release revision.
- **Audit:** PR #312 all prior CI gates pass; latest code review found three unfixed issues: shared trend draft state crosses folders, extensionless videos rendered as images, no durable admin catalog audit. Existing user_prompts.category, Seedance/WAN pipelines, referral, prices and private recipes must not change.
- **Reuse:** trend_catalog SQLite/PG migrations, bot/trend_catalog_api signed Mini App auth, existing append-only creator/partner audits, TrendShowcase, TrendCategoryManager.
- **Risks:** concurrent admin changes; leaking hidden recipe in audit; PostgreSQL DDL triggers; category delete losing history; stale draft changing another folder. Existing prod data/price.json is mutable and must be preserved.
- **Implementation:** 1. partition draft state by (category_id, trend_id); 2. resolve video media by safe public kind+legacy tags; 3. add independent append-only trend_catalog_audit with signed Telegram actor, action, before/after snapshot, stored in the same DB transaction for every mutation; 4. expose authenticated admin history; 5. regression/CI/code review; 6. merge to tanyapi; 7. verify exact SHA and production smoke.
- **No hardcode:** editorial category names/order/badges are admin-controlled DB data; audit stores only IDs, public category metadata and membership positions, never executable prompts or private refs.
- **Observability:** read-only history list with event ID and actor, signed request logs, deployment SHA/health and HTTP endpoints, check errors after release.
- **Test plan:** SQLite unit/HTTP atomicity and append-only guard; PG migration via existing CI; Jest category switching and no-extension video; browser E2E; CI suite, Docker image, deployed SHA, endpoint guards.
- **Status 2026-10-15:** implementation in progress; production deliberately unchanged until green checks and review.


### 2026-10-15 hardening implementation checkpoints

- Folder+trend scoped draft keys, including move targets and badge expiry, verified in React/Jest.
- Video cards honor public preview_type, then public generation kind/category/trend-video and local extension including MKV/AVI.
- New additive trend_catalog_audit schema with SQLite and PostgreSQL append-only guards; eight service mutations insert signed actor and before/after metadata on the mutation connection before commit.
- Authenticated admin history API/UI; read-only and no prompt or private media in snapshots; timestamps include microseconds.
- Tests: 20 focused backend passed; 12 frontend Jest passed; PostgreSQL acceptance appended to isolated creator test suite (requires disposable GitHub service).
- Remaining: full regressions, Next build, browser tests, CI/second code review, merge and production SHA/health/log smoke.


### 2026-10-15 pre-PR gate evidence

- 160 backend regressions passed (including immutable SQLite audit, rollback, signed admin-history HTTP, variable binding, Seedance/WAN/Pinterest/privacy).
- 57 Jest regressions passed, TypeScript and ESLint clean.
- Production Next.js static export generated; Chrome mobile E2E passed extensionless video, category pagination, existing repeat dialog, admin editing and signed history.
- Disposable PostgreSQL trigger/atomicity case added to creator PostgreSQL workflow tests, awaiting GitHub runner.
- No live customer generations, price changes, DB edits or direct production deploy performed.

- Follow-up Codex review on functional commit 59b5676: security review clean; reviewer identified reverse-order PostgreSQL row-lock deadlock for concurrent category reorder (P2).
- Fix: PostgreSQL now locks category rows ORDER BY id FOR UPDATE prior to position updates; SQLite takes BEGIN IMMEDIATE before reading revisions. Added disposable PostgreSQL concurrent opposite-reorder test requiring exactly one revision-conflict and one success, rather than deadlock/500.
- Final local focused regression: 20 tests passed, Ruff clean. Pending GitHub PostgreSQL concurrent CI, entire CI and code review final disposition.


### 2026-10-15 — WAN 3 repeat price / iPhone JPEG upload release
- **Baseline:** tanyapi production `a7a498044f7f40eaac07b38d7e56c7c49caec026`. User screenshots: WAN reference trend repeat reports red `IMG_0729.jpeg` validation failure; published WAN repeats omit banana price.
- **Evidence:** Postgres read-only lookup found 5 attempted `IMG_0729.jpeg` reservations, 1,017,222 bytes each; four received all chunks, repeated `/wan3/upload/complete` HTTP 400 and session cancellation. Stored bytes already expired, so the precise Pillow/media rejection is not recoverable. WAN public repeat plans return 200 and 10 current approved WAN 3 trends have durable recipes; do not loosen author media/privacy permission.
- **Pricing root:** `estimate_trend_repeat_cost` correctly returns null for WAN because the total depends on measured retained/uploaded video durations, but the UI hides all price information. Introduced a **catalog-only server retail floor** from current per-model resolution rates and output duration; Auto is an explicit 30-second maximum reserve. Source video duration stays unknown until server quote. Supports creator tariff snapshot; missing/stale rates fail closed. Public API carries only amount/type, no hidden reference URLs/prompts; final quote/hash/charging unchanged.
- **Upload recovery:** after a 400 `validation_error` from owned image upload, the existing client-side session cleanup finishes before an optional one-time browser canvas JPEG export (bounded to 4096px and 20 MB) is uploaded as a fresh session. Original filenames shown in UI; Abort/cleanup and admin/private materials unchanged. If even the export is rejected, show actionable JPEG/PNG instructions and allow an explicit retry. Original failed image cannot be replayed because retention removed its chunks; real iPhone acceptance still required.
- **Coverage:** focused Jest 4 suites / 42 passing, TypeScript noEmit, ESLint/lint, Next.js static production build; backend price contract + WAN regressions + trend API 74 passing; Ruff + diff check. No paid provider calls, no DB edits, no price.json/config changes.
- **Release:** dedicated branch -> PR against `tanyapi` -> protected checks/auto-merge -> exact production SHA, backend health, Mini App revision and logged upload/quote observation; no `main`/`dev` edits. Physical iOS Photos/Telegram acceptance is a follow-up, not implied by mocked tests.


### 2026-10-15 — restore successful trend repeat counts on categorized live tiles
- **User report:** the previous successful-launches number disappeared when the editor-managed trends screen switched to live category tiles. The legacy trend success compatibility module still enriched legacy list+detail, but trend_catalog bypassed it and TrendShowcase rendered no counter.
- **Production read-only evidence:** trend_generation_runs joins uniquely on task ID with generation_tasks.status = completed: 1,367 completed, 33 failed linked tasks initially, while user_prompts.uses_count includes accepted/failed launches. The count belongs to trend ID, never to an editorial folder. No live data mutation.
- **Backend:** one existing get_trend_success_counts bulk query per catalog, category page or authenticated admin trend search; publishes successful_runs_count only on sanitized cards, zero for confirmed new trends, same count across multiple folders and pages. Legacy API unchanged.
- **Frontend:** compact success badge on each live tile and full successful-repeat count in detail. Never silently treat missing metrics as zero. Admin-defined folder order, prompt privacy, previews, links and repeat action retained.
- **Regression:** SQLite categories, pagination, admin search, zero, failed/pending/processing, duplicate task ID, signed HTTP privacy; React badge/modal tests and Chromium mobile category browser test. No charges, provider calls, or production DB writes.
- **Prior release gate:** PR 318 CI failed inside a synthetic bot-start-gate test because a deferred Playwright response.json lost its DevTools response body at 390px. The synthetic fixture now verifies its own recorded HTTP body/status independent of Chromium response-body caching and request cancellations, without changing application behavior. Required CI must pass before protected merge.


### 2026-10-15 — GitHub E2E cancellation robustness after PR #318 regression
- GitHub CI twice failed specifically in bot-start-gate.mjs: response.json raised Network.getResponseBody No data found for resource, after all prior E2E flows succeeded. Pre-reading response.json only shifted the failure.
- Synthetic bootstrap mocks now retain the exact HTTP body/status by Playwright Request WeakMap at route fulfilment; capability assertions correlate to requested capability check and fixture body. Null Playwright response after a subsequent intentional client abort is tolerated; actual app-gate visible/hidden, retry, delivery, and preserved draft checks still enforce the user-facing behavior. Other JSON responses in this fixture reuse the recorded response body; no production auth or delivery code is bypassed.
- Local Chromium test passes 320,375,390,430; live trend category browser test passed, including completed repeat badges. Counter singular/plural forms covered with React regression.
- Native protected GitHub CI required before auto-merge/deployment; no server state mutation.


### 2026-10-15 — source-aware video repeat authorization and protected Wan reroute
- Context: production PR #318 already shipped; users still saw a blanket author-permission error when repeating certain videos. All work on isolated tanyapi worktree, read-only production probes.
- Repro RED: focused pytest published_curated Wan fixture failed in build_repeat_plan on action_type=trend; React tests showed all generic submit/quote errors incorrectly latched repeatError. Tests later GREEN after fix.
- Live read-only evidence: 280 recent published completed videos, 33 ordinarily authorized Wan sources; one public Wan3 source generation (row id 315600) refused solely due to action_type=trend, but it records an integer original trend_id 2048. Curator trend 2048 is currently approved, public and has pinned complete Wan3 recipe. Derived owners must NOT sublicense inherited private input URLs or prompts.
- Backend: a completed publicly accessible Wan generation with action_type=trend, no source_feed_gen_id, and positive integer trend_id delegates a new repeat to the **currently approved curator trend plan**. Same model required; existing quote and launch transaction verify original trend hash, permissions, hidden source media and submitted replacements. Revoked original, malformed provenance, nested repeat/remix, model mismatch remain denied. No permission bypass or database changes.
- Frontend: if WAN repeat-plan returns trend_id for published feed source, editor transitions to canonical curated trend plan (clears inherited prompt/source_feed_gen_id), requires user uploads, quotes using original trend id/hash; explanatory copy is rendered. Generic video repeat only locks on explicit repeat_permission_changed; provider failure/network/price error no longer masquerades as author revoked permission, and preserves user draft. Unknown model gets distinct error. Missing/invalid private permissions remain fail-closed.
- Tests: 196 backend authorization/curated/transaction tests, 40 focused React tests, 11 Wan deep-link tests (stale mock updated), TypeScript and production Next.js build all green; Ruff, lint and diff check clean. Mobile browser E2E pending. No billable provider launch, no production DB updates.
- Release: PR against protected tanyapi; required GitHub CI, auto merge, production exact revision/health, read-only live published Wan derived source repeat check; verify admin price.json checksum unchanged. Real client acceptance after deployment still needed.


### 2026-10-15 — CORRECTION: publication permits repeating the published result
- **Owner clarification overrides prior issue #319 assumption:** if an author publishes a completed generation in the feed, that specific publication is repeatable. Being created from a trend, remix or prior repeat is *not* a blanket refusal. Earlier #319 auto-merged before the correction; hotfix directly follows it. All production probes read-only and implementation isolated in fresh worktree.
- **Correct identity:** repeat the actual clicked publication, with its own prompt edits, output settings and numbered reference slots; never silently reroute to its ancestor trend. For Wan, source_feed_gen_id in the returned public plan is the clicked child ID; source URLs and saved prompt remain exclusively on the server.
- **Reference policy:** publication enables repeat, while explicit per-input fixed/upload selections still control use of saved hidden media. A visitor uploads replacement files for upload slots. Revoked or unavailable selected media remain blocked before a provider request, with clear errors and refunds as applicable. No public media URL/prompt leakage.
- **Backend:** remove ancestor-only denial for Wan and typed Seedance/generic videos and old compatibility restore; preserve pre-charge immutable-plan/consent check. Telegram callback targets the published child itself. For image remix/feed and generate-image, eliminate old derived-only 403; preserve source recipe and explicit fixed-slot merge. On launch verify private media against the immediate published parent, while source_feed_gen_id retains lineage root for accounting/history. Unpublish blocks repeat.
- **Regression:** RED on published Wan trend/repeat/remix and revoked-ancestor reference cases under #319; green after changes. Added published child photo matrix, provider authorization checks for clicked child vs lineage root, Seedance/video callback + prompt/slot tests, Wan frontend source-plan tests. Browser/production build, combined suite and protected CI are release gates; no paid launch or production DB write.
- **Acceptance:** read-only production repeat-plan for real published Wan task 315600 must return *source_feed_gen_id=315600*, preserve the child settings and avoid trend_id fallback. Inspect whether user-upload slots are requested appropriately; then manual Telegram repeat, upload, quote and finished output in normal client.

- Auto-retry: persist the server-authorized immediate publication ID as private_repeat_permission_source_id in the child request snapshot and recheck it on failed-provider automatic retry. Retain source_feed_gen_id as the original lineage for history; old jobs without this field keep old behavior. The current child owner can revoke consent by unpublishing.

## 2026-10-20: owner-requested full rollback to October 18

- Request: roll back Tanya / NEUROMIX code from Git to October 18, 2026 after a Mini App startup incident; do not substitute another feature patch.
- Selected first-parent baseline: `63d6e8b2164de223f80ca950460c697e123237c1`, October 18 at 21:38:29 Europe/Moscow. Selection cutoff: October 19 at 00:00 +03:00.
- Pre-rollback production checkout: `5c733182d322758168f7c0f3290e7c7044eafeff`; running backend/frontend: `f1649adbaa2e2023023541556b883e7482a77f78`.
- All tracked application, frontend, test, schema and workflow files are restored byte-for-byte to the baseline. This ledger entry is the sole difference from that snapshot. Existing DB tables are NOT downgraded or deleted.
- Runtime tariffs (`data/price.json`), secrets, current DB/balances/payment receipts, user media and outputs must be preserved. No paid generation, mass message, financial correction or historical media maintenance is authorized by this rollback.
- Before changes: Git bundle, working diff, private config/runtime metadata, static snapshot and exported running-container filesystem are saved locally. The current running image has no local image entry, so a Docker rootfs export replaces an impossible image retag. Database backup remains mandatory before cutover. No private backup content is committed.
- Post-October-18 pending PRs #339 and #344 are paused as drafts to prevent reintroducing changes during rollback. #343 was already draft. No branch history is rewritten.
- Full rollback intentionally removes the smart-repeat rollout, optional extra-photo UI and forced Telegram-to-Mini-App handoff added on October 19, as well as the October 19 reference-query correction. This is not a claim that every earlier bug is fixed or that carrier connectivity is solved.
- Verification gates: exact snapshot comparison, protected CI, target build/frontend tests, DB compatibility/read-only in-flight-operation check, preserved runtime files, container/static/public revision agreement, backend health, full static asset delivery and browser startup smoke. Results pending at commit creation; exact evidence will be recorded in the release PR.


### 2026-10-20 — cautious disk cleanup after the 12-hour audit

- **Authorization:** Igor explicitly requested disk cleanup and inspection of all usage, preserving user/trend/repeat references. Delete only verified disposable caches or unused reviewed images; no databases, volumes, containers, uploads, outputs, references, source/worktree edits, recovery assets or backups are cleanup targets.
- **Baseline:** source `origin/tanyapi` = `0c6c7062045dc2a2cf9cdd5f21152bdecfb8efbd`; running backend = `c9cf187497c1d9725424bf300b78a27a33e04e02`, healthy, zero restarts. Isolated `agent/safe-disk-cleanup-20261020` task worktree; existing production price changes preserved.
- **Fresh audit:** before this task's deletion operations, free space already rose to 89,058,705,408 bytes (about 82.9 GiB), with 25 Docker images versus the previous audit's 100. The previously proposed three images are already absent, along with other images; that earlier freeing is not credited to this cleanup. Current runtime and named rollback image still exist. No image/container/volume prune is planned.
- **Plan:** (1) inspect top-level and project disk usage; (2) snapshot runtime/config/known persisted reference-file existence; (3) prune old unused BuildKit cache through Docker with recent-cache reservation, and clean verified npm/pip download caches when no installer is active; (4) verify actual free-space gain, all containers/mounts/recovery images, protected files, backend/public health/static/browser; (5) record exact actions and leave data/backup retention for separate work.
- **Verification/no-hardcode:** use fresh Docker references, official cleanup commands and filesystem measurements; no runtime business/config/schema/API/UI/FSM/provider/payment changes, migrations or paid tests. Guidance: Bambale0/skills diagnosing-bugs measurement-first, Bambale0/claw operational review checklist, anthropics/skills webapp-testing. Private evidence is stored only in mode-0700 `/tmp/neuromix-disk-cleanup-20261020`.
- **Actions completed:** old unused BuildKit cache prune (`until=24h`, reservation 10GB), npm `_cacache` clear, pip-tools/pip download cache purge, removal of 10 unused VS Code Server versions older than 60 days after process/FD/maps/mount checks. One immutable-protected old installation was preserved without removing protection; current/recent servers, settings and source code remain. No image/container/volume/data/media/log/backup deletion.
- **Space result:** available bytes increased from 89,058,705,408 (82.94 GiB) to 117,452,447,744 (109.39 GiB): **+28,393,742,336 bytes / 26.44 GiB**, df rounded 110G free/88% used. Earlier image removal performed before this task is explicitly excluded from this gain. Full disk-use allocation and retained areas recorded in [cleanup report](DISK_CLEANUP_2026-10-20.md).
- **Protection evidence:** PostgreSQL read-only snapshot covered 47,225 saved refs, 26 trend assets and 1,492 audited task snapshots. All 44,048 existing referenced files remained present with identical size/inode/mtime; 3,821 already-missing paths are not attributed to cleanup. All 41 containers retained image/start/restart/mount state, protected current/recovery images exist, runtime `.env`/price hashes match. Backend/public health, same exact backend/Mini App SHA, runtime pip check and published mocked mobile browser smoke passed. Existing reference/recovery/financial audit findings remain follow-ups; no paid generation or business mutation. Documentation diff/privacy review and PR are the remaining delivery steps.

### 2026-10-20 — restore administrator-only trend repetition statistics
- **Baseline:** `cab455f1cfdb50c508c2550569213eb7ca6d906c`, matching running container and published Mini App revision. Dedicated worktree; production checkout and mutable price.json are not edited.
- **Report:** ordinary Mini App users see green successful-repeat badges; statistics must remain administrator-only.
- **Root cause:** PR #318 (`f3f38525`, October 15) added unconditional metric enrichment in list_catalog/category_page and unconditional badges/detail counts in TrendShowcase. The October 18 rollback contains that implementation. Not a user accidentally receiving administrator privileges.
- **Related exposure:** legacy prompt list injects the same count into description; public serializer and Telegram caption currently retain it. Protect these read surfaces too without changing collection, calculation or generation paths.
- **Plan:** (1) reproduce non-admin exposure in role-specific tests; (2) default-deny DTO and UI metric visibility using existing verified config.is_admin / bootstrap user.isAdmin; (3) preserve admin completed-only counts, category paging, prices/new badges/repeat links; (4) tests/build/browser E2E; (5) protected PR to tanyapi, exact-SHA autodeploy and production read-only/browser verification.
- **Scope:** no schema/config migration; no counter reset, provider request, billing, balance, reference or repeat-flow change. Legacy authored descriptions remain intact except the known system-added counter prefix. No new admin flag or hardcoded production user IDs.
- **Verification plan:** signed catalog/category HTTP for admin/viewer (including forged body admin flag), public legacy DTO and Telegram captions, React shelves/pagination/detail/role change/stale metrics, mobile Chromium, TS/build/lint. Implementation and final release evidence follow below.

- **Red reproduced:** before implementation, five backend regressions failed (viewer catalog/DTO/legacy caption) and two React regressions failed (viewer and role-revocation displays). Admin positive controls passed. Exact logs on host: `/tmp/tanya-trend-counter-red-{python,react}-20261020.log`.
- **Implemented:** administrator-only successful metric enrichment; copied public trend DTOs omit accepted/success counters and exact generated legacy description prefix; signed admin shared-detail retains stats while still hiding recipe; Telegram caption uses the same default-deny policy. Explicit bootstrap role passed to every shelf/page tile and preview. Non-trend prompt statistics unchanged.
- **Initial local verification:** 106 backend tests passed across catalog, signed API, legacy/shared-link privacy, Telegram captions, metric invariants and reference/privacy regressions. 26 Jest tests passed (showcase + repeat-cost + share-link); tsc and production build passed. Mobile Chromium category E2E passed for viewer/admin, paging, preview, role change, prices/new badge, repeat and admin actions. Ruff and changed runtime TS lint passed (test file is excluded by the existing ESLint configuration). Extended critical browser suite was still running at this checkpoint; its completed result is recorded below.
- **Review:** no statistics/balance/schema/provider writes, no mutable production data staged, only existing server config.is_admin and verified bootstrap role. Data is copied rather than mutated across roles; missing metric stays absent, admin confirmed zero remains visible. Rollback-era generation and upload architecture retained.
- **Initial release checkpoint:** ready for a dedicated PR into tanyapi and protected CI; deployment was not yet claimed. GitHub connector could not read branch-protection admin metadata (403); no attempt to change protection or bypass required checks.

- **Full CI follow-up:** first PR #346 run `39479777081` exposed an isolated AST test loader omitting the newly introduced real sanitizer helper, causing `NameError` in `tests/isolated/test_wan_public_trend_marker.py` (12 subtest failures; 3,869 other tests passed). Added the actual helper declaration to the isolated loader; no fake implementation or weakened expectation. Strengthened both WAN variants and signed shared-detail tests with administrator-only counter assertions. Runtime code unchanged by this test-harness follow-up. Native merge was held until complete green CI, then completed as recorded below.
- **Production baseline reproduction:** read-only catalog service in the deployed container returned counts for all 87 viewer cards and all 3 sampled category-page cards. The same diagnostic checks PostgreSQL transaction_read_only and replaces only startup schema-creation hooks in its disposable process; no database mutation, no real user authentication/profile changes, no provider call.

#### Final release verification — 2026-10-20

- **Merged release:** [PR #346](https://github.com/Bambale0/banano_kling/pull/346), native squash auto-merge to `tanyapi`, exact merge SHA `c9cf187497c1d9725424bf300b78a27a33e04e02`. All four mandatory gates passed for that SHA in [CI run 39483820025](https://github.com/Bambale0/banano_kling/actions/runs/39483820025): Python/deploy validation, safe regression suite, Mini App browser E2E, production Docker image.
- **Completed local checks:** final focused backend/privacy/reference run passed 110 tests and 13 subtests. The complete `critical-flows.mjs` run, including imported suites, exited 0 in 207 seconds; its earlier 180-second timeout was not counted as success. The 26 Jest tests, TypeScript, production static build and focused lint checks above passed.
- **Autodeploy recovery:** the initial deploy stopped before replacing the container because free disk space was below the existing 10 GiB minimum. Reclaimed 5.211 GB of Docker build cache older than 24 hours with a 20 GB reservation, then reran only the failed GitHub deploy job. No minimum-space guard was lowered; no runtime data, images, volumes, media or backups were deleted.
- **Production deployment:** [deploy run 39483820089](https://github.com/Bambale0/banano_kling/actions/runs/39483820089) succeeded on 20.10.2026 at 22:57 MSK (19:57 UTC). Production checkout, healthy backend container revision and public Mini App `revision.txt` all matched the exact merge SHA. Public backend `/health` returned HTTP 200/status ok; restart count 0, OOM false.
- **Real database acceptance:** the deployed catalog service, with PostgreSQL-enforced read-only transactions, returned successful/accepted counters on 0/87 viewer cards and 0/3 sampled category-page items. Administrator successful counters were present on 87/87 cards and 3/3 sampled page items, including 22/22 sampled Seedance 2.5 catalog cards. Roles were passed explicitly to the service; this was not an authenticated real-user HTTP session. The same assertion failed against the previous container with `Viewer catalog leaks repeat counts`, then passed after deployment.
- **Published frontend acceptance:** mobile Chromium against the real published static app passed viewer/admin tiles, paginated category, preview, role change, repeat and admin-history checks. Application API responses and media were synthetic; no real user data, paid generation or production mutation was used. The same browser check failed against the previous published app.
- **Verification commands:** `cat /tmp/tanya-trend-counter-readonly-acceptance-20261020.py | docker exec -i banano-kling-bot python -`; from the task frontend worktree, `TREND_SMOKE_ORIGIN=https://tanyapp.xn--e1aikcel5c5a.online node .artifacts/trend-counter-deployed-smoke.mjs`. These host-local diagnostic artifacts are not versioned; permanent regression coverage lives in `tests/test_trend_catalog.py`, `tests/test_trend_catalog_api.py`, `frontend/miniapp-v0/__tests__/trend-showcase-categories.test.tsx` and `frontend/miniapp-v0/e2e/trend-category-showcase.mjs`.
- **Runtime preservation/telemetry:** `.env` and runtime `data/price.json` hashes matched the pre-retry snapshot; predeploy PostgreSQL/application backups were retained. At the post-restart audit point: 688 log lines, 0 ERROR/CRITICAL, 0 tracebacks, 0 trend-link failures. No schema migration, new configuration, admin setting, provider/payment/balance change or manual runtime code patch.
- **Guidance used:** `Bambale0/skills` diagnosing-bugs (red/green evidence), `Bambale0/claw` PR/FSM checklist, `anthropics/skills` webapp-testing (published-browser role verification).
- **Follow-ups/limits:** about 13 GiB free at the release audit; capacity monitoring/retention remains separate work. Physical Telegram/iOS acceptance and historical Seedance 2.5 count completeness were not verified. Rollback remains a PR revert through `tanyapi` CI/CD.

### 2026-10-20 — production audit: last 12 hours and Docker image removal candidates

- **Request/scope:** audit production health/errors for 2026-10-20 08:14:50–20:14:50 UTC (11:14:50–23:14:50 MSK); identify old images that can be removed without affecting user, trend or repeat references. Inspection only: no image/container/volume/media deletion, no financial/provider mutation or live generation.
- **Baseline at audit start:** `origin/tanyapi` and backend revision `c9cf187497c1d9725424bf300b78a27a33e04e02`; isolated `agent/project-audit-12h-20261020` worktree. Existing runtime price changes remain untouched. During the audit, documentation PR #347 merged as `0c6c7062045dc2a2cf9cdd5f21152bdecfb8efbd`; this report was rebased onto it while preserving both ledger entries. Runtime findings refer to the audited application SHA above.
- **Preflight:** application file logs cover the whole requested window; Docker logs cover only the latest container restart. Production media/data/logs/backups/outputs are host bind mounts; inspect all container references, image labels, old image contents and rollback tags before classifying removal candidates. Shared host also runs other projects, which remain out of cleanup scope.
- **Flow/guidance:** evidence-first diagnosing-bugs from Bambale0/skills; technical/QA checklist from Bambale0/claw; anthropics/skills webapp-testing for browser smoke. This bounded operational audit does not require a cross-session wayfinder map.
- **Steps:** (1) timestamp-correct error grouping and impact correlation; (2) read-only task/payment/reference invariants; (3) health/static/auth/browser and infrastructure/CI checks; (4) image-to-container/layer/rollback inventory; (5) sanitized report with exact candidates, limitations and follow-ups.
- **Acceptance:** full 12-hour coverage stated; production errors separated from tests/expected failures; no secrets or private log payloads committed; candidate images explicitly exclude active/stopped-container references, current release, rollback assets and other projects; protected data untouched. No schema/API/UI/FSM/config/admin/provider/payment change is planned.
- **Completed audit:** [sanitized report](PROJECT_AUDIT_12H_2026-10-20.md). Full application-log coverage: 227,172 events, 52 ERROR (25 moderation, 5 other provider, 11 upload reset, 3 Redis timeout, 4 analysis, 2 Wan ratio, 2 Telegram blocked); no CRITICAL. Nginx refused clusters match two release cutovers. No code fixes, retries, refunds or cleanup performed.
- **Database/reference evidence:** PostgreSQL enforced read-only; 1,492 window-created tasks (1,408 completed, 84 failed), no completed task without result, no negative balances/completed duplicate payment keys/orphan ownership. 78 explicit failed-task refund markers; three positive-cost fast failures lack durable refund evidence, not proven financial loss. One stale Wan task from October 14. All 1,278 unique local task-input files in the window exist. Separately, 3,817 saved-ref records created May–June and four unique files in five trend-asset rows are already missing; two affected templates are public. No restoration or deletion attempted.
- **Docker evidence:** all 99 images and 41 containers inspected at snapshot; three unused NEUROMIX test/legacy images (`851d3714e61a`, `c96d121087eb`, `f39b708c6851`) have approximately 5.23 GB unique image data. All 7 layers per candidate inspected read-only: no uploads/output/backup files or nonempty DB files. Current image, both named recovery images, stopped-container dependencies, other projects, volumes and host media remain protected. The report's explicit non-force image-removal command is a proposal and was not executed.
- **Verification:** local/public health and exact backend/frontend revision passed; Redis PING, nginx syntax, production pip check, both TLS certificates, 8/8 current static assets and unsigned API rejection passed. Published mobile Chromium role/category/repeat/history smoke passed with synthetic APIs/media. Existing exact-SHA four-gate CI success verified; no paid smoke/full test rerun. Documentation-only diff/path checks and PR are the final delivery steps. Raw evidence is local in mode-0700 `/tmp/neuromix-audit12h-20261020`; no secrets/user URLs/DB rows staged.
- **Final capacity/candidate recheck:** free space fell from about 12 GiB at the initial snapshot to 8.2 GiB (df: 100%), below the unchanged 10 GiB deployment floor; the cause of that change was not established. All three candidate images still exist and have zero references across all containers. Backend remained healthy at `c9cf1874` with restart count 0 and the same protected bind-mount destinations. No deletion performed. Audit documentation PR #348 targets `tanyapi` with native squash auto-merge enabled; required CI remains enforced.


## 2026-10-21 — Runtime incidents: recovery, uploads, assistant and payment audit

- Baseline: `bf5e8a1c21d00178f657cee83a9ffd738e437ecf`, current `origin/tanyapi`; dedicated worktree/branch `fix/runtime-reliability-20261021`. Production price.json is modified administrative data and is excluded from work.
- Result: temporary infrastructure/client failures recover without permanent FSM degradation; assistant audio uses a verified supported adapter configuration; missed Lava notifications are checked against provider state; deployed production SHA and smoke are verified.
- Audit: 22 ERROR records, six HTTP 500 responses on 2026-10-21 00:00–06:40 UTC. apt-daily-upgrade restarted PostgreSQL/Redis at 05:53; both recovered. FSM fallback is permanent. Wan chunk disconnect becomes 500 while generic Mini App upload already maps it to 499 and supports JSON fallback. Telegram reference download has no retry; periodic dump ignores RetryAfter. Audio submits retired PHOTO_PROMPT_MODEL to /codex/v1/responses. Lava rejects 102 events (eight success) from undocumented source, existing provider-verification/idempotent completion and periodic reconcile can be reused. Public production health/static TLS currently pass. Two unrelated/shared certificate renewals failed; inspect ownership before changes, do not modify dev branches/services.
- Existing/partial/missing/reuse: reuse HTTP boundaries, upload fallback, public storage API, atomic payment completion, Lava binding/reconcile, safe Telegram transport; add recovery and bounded retries rather than rewrite flows.
- Risks: FSM recovery must preserve fallback writes and not resurrect cleared state; upload disconnect cannot be repaired server-side and needs bounded client retries; never trust unknown webhook source or grant balance from callback alone; no production test fixtures or private media exposed. Migration: none expected. Mutable provider choices stay typed env/config, not hardcoded replacements. No prices/referral economics change.
- Public test seams: BaseStorage state/data across outage and recovery; aiohttp upload route/error contract; assistant service with synthetic audio/provider responses; Telegram media/send seam; Lava invoice verification and atomic replay tests; actual provider read-only invoice audit; public deployed health/revision.
- Observability: record fallback entry/recovery and migrated-key counts, attempt/status/error class for retries; no bodies/secrets/audio. Financial audit prints only aggregate counts, private audit artifacts stay outside Git.
- Steps: (1) reproduce each bug with focused regressions; (2) FSM recovery; (3) upload transport and Telegram retries; (4) audio contract/model verification and config; (5) Lava read-only reconciliation and authenticated delivery remediation; (6) applicable cert renewal diagnosis; (7) focused + safe regression/lint/deploy checks and independent standards/spec review; (8) PR to tanyapi with native squash auto-merge, four protected gates; (9) exact merge-SHA CI/autodeploy, health/static and focused smoke/telemetry.
- Acceptance: focused regressions red then green; state/data survive fallback recovery and clear; interrupted uploads no longer 500 and valid retry works; real synthetic audio yields response; actual provider-paid invoices credited once, no unverified credits; production exact SHA verified, no new related server failures during observation.
- Verification layers: unit/domain, Telegram FSM, Mini App API, retry/idempotency, provider contract, payment DB audit, deployment and telemetry apply. No schema migration; admin/security checks focus on payment verification and unchanged owner-scoped uploads. Browser upload seam applies if client code changes; no unrelated UI redesign.
- Rollout: normal PR/CI/autodeploy only, reversible runtime config backed up outside repo; rollback via protected revert PR preserving runtime prices/data.
- Skills: Bambale0/skills diagnosing-bugs, tdd (existing repository-authorized public seams), code-review; Bambale0/claw PR review checklist; anthropics/skills webapp-testing where browser verification applies.
- Progress: public FSM regressions failed before the recovery implementation, including preservation of existing fields across fallback update; Wan HTTP transport failed 500→expected499 and three browser-library chunk regressions failed before implementation. These seams now pass; additional retry tests cover explicit Telegram flood rejections, bounded read retry and no ambiguous send replay. Audio public HTTP seam failed against the retired Responses route; final OpenRouter chat seam covers configured model, inline bytes, retries and non-leaking permanent errors.
- Provider evidence: KIE's retired model returned404; supported Codex replacement explicitly rejects audio400. Gemini KIE chat/native probes did not reliably accept speech. Existing OpenRouter credential + `google/gemini-3.8-flash` accepted the synthetic spoken phrase and transcribed exactly “The secret word is purple pineapple.” No private user recording was used or published. Final implementation uses this verified OpenRouter contract, not the failed probes.
- Payment evidence: authenticated read-only provider comparison found 36 local pending/provider in_progress and two fresh pending/provider failed; provider list of 100 final invoices matched all 33 completed and 67 failed locally. No provider-paid/local-uncredited item in the sample; no manual credit/SQL mutation. Sender 158.160.251.222 is observed in production callbacks but not the published IP documentation; retain strict sender configuration and independent verification.
- TLS: production backend and current Mini App certificate renewals both passed `certbot renew --cert-name <production-name> --dry-run --no-random-sleep-on-renew`. Igor explicitly excluded DEV/other domains, so shared Certbot failure from those renewals is an out-of-scope host finding, not a NEUROMIX certificate failure.
- Scope extension: Igor supplied a wrong-person Seedance 2.5 repeat and clarified: repeat = author's prompt + consumer's replacement references. Production DB snapshot and authenticated provider task lookup both confirmed an author-owned image path in a foreign repeat with no private-use grant. No private customer identifiers/URLs are committed. Original prompt/slot order must remain; no generation or debit for missing consumer files.
- Privacy fix: the authenticated Mini App boundary converts absent/legacy foreign consent to replacement-only consumer slots without changing stored publication settings. It never invokes the legacy auto-restoration branch for that consumer. Public descriptors require the corresponding uploads. Owners retain their own editable recipes; explicit separate fixed-slot grants keep their validated behavior. Telegram foreign legacy repeats redirect to this same flow; missing-parent derivatives fail closed. Seven new public regression cases initially failed; expanded privacy/repeat/provider/identity tests verify own replacements, partial rejection, forged ownership, prompt composition and before-charge checks. Old tests that treated reference visibility as implicit reuse are revised to require explicit consent or consumer replacements.
- Review findings addressed: actual Mini App bootstrap catches DB errors before outer middleware, so the shared safe 503 classifier is now inside its real error seam too. FSM calls and recovery batches now have finite deadlines/socket timeouts; migrated keys retire incrementally so a large queue drains across deadlines. Both issues reproduced with regression tests before the follow-up fixes. Missing-parent Telegram bypass reproduced and blocked. Independent Standards reviewer retracted its Lava legacy-discovery concern after confirming the installed authenticated discovery wrapper.
- Local checks in progress: focused base set 29 passed; expanded repeat/identity/Telegram/media set reached 299 passed with one outdated synthetic request harness, which was corrected to exercise normalized JSON and the independent receipt seam. Frontend upload/cancel/API tests: 44 passed. Production static frontend build and TypeScript passed. Video browser contract passed 320/390/430 px; replacement-only legacy case added for final browser/CI verification.
- Test environment: host Python venv lacked required pypdf. Installed pypdf 6.21.1 only into a private QA dependency directory and created an isolated QA venv referencing existing dependencies; production venv/container unchanged. Initial full-suite collection/dependency failures and a run concurrent with test updates are not counted as passes. Final exact-head full suite/CI remains required.

- Final local verification: complete safe Python suite passed **3901 tests, 76 subtests**, with 113 skips (live smoke excluded); final focused runtime/reference/payment slice passed 116 tests. Final frontend upload/reference/identity Jest slice passed 60 tests. TypeScript, production static build, changed-line Ruff (0 relevant violations) and `git diff --check` passed. Complete critical browser suite exited 0, including its imported journeys. Video reference-slot browser suite, including replacement-only legacy repeat, passed at 320/390/430 px.
- Independent code-review/spec-review completed against `7cd6f01a`: no remaining blocking findings in reviewed scope. Both bootstrap 503 and missing-parent Telegram findings are covered by regressions; finite FSM recovery also reviewed.
- Release checkpoint: [PR #350](https://github.com/Bambale0/banano_kling/pull/350) targets only `tanyapi`; native **squash** auto-merge is armed. Branch protection was verified strict with all four required CI gates. This ledger checkpoint precedes exact-merge CI, autodeploy and production smoke; final release evidence will be attached to the PR and delivery report after verification.
- Configuration status: no schema migration or runtime price changes. New retry/recovery/audio settings use documented environment overrides and safe defaults. Production Lava sender admission has not been broadened: the new observed sender is absent from published provider documentation, so Igor has been asked specifically about this trust-list change. Independent authenticated invoice checks remain mandatory either way. DEV/other-domain Certbot failures remain outside Igor's explicit production-only scope.

### 2026-10-21 — publish and repeat completed original/trend/repeat results

- Baseline: `f8189f0d16d994dcb907ef8344789e29b8d4064e` on current `tanyapi`; dedicated `fix/own-photo-publication-20261021` branch. Previous runtime PR #350 has merged; exact-release CI/autodeploy is still pending, so production updates are not yet claimed.
- Igor's explicit behavior: every user can publish their completed original, trend and repeat results to Feed/Profile; every viewer can repeat published results using the selected result's server-side recipe and their own files. Privacy of executable recipes and inherited author references remains independent from publishing the output. Ownership/completion, real media availability, authentication and deterministic billing still apply; no role/model/source-origin ban on publishing a valid owned result.
- Fresh evidence: reported original image has no source/parent/action provenance. A later approved trend by the same author has identical prompt text, so legacy text matching wrongly hides the author's own prompt and the UI removes publishing. Independent audit also found source-lineage rejection in `share_to_feed`, hidden-prompt UI gating, and private Genjutsu result publication rejection. Existing multi-hop image/video repeat services can reuse the selected published result's recipe, but all relevant lineage/reference/permission seams must be verified.
- Reuse/risks: preserve existing publication API, media persistence, visibility scopes, root/immediate-parent lineage, private-reference grant validation and before-charge checks. Explicit private/trend markers continue to redact prompt/media. A descendant cannot grant inherited author files to others. No SQL correction of historical tasks, migration, price/provider/referral change or paid generation is planned.
- Steps: (1) reproduce owned prompt false-positive plus original/trend/derivative publication/repeat failures; (2) separate output publication capability from private-recipe disclosure in backend and UI; (3) preserve selected result's hidden recipe and require consumer reference replacements for repeated publications; (4) verify Telegram and Mini App photo/video/recipe flows, public cards/deep links and revocation; (5) independent code-review, focused/full regression, browser/build/lint; (6) protected squash-auto-merge PR to tanyapi, exact-SHA CI/autodeploy and production read-only/browser/telemetry verification.
- Acceptance: own completed original/trend/repeat output can publish to both scopes without admin privileges, public result repeats work for another user with own references, missing consumer inputs fail before billing, no private recipe/reference disclosure, explicit denials on private inputs cannot be overwritten by client flags. Nonowners cannot publish another user's task.
- Verification layers: domain/DB, signed API/Telegram callbacks, browser UI, provider payload/lineage, billing/retry regressions and production smoke apply. No schema migration/config flags needed: this removes inconsistent source/role restrictions from existing capabilities. Playbooks remain current: diagnosing-bugs → TDD → two-axis code-review; Bambale0/claw checklist; anthropics webapp-testing.
- Related operational authorization: Igor explicitly approved both Lava sender IPs with mandatory provider-API verification. Production `.env` now contains the documented and observed sender; a mode-0600 backup is retained outside Git and unrelated settings are unchanged. The running container will receive it through normal autodeploy. No financial mutation was performed.

#### Runtime release #350 verified before the publication follow-up

- Native squash merge `f8189f0d16d994dcb907ef8344789e29b8d4064e`; [exact-SHA CI 39569171069](https://github.com/Bambale0/banano_kling/actions/runs/39569171069) and [normal autodeploy 39569171056](https://github.com/Bambale0/banano_kling/actions/runs/39569171056) succeeded. Production checkout, healthy backend revision and public Mini App revision matched. Public health returned 200/ok; backend restart count 0/OOM false. Publication follow-up changes are not included in this release.
- Deployed guard evaluated the reported incident's actual stored source under a PostgreSQL read-only connection: missing consumer files rejected, supplied synthetic consumer file exclusively retained, author prompt preserved; no provider generation, debit or customer data mutation.
- Deployed assistant service transcribed synthetic Telegram-format OGG exactly: “The secret word is purple pineapple.” Verified live OpenRouter audio contract via the actual new service.
- Deployed payment audit: authenticated GET of 100 recent invoices matched 34 provider/local completed and 66 provider/local failed; zero final-state mismatches. The container now admits both explicitly approved Lava sender IPs while retaining independent invoice checks and idempotency.

- Requirement clarified further by Igor: “тренды, повторы выложить и повторить может каждый”. Removed source-origin publishing/list restrictions across Mini App, Telegram compatibility and ordinary DB services, while retaining ownership, completion, result availability and hidden-prompt export boundaries. Private Genjutsu result publication creates a server-only replacement contract for all source/photo slots; inherited fixed assets are not transferred.
- Red evidence: the reported own-author prompt match failed its owner HTTP detail regression; private Genjutsu output publication returned 403; the private-run browser component had no publication control. New public photo-repeat cases also exposed empty-input billing eligibility at the Feed endpoint; it now requires consumer input when the source has reference slots, before debit/provider submission.
- Review follow-ups: private video owners now receive replacement descriptors and use the same authenticated replacement contract as other consumers. Explicit selection of their own existing saved local photo is permitted; ownership comes from trusted local upload identity plus authenticated context, never a body flag or an external URL lookalike. Private profile photo repeats no longer silently restore inputs on an empty request.
- Legacy privacy is classified in batches for Feed/Profile card reads, publication/grant validation and authenticated repeat source snapshots. Classification annotates copies with top-level `private_recipe`; it preserves dictionary/JSON request-data representation and does not rewrite historical source metadata. Author's ordinary originals are exempt from legacy text matching; explicit private/trend/lineage markers still win. The shared backend connection configuration is used in these reads; obsolete isolated-test path monkeypatches are removed.
- Latest targeted checks: **439 Python tests passed** across publication, hidden recipes, photo/video repeats, private grants, Genjutsu and trend referral links. **19 frontend tests passed** across publication controls and image/video repeat surfaces; Next static build and TypeScript passed. Complete mobile reference/repeat browser suite, now including private-result Profile publication, passed at 320/390/430 px. Earlier full safe run passed 3918 tests/76 subtests; a later run exposed ten obsolete test-fixture path monkeypatches, which are corrected. Final exact-head full suite and protected CI remain release gates.
- Config/migration/finance: no schema migration, new business flag, price/balance/referral mutation or paid customer generation. No publication permission is inferred from hidden prompt state. Final release evidence will be recorded on the task PR and delivery report after protected autodeploy and exact-SHA production verification.

- Final Telegram review closed owner shortcuts in old quick-photo confirmation, stale photo launch, parentless private-trend video and published Wan child callbacks. Private owners choose their own inputs just like other consumers; local aliases cannot bypass inherited-media filtering. The clicked published child remains the repeat target. Ordinary original-owner editing is preserved. Added public callback regressions; updated eight obsolete derived-owner expectations that previously required inherited fixed inputs. Targeted Telegram/photo/reference/Wan slice passed 166 tests before the final context guard; full current-head regression is rerun below/CI.
- Final targeted callback/reference/provider/permission regression: **224 passed**. New private-trend callback regression traverses central image launch, mocked provider, persisted successor and HTTP task detail: only the consumer photo is submitted and recipe privacy survives without a published source. Automatic retries retain original grant revalidation independently of new-repeat input replacement. Full final suite and protected CI remain pending.
- Both final review axes confirmed no remaining high-severity issues in application head `5f5949aefbbe69d82399766a7a1ec3a465b2b9c9`. Complete regression exposed six further obsolete expectations/harness assumptions: private child editor now starts with empty inputs, explicit new consumer files no longer depend on ancestor fixed-grant revocation, quick confirmation reopens selection, and an ordinary Seedance owner test now mocks the authenticated source lookup instead of bypassing it. Updated those tests; the affected legacy runtime/Seedance/rendergrid/admin slice passed **60 tests**. Application code is unchanged by this test follow-up. Final full safe regression and protected CI are rerun on this commit.
- Fresh runtime review found no HTTP 5xx or Redis memory fallback after runtime release #350. One real Grok provider content rejection was reconciled: read-only DB evidence confirmed failed status and atomic refund marker for its 9-credit cost. Invalid-signature Prodamus callbacks remain rejected. No manual financial mutation.

### 2026-10-21 — mobile Wan photo upload fails before any chunk

- Baseline: current tanyapi `8a19d75813d2b28d17c4075fc9158abf27a108e2`; isolated `fix/wan-photo-upload-20261021` branch. Production runtime prices remain administrative state.
- Evidence first: screenshot's exact filename correlates with repeated owned upload sessions over several days: init succeeds, received_chunks=0, no complete/image-validation request, then cancel/expiry. Current Samsung Android WebView repeats this even with a 184 KB JPEG; image/model limits cannot explain a failure before bytes arrive. Some init responses are also lost after proxy timeouts; existing durable same-ID reconciliation/cancellation must remain intact. Other photos/users complete normally. Generic multipart boundary/reset failures are separate observed transport events.
- Current seams: Wan image upload opens a server reservation before FileReader touches the original picked File, and the form clears the native input before starting async upload. Android content-provider File handles can become unreadable across asynchronous work; Chromium issue 40123366 documents this family of failure. The form currently exposes only a generic error, and Wan lacks client stage/correlation telemetry.
- Preflight/risks: reuse owned init/chunk/complete/cancel, limits, auth, quotas, local JPEG validation fallback and existing MediaField. No provider/schema/payment/pricing change. Preserve explicit cancellation, cleanup fencing, stale source resets, and no launch/debit on missing media. Cache only provider-bounded image bytes before network waits; video/audio/document streaming stays bounded by existing chunk protocol. Native input must stay valid during reading/retry. No customer data export or paid generation.
- Steps: (1) add a deterministic public upload regression with a native-like file whose original handle expires once network work begins; (2) snapshot valid image bytes before init, preserve input lifetime, and maintain cancellation/deadline semantics; (3) add privacy-safe client stage/upload-ID diagnostics; (4) focused upload/cancel/form/browser tests, full safe Python and frontend build/types/lint, two-axis review; (5) protected squash-auto-merge PR to tanyapi, exact-SHA CI/autodeploy and production upload smoke.
- Acceptance: delayed native-file lifetime regression uploads the exact image bytes; no reservation is created for unreadable/aborted input; successful and cancelled/failed cleanups keep existing invariants; repeat Image1 is selectable/uploadable without losing user replacements; source privacy and before-charge guards remain intact. Production probes use synthetic files and no generation/balance mutation.
- Playbooks: current Bambale0/skills diagnosing-bugs/TDD/code-review; Bambale0/claw checklist; anthropics/skills webapp-testing. Unit/domain, signed upload API/DB, frontend/real-browser transport, auth, cancel/idempotency, deployment and telemetry apply. Provider generation, schema migration and financial mutation are not required by this upload-only fix.

- Reproduced red/green: a public upload test expires the original native-like handle when init begins; baseline fails `NotReadableError`, updated code uploads exact bytes from its owned memory File. Images are prepared together before network work and retained through JPEG fallback/manual retry. Input reset moved before opening the picker and after confirmed success. WeakSet tags prepared files without a strong global cache; existing 20 MiB/image and field-count limits bound memory. Videos/audio/documents keep chunk streaming.
- Telemetry: safe client upload stage, validated 32-hex upload ID, error code, size, status and duration; no photo bytes, original filename, auth or provider detail added. Malformed stage/ID inputs are regression-tested. No schema/config/admin/economic migration.
- Verification checkpoint: full safe Python `pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short` passed **3954 tests + 76 subtests**, 113 skipped. Focused telemetry/cancel/quote/mobile upload passed **46 tests**; focused frontend upload/form/cancel passed **64 tests**. Next production export and TypeScript passed. Wan browser passed all ordinary/Prime modes plus native-handle expiry with two exact-byte photos and zero generation calls. Complete repeat/reference browser passed 320/390/430 px.
- Broader frontend review corrected asynchronous fixture waits. A separate baseline checkout confirms two existing publisher-test failures: synthetic 400 entered unmocked JPEG recovery, and stale preview expected an error after mode reset invalidated its attempt. Retry test uses 503; stale-preview test checks no restored media/raw error and disabled publication. Dedicated JPEG fallback regressions remain. Native-picker browser coverage is now imported by the existing mandatory critical browser CI gate.
- Both code-review axes found no remaining blocking issues; final narrow test/harness review also passed. Actual Samsung hardware confirmation remains outstanding: session evidence and deterministic browser reproduction establish the handled failure mechanism, not direct observation on that physical phone. Protected PR, exact-SHA CI/autodeploy, published-asset smoke and final release evidence remain mandatory; final evidence will be attached to the PR/delivery report.
- Final local frontend: all **67 Jest suites / 531 tests passed**; changed runtime TS ESLint passed; build and final `tsc --noEmit` passed. No unresolved application/test failure remains.

### 2026-10-21 — restore Studio access to older bot-published videos

- Baseline current tanyapi `3a47eabd8b5b48be6e16e0dc11525d258653e97f`; isolated task branch `fix/studio-history-reference-settings-20261021`. Preserve live administrative `data/price.json`.
- User outcome: works beyond the eight bootstrap cards remain reachable in Studio; an older video published through Telegram reopens the existing owner publication/reference editor. No regeneration, publication removal or financial mutation is needed. User-specific account/task identifier requested asynchronously; no identity guessed.
- Evidence/preflight: production bootstrap logs show successful requests; `_fetch_recent_tasks(limit=8)` and TaskHistoryList have no older-history route/control. Existing signed task detail, owner reference controls, publication/grant saves, protected-task sanitizer and Telegram-created generation rows are reusable. Genjutsu has a separate run history and stays excluded. Review README, agent docs, user flows, QA ownership invariant, model/DB schemas, task and publication UI/API, tests and current production CI/deploy.
- Ranked hypotheses: (1) bootstrap window hides older rows; (2) publishing changes eligibility; (3) records/results were removed. Public signed pagination/detail regressions distinguish these: 19 same-timestamp owned tasks plus foreign/dedicated history rows, an older bot-publication with own refs, foreign cursor/forged actor/invalid auth. Client regressions exercise load-more, refresh persistence, retry and auth-switch cancellation.
- Plan: (1) red public HTTP/React reproductions; (2) owner-scoped keyset paging with existing serializer/privacy boundary and stable timestamp/id ordering; (3) load-more with bounded per-page transport, dedupe, refresh retention and stale-owner cancellation; (4) signed API/DB/privacy, editor and mobile browser tests, full safe suites/build/type/lint, two-axis review; (5) native protected squash auto-merge PR to tanyapi, exact merge-SHA CI and normal autodeploy, published-asset/read-only production acceptance.
- No-hardcode/schema: eight items is the existing initial transport page, not a user-history/business cap. Paging has no maximum total history; no new mutable business setting or schema migration. No provider request, price/balance/refund/referral or consent mutation. No automatic changes to a customer's reference choices.
- Observability: route logs authenticated owner, returned count, continuation presence/duration; no prompt/reference URL/auth contents. Existing request IDs/access logs and task IDs remain. Acceptance: all old owned rows reachable once in stable order despite tied timestamps/new inserts; foreign cursors cannot select foreign records; missing/deleted/foreign anchors identically restart the owned head; hidden recipes stay hidden; old bot-published detail retains existing authorized reference editing; refresh/account changes do not drop pages/leak data.
- Playbooks refreshed: Bambale0/skills diagnosing-bugs/TDD/code-review; Bambale0/claw engineering checklist; anthropics/skills webapp-testing. Provider/financial write and migration tests are inapplicable because this is an authenticated read/accessibility fix; existing editor save/ownership/privacy regressions remain required.
- Red/green evidence: baseline signed HTTP lacks the history route; rendered Studio has no Load more control after eight tasks. New signed HTTP regressions pass for 19 tied-timestamp owned tasks, new inserts, older Telegram-style publication/own references, invalid auth, forged actor fields, foreign/stale/deleted cursor recovery and hidden recipes. Frontend load/open, dedupe/refresh, retry, owner-switch cancellation and confirmed older pending→completed/publication state pass.
- Review follow-ups closed: per-page 10s deadline (same technical read budget as existing pending-detail resolution), caller cancellation and retry even when transport ignores abort; merged confirmed selected-task details into cached older cards, without adding a poll per historical card. Deleted cursor safely restarts the authenticated owner's head; duplicate cards are merged.
- Current checks: full safe Python **3958 passed + 76 subtests, 113 skipped**; all frontend Jest **69 suites / 542 passed**; focused owner-publication/reference UI **27 passed**; Next production export passed after correcting the synthetic Response fixture type. New authenticated query tested on real production PostgreSQL with PGOPTIONS-enforced read-only transactions: 8 initial / 9 older lookahead, no overlap, previous incident source still opens with own reference data. Disposable probe disables only schema-initialization helpers, never read-only enforcement; no provider calls or data writes.
- Read-only production evidence confirms older tasks and their published-reference settings remain stored. Account-specific diagnostic details are retained only in the private host report; no customer reference choices changed.
- Final local mobile browser PASS at **320/390/430 px**: user explicitly selects Studio, handles a failed page/retry, opens an older bot-style publication, sets original indexed photo/video reference choices, saves through existing publication API, and loads the remaining pages once. All external APIs/media are synthetic/intercepted; no customer publication, paid generation or payment call. New browser is imported by the mandatory critical-flows gate. Build/TypeScript/changed runtime TS lint passed. Both review axes are checking the final P2 follow-ups; protected PR/CI/exact-SHA deploy and published/read-only acceptance still pending.
- Final contract review reproduced another red case: actual task detail omits prompt_preview; replacing the cached card erased its title. Merge now preserves existing fields and explicitly clears the preview when privacy becomes hidden. React and browser detail fixtures now match the real response. Final **69 Jest suites / 543 tests**, mobile browser320/390/430, production build, TypeScript and changed runtime TS lint passed. Both review axes confirm no remaining blockers. No backend behavior changed after the full3958-test run.

### 2026-10-21 — Lava outages and remaining mobile upload failures

- Baseline: `53eb297213cdaa5f9f429a0f3d0918d3ce5cd48d`, fresh origin/tanyapi; branch `fix/lava-upload-reliability-20261021`, isolated worktree. Production runtime prices remain untouched.
- Result: Lava outages must not trigger cascading catalog discovery or masquerade as pending invoices; checkout must explain temporary unavailability without ambiguous POST retries. Remaining Seedance mobile file kinds must use the existing bounded-size JSON transport instead of broken multipart.
- Audit: 214 final Lava HTTP500 logs in 17:41–18:24 UTC; current authenticated list/detail GETs return200. Actual container allowlist already contains both observed sender addresses; 347 rejected callbacks predate the current container/config. No new source trust or auth relaxation is required. Read-only PostgreSQL shows40 pending,4219 completed,3760 failed. Latest100 authenticated provider invoices match35 completed/65 failed locally, no paid/uncredited in sample. Expand audit before financial conclusions.
- Existing/reuse: atomic payment completion, authenticated provider verification, configured sender/auth, invoice bindings, public reconciliation and JSON upload. Partial: get_invoice collapses provider outage into None; binding fallback then enumerates catalogs, empty status classified still_pending. Seedance file kinds pass through generic upload but are missing from its mobile JSON preference/type contract. Wan image400 may precede successful JPEG recovery and is not alone evidence of a lost upload.
- Risks/invariants: never replay an ambiguous invoice POST, credit from callbacks alone, mark unavailable invoices failed or change source trust; retain pending state until authoritative provider status. JSON remains capped16MiB per generic request; larger videos retain existing chunking/multipart with fallback. No pricing/schema/provider selection/admin migration. Provider500 cannot be repaired locally; guard polling and give actionable alternatives.
- Public seams/test plan: real HTTP fake Lava server + public invoice/reconcile/webhook/checkout and transaction APIs; uploadFile with mobile File/XHR/fetch; synthetic production owner-scoped upload (no generation); browser mobile upload journey. Backend safe suite, frontend Jest/build/types, protected CI/deploy and exact SHA telemetry.
- Steps: (1) reproduce outage and Seedance upload gaps; (2) typed provider read failure, stop degraded batch and return503 webhook/checkout; (3) complete mobile JSON kind contract and enforce deadline; (4) authenticated read-only financial audit; (5) focused/full regression, build/type/lint, independent Standards/Spec review; (6) protected squash-auto-merge PR to tanyapi; exact-SHA CI/autodeploy, health/static, synthetic upload and new telemetry.
- Acceptance: outage causes bounded reads and no catalog fanout; logged reconcile errors reflect lookup failures; pending invoices stay unchanged; recovered provider can complete exactly once; mobile subtype sends exact file bytes directly as JSON; timeout/auth/invalid input paths are bounded and safe; no sensitive log data. Unit/domain, DB, API, Telegram payment, provider/retry/idempotency, browser, smoke/deployment/telemetry apply. Schema migration is inapplicable; financial invariants reviewed via real read-only audit and isolated DB tests.
- Playbooks updated: Bambale0/skills diagnosing-bugs/TDD/code-review; Bambale0/claw review checklist; anthropics/skills webapp-testing. Existing repository instructions authorize these public test seams; no additional seam approval needed. Live provider outage has already been observed; deterministic fake HTTP reproduces the failure before patching.
- Red/green: initial real-HTTP outage regression failed with2 still_pending results and6 final errors including catalog enumeration; now the batch stops after one invoice/at most3 GET attempts with provider_unavailable. All three Seedance kind regressions failed (unwanted native multipart), now exact original bytes go directly via JSON. JSON stuck-transport test initially timed out at Jest5s, now simulated15-minute timeout aborts and settles even if transport ignores its signal.
- Expanded read-only financial evidence:100 provider final invoices span2026-10-17 through2026-10-21;35 completed/65 failed match local states. All40 local pending invoices individually queried using authenticated GET are in_progress.41 provider reads returned200; no paid/uncredited or failed/credited discrepancy. No production financial mutation was needed.
- Public signed checkout regression proved raw upstream errors were returned500; new503 safe code/message covers explicit card/SBP. Real webhook regression exercises outage503 with unchanged balance, recovery and duplicate delivery with exactly50 credits once, and forged sender403 before provider access. Missing404 remains an error rather than a falsely confirmed pending state. No schema/config/admin changes.
- Verification checkpoint: focused backend101passed, frontend upload/cancel/Seedance49passed; all69frontend Jest suites/547tests passed. Production static build and TypeScript passed. Expanded invoice outage/recovery/duplicate/webhook/signed checkout/missing tests5passed. Full safe backend suite is still running. Independent Standards and Spec reviewers found0 blockers against baseline53eb297..bab17a85; no auth relaxation, ambiguous POST replay or unrelated changes.
- Final local verification: `python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short` passed3963tests +76subtests,113skipped (279s). All69Jest suites/547tests passed; production `npm run build`, `npx tsc --noEmit`, changed TS ESLint, Python compile and changed-line Ruff passed (49 existing/outside-diff Mini App findings remain outside this task). Seedance identity/reference browser passed320/375/390/430px with iOS/Android UAs and exact-byte JSON assertions, plus repeat/quote/validation journeys. The mandatory CI browser gate already imports this strengthened journey.
- Independent Standards and Spec reviews:0 findings on application changes; final follow-up only normalizes test imports/EOF and records evidence. [PR354](https://github.com/Bambale0/banano_kling/pull/354) targets tanyapi. Branch protection verified strict=true with all four required Python/deploy, safe regression, Mini App browser and production Docker gates. Native squash auto-merge will be armed on readiness; no manual production deploy. Exact merge-SHA CI, autodeploy and deployed smoke/telemetry remain the release checkpoint and will be attached to the PR/delivery report. No runtime config, migration, balances, prices or webhook trust changes.
- Final scope extension requested by Igor (“устранить проблемы все, доведи до релиза”): browser reproduction invalidating native handles when the picker is cleared fails before the second Seedance photo is available (30s public UI timeout). Generic UploadArea and trend reference picker clear before async upload; Seedance public picker clears immediately after starting it. All three now clear only before the next native picker opens, preserving current selected handles throughout async/multi-file work. The shared browser fixture exercises this expiration on both the public Seedance composer and admin trend/general upload paths, with exact original bytes. No generation or production data mutation. Auto-merge is temporarily disarmed while this concrete additional fix is validated; it will be rearmed with the final head.
- Both reviewers reproduced a remaining generic picker race during an active multi-file batch. Public React deferred-upload regression failed because picker remained enabled, then passed after a synchronous full-batch guard + disabled UI state, released in finally on success/failure. Overlapping picker/drop selection cannot clear active original handles. Extended real-UI browser holds the first generic upload response and attempts another picker click, then verifies both original byte payloads and re-enabled picker. Both Standards/Spec follow-up reviews report0 remaining findings. Final native-picker build passed; full frontend suite and both strengthened browser suites are running. Backend code unchanged after3963passed/76subtests; no new financial/config/schema effect.


## 2026-10-22 — Mini App external payment browser recovery

- Baseline: current origin/tanyapi `30e9f7ee19ddb8af6c54235bfb01e86183af277e`; isolated task worktree/branch `fix/miniapp-payment-browser-20261022`.
- User outcome: Robokassa checkout from Mini App opens outside the Telegram Mini App WebView with a fresh user gesture, and reopening the prepared invoice never creates another transaction.
- Evidence: owner reports multiple Mini App failures with the payment form error on iPhone, while bot URL-button checkout succeeds. Read-only runtime DB, logs and Robokassa OpStateExt show two unconfirmed attempts then a completed card payment for the reported case. This does not reproduce the provider error page or prove a provider-side root cause.
- Audit: bot and Mini App use the same adapter, description, receipt name, signature, amount/credits calculation and ResultURL completion. Mini App keeps signed URL as a string. The frontend unconditionally navigates iOS via location.assign before considering Telegram.openLink. Other platforms call openLink after awaited API; Telegram web-events specifies a one-second interaction TTL. Existing browser fixtures only cover immediate Android/desktop bridge success and lack slow iOS checkout coverage.
- Reuse: existing authenticated create-payment, signed adapter URL, package configuration, atomic callback completion, client-log diagnostics and mounted static browser harness. No prefactor required beyond narrow balance sheet state.
- Risks: native Telegram iOS/browser integration cannot be fully certified with mocked Playwright WebKit; real-device acceptance remains required. Exact screenshot cause is not claimed. Preserve exact signed query including encoded Receipt and 64-bit invoice strings. Do not log URLs/signatures/credentials.
- No-hardcode/config/migration: no prices, provider choices, retries or operational thresholds introduced. No schema, auth, admin, rate, receipt, Telegram FSM, payment completion/refund or provider contract mutation. Prepared URL stays in component memory.
- Observability: checkout-ready/open/fallback client events with provider, order ID and opening path only; an open request is not proof that provider UI loaded.
- Test plan: rendered BalanceSheet regression for iOS direct external open, silent Android bridge retry, exact URL and one transaction; API failure; slow-response mobile browser fixture using WebKit and Chromium, no live provider requests; existing frontend Jest, lint/types/build and critical E2E; focused backend Robokassa adapter/callback regressions.
- Steps: (1) failing rendered checkout regression; (2) ready invoice and fresh-tap external opening; (3) mobile browser regression and docs; (4) local checks/review; (5) PR to tanyapi with native squash auto-merge and protected CI; (6) exact-SHA deployment, health/revision and telemetry smoke.
- Acceptance: iOS stays in Mini App until explicit payment click; click invokes native openLink synchronously; exact URL survives; repeated ready-button click has one create-payment call; Android automatic open retains a visible retry; Stars remains native; no paid test or customer message.
- Guidance: current Bambale0/skills diagnosing-bugs (evidence-first with deterministic bridge regression; actual provider page remains unreplicated), Bambale0/claw QA/review flow, anthropics/skills webapp-testing. All three local playbooks refreshed before edits.
- Verification layers: frontend/browser and signed-provider contract applicable; DB/schema/admin/refund mutation layers N/A because business/payment processing code unchanged. Existing financial callback regressions still run.

- RED: rendered checkout test failed 2/3 cases: iOS attempted location.assign, no prepared invoice action, Android had no retry. GREEN: 7/7 rendered tests pass, including native anchor fallback/throw, closing before a late response, and native Stars.
- Validation: all frontend Jest 71 suites / 555 tests pass; tsc --noEmit and production static build pass. Full lint has no errors, one pre-existing task-detail-panel hook warning. Focused backend Robokassa primary/receipt/partner notices: 13 passed. Initial command naming an untracked payment-utils file collected no tests; corrected to tracked suites. Slow Android browser fixture passes exact URL, one invoice, stale automatic event and fresh-tap retry.
- Local WebKit launch is blocked by missing system libraries; no production host packages changed. Mandatory GitHub browser gate installs WebKit dependencies and runs all three new payment scenarios (iOS native, Android native, iOS bridge fallback). Existing critical browser suite remains in progress.
- Review: no signed URL reconstruction/logging, financial mutations, hidden paid retries or cross-surface price/signature drift. Foreign Lava ready state deliberately omits an unverified checkout currency/amount. Native Stars route and explicit customer-email handling preserved.

- CI wiring review: payment-browser runs first in both the standalone browser workflow and the actual branch-required browser job in ci.yml. Rendered payment regressions are also included in miniapp-ci.yml. This makes iOS payment coverage a required merge condition, rather than relying on the standalone browser result.
- Local aggregate critical-flows.mjs completed successfully, including all imported mobile publication/repeat/identity/upload/Wan/Studio suites. Source lint passed with one existing hook warning; a rerun initially scanned generated .e2e-server assets, then passed with that generated directory excluded. Generated test artifacts removed from the isolated worktree.
- PR #355 opened; native SQUASH auto-merge verified armed for head b5749efa. Branch protection verified strict=true with all four required CI gates. Workflow coverage follow-up creates a new exact head; checks must pass for it before merge.

- First iOS CI payment scenario reached its final privacy assertions but the fixture failed parsing a missing WebKit sendBeacon request body (null), not a checkout assertion. Harness corrected to capture the actual Blob payload before sendBeacon, assert ready/open events exist, and inspect those payloads for signed URL leakage. No production logic change was needed.

- Full CI safe suite on 50db65f0: 3962 passed, 113 skipped, one obsolete source-text test failed because it explicitly demanded iOS same-window navigation. Removed that implementation assertion; it is superseded by seven rendered payment regressions and the mandatory mobile browser journey. No backend processing implementation changed. Full isolated local safe-suite rerun started to verify the remaining contracts.
## 2026-10-22 — neuromixbot.com domain migration

- Baseline: tanyapi `0c752e33857cf591328aef1e3b47235a6174584f`; isolated task worktree/branch `fix/neuromixbot-domain`. Production runtime price file remains untouched.
- Result: Mini App, new media links and Telegram launch buttons use `https://neuromixbot.com/mini-app/`; valid automatically renewed TLS; historical origin remains available.
- Audit: A record already resolves to 144.76.188.75; no AAAA. Nginx has no dedicated new-domain vhost; HTTPS fails hostname verification. Existing shared-origin vhost supports static export, uploads, signed Genjutsu and API. Backend and static revisions match baseline; backend health is OK. Existing deployment pins old domain in scripts/workflows; bot/env.py unconditionally overrides configured MINI_APP_URL. Reuse existing static root and proxy routes; no prefactor beyond respecting explicit URL configuration.
- Risks/dependencies: ACME HTTP reachability, shared Nginx, stale links, CI exact-SHA checks, Telegram main-app settings managed outside Bot API. No DB/schema/FSM/payment/schema change; Telegram/payment webhook host remains tanyapi.chillcreative.ru. New signed Genjutsu callbacks follow GENJUTSU_PUBLIC_BASE_URL; both origins proxy these routes. Media origin configuration changes only after TLS is live. Preserve old vhost and content; rollback via prior env backup/release.
- No-hardcode: existing MINI_APP_URL/PRODUCTION_MINI_APP_URL/MINIAPP_FRONTEND_DOMAIN settings remain configurable; update canonical defaults, honor explicit runtime MINI_APP_URL, keep known historical media origins.
- Observability: nginx -t and reload status, TLS hostname/expiry, ACME dry-run, public revision and assets, auth boundary and media Range checks, backend health/config/image SHA, recent error counts without secrets/private payloads.
- Applicable verification: environment/config and deployment regressions; media URL normalization; Mini App browser/static/API auth; deployment validation and four required protected CI gates; exact release CI/autodeploy and production smoke. DB/migrations, financial mutation, generation and Telegram FSM business changes are inapplicable because only public origin changes.
- Steps: (1) prepare regression/config changes; (2) add HTTP challenge vhost and obtain certificate using existing ACME account; (3) activate HTTPS against existing static root; (4) update runtime origin config with root-only backup; (5) focused tests/review and protected squash-auto-merge PR; (6) exact-SHA autodeploy and production verification.
- Acceptance: hostname-verified HTTPS serves NEUROMIX and all current assets; same-origin API rejects unauthenticated requests normally; uploads/ranges work; runtime launch and new media URLs use new origin; previous links still work; renewal dry-run succeeds.
- Playbooks refreshed/read: Bambale0/skills diagnosing-bugs (HTTP red/green evidence), code-review; Bambale0/claw PR review checklist; anthropics/skills webapp-testing. Infrastructure migration uses direct HTTP/TLS evidence instead of unnecessary bug-hypothesis instrumentation.
- Infrastructure evidence: dedicated HTTP/TLS vhost activated, hostname-verified HTTPS returns200, bootstrap without Telegram initData returns401; certificate CN neuromixbot.com/Let's Encrypt YE1 expires2027-01-20. Renewal dry-run with deploy hook succeeded; certbot.timer active. New static root symlinks to existing root. Runtime env origins updated atomically; root-only backup `/root/backups/neuromix/domain-20261022-183018`; application awaits protected CI release. Initial five domain/config regressions failed before implementation; focused config/deploy suite passed145tests +6subtests, updated config tests35passed; media tests7passed.
- Review corrections: update README current production table; align direct Compose fallback with new domain; clarify new Genjutsu provider callbacks follow the shared media origin while payment/Telegram webhooks remain unchanged. Standards review found no high-severity blocker; Spec review confirmed vhost route coverage and requested signed callback smoke.
- Historical launch-page redirects activated for /, /mini-app and /mini-app/*, preserving query strings and client-side fragments; /mini-app/api/, hashed assets, /uploads/ and signed /genjutsu/ continue on the old host. Both active vhosts are recorded in ops/nginx. Invalid new-domain Genjutsu callback/media signatures are checked before processing (smoke result below). All72frontend Jest suites/559tests passed; production build/type checks underway.
- Final two-axis review at144455e7: Standards0blockers; Spec0blockers. Production mobile browser follows old launch URL onto neuromixbot.com preserving query and fragment, title NEUROMIX,0page errors/failed same-origin requests. Public video Range returns206 and exact original1024bytes on both domains. Invalid signed media/callback each403. Python compile, Bash syntax and changed-line Ruff passed (8existing findings outside changed lines). Production frontend build and TypeScript passed.
- Release dependency blocker: browser CI npm audit reports critical Next.js advisory GHSA-673q-mjm6-r5xr (and related image/server-action advisories, patched>=16.4.1). Minimal release prerequisite: update Next.js range to^16.4.2, resolved16.4.2 and matching @next packages only; no audit suppression. Fresh isolated npm ci succeeds; audit now has0high/critical (20existing moderate remain outside high-severity gate). Repeating frontend suite/build/types and protected CI on patched lockfile.
- Patched dependency verification completed: fresh npm ci; npm audit --audit-level=high passes (0high/critical); all72Jest suites/559tests pass; Next16.4.2 production static build, TypeScript and changed production TS ESLint pass. Dependency-only Standards re-review reports0blockers. Four strict required CI contexts and native SQUASH auto-merge verified on PR356; exact release CI/autodeploy and final runtime checks remain pending.
- Full CI regression:3963passed/76subtests/113skipped; three existing expectations still encoded forced old URL behavior and old deploy origin. Update those contracts to the intentional configurable URL behavior and new production origin; no application failure observed. Owner reported BotFather /setdomain updated; rechecking live Login Widget.
- BotFather domain confirmation: owner completed /setdomain for Neuromixx_bot; fresh production browser on neuromixbot.com now renders the live oauth.telegram.org “Log in with Telegram” button instead of “Bot domain invalid”. No login credentials were entered. Expanded focused backend contracts156passed +6subtests; Ruff on corrected tests passes.

## 2026-10-22 — historical video retained-reference compatibility

- Baseline: current tanyapi `727052816782b551a13407cb32e556b4ceb0a87c`; isolated branch/worktree `fix/preserve-video-reference-consent-20261022`. Live administrative pricing file remains untouched.
- User outcome: older published Seedance videos keep the author's explicitly retained source slots. Reported four-image publication must request two replacement photos, preserving its two retained tail images in original positions.
- Evidence/current audit: exact production image revision matches baseline. Read-only production inspection confirmed all four source files exist, a two-image explicit legacy `feed_reference_selection`, public references enabled, and historical empty image-only repeat grant. Current public descriptor returns four upload slots. Recent author publications already have typed grants, so the problem is not proven to affect every video. Regression appeared in #350: foreign_video_repeat_task replaces every historical selection with typed empty consent before the existing compatibility descriptor can run.
- Ranked diagnosis: (1) lost legacy semantics predicts four uploads despite saved selection (confirmed); (2) historical-origin alias mismatch predicts unresolved stored slots (covered using known-host alias fixtures); (3) upload deletion predicts missing local originals (ruled out for all four incident inputs).
- Reuse/prefactor: reuse the existing closed retained-tail Seedance 2.5 legacy planner, typed slot validation/merge, URL identity resolver, authenticated source boundary, before-charge snapshot guard and owner publication editor. Add a shared effective grant resolver; no broad provider refactor.
- Security/no-hardcode: visibility alone, absent/empty selections and private/derived historical recipes never infer consent. Typed grants, including explicit empty revocation, always win. No task IDs, authors, media URLs, business values or provider rules hardcoded. No production SQL mutations, schema/config/admin setting, price, charge/refund, provider payload schema or retry changes.
- Surface/API impact: same URL-free slot descriptor and same authenticated video launch API. Owner editor receives original saved retained indices, avoiding accidental clearing on the next save. Telegram uses the same Mini App repeat redirect. Publication removal records a typed empty tombstone for legacy videos too, preventing implicit restoration after republishing.
- Observability: existing source-generation IDs, rejection codes, permission snapshot logging and before-charge media checks retained. Production acceptance will record only slot counts/file availability; no prompts, auth contents or private source URLs in committed evidence.
- Applicable verification: domain/SQLite publication integration, authenticated restore/before-charge revocation, typed/malformed/legacy/alias/privacy regression, Telegram callbacks, provider/financial/retry regression, existing mobile browser slot journey, Python lint/compile, four strict CI gates and exact-SHA production deployment. No migration verification needed beyond unchanged schema; no paid provider request or customer message.
- Steps: (1) reproduce with public card/owner indices/launch regression; (2) resolve validated legacy grants consistently and persist revocation tombstone; (3) safety regressions/docs/review; (4) safe regression and browser checks; (5) PR to tanyapi/native squash auto-merge; (6) exact-SHA CI/autodeploy and read-only incident-card/file/health/telemetry smoke.
- Acceptance: [upload, upload, fixed, fixed] for the reproduced legacy selection; outgoing inputs [new1,new2,retained3,retained4]; unchanged stored selections after reads/repeat; owner editor indices [2,3]; revocation or withdrawal blocks stale launch before charge; typed empty and ungranted cases still require replacements; no private URL in descriptors.
- Guidance refreshed/read: Bambale0/skills diagnosing-bugs (red-capable public seam, evidence-first), code-review (Standards/Spec); Bambale0/claw PR review checklist; anthropics/skills webapp-testing (existing synthetic browser journey). Regression RED: isolated test failed with four uploads instead of two fixed slots; initial host Python lacked aiogram, switched to existing isolated test venv.
- GREEN: first full targeted publication/typed/legacy/Telegram slice 159 passed. Added actual Seedance provider-boundary regression for both historical empty formats: two new photos + exact retained slots reach the mocked adapter; a simulated provider rejection produces one debit/one matching refund. Both provider cases pass. Historical compatibility also uses the existing durable repeat receipt authorization; source snapshot revalidation stays unchanged.
- Safety matrix covers missing/hidden/empty selection, private recipe, derived ancestry and explicit typed revocation; historical-origin alias test preserves exact slot positions. Existing expectations requiring four uploads for an explicit two-slot legacy selection updated to the intended backward-compatible behavior. Browser regression now covers the reported two-upload/two-fixed layout alongside replacement-only and other existing repeat journeys.
- Review: Spec 0 findings; Standards 0 blockers, one stale security-boundary comment/name corrected: the historical planner now explicitly serves descriptors, owner editing and authenticated launch compatibility rather than claiming display-only behavior. Changed-line Ruff 0 findings (274 pre-existing whole-file findings), compile and diff whitespace checks passed.
- Mobile browser: 320px/390px passed, including new two-replacement/two-retained regression. Full safe suite initially could not collect with the older venv (missing pypdf); rerun uses an existing up-to-date isolated venv with the required dependency. No production packages changed.
- Read-only production-data preview of the reviewed module (disposable interpreter, no running-service replacement): 147 published author videos examined; 56 typed grants, 14 valid legacy retained selections, 77 replacement-only recipes. Incident returns [upload, upload, fixed, fixed]; both retained local files exist. Preview is not a deployment claim.
- Expanded regression caught legacy validation exceptions escaping the authenticated boundary as503; map them into the existing user-facing repeat_reference_incomplete400 before any billing. Five older assertions intentionally required four uploads for explicitly retained historical selections; updated to two replacements and exact original retained positions. Aliases remain rejected when ambiguous; a valid exact retained-tail occurrence stays in its source position. Final focused continuity/typed/legacy matrix:217passed.
- Full first pass:3961passed/113skipped,15failures limited to the already-corrected historical exception/status/expectation cases and six dedicated identity-form cases. The dedicated identity form replaces complete media kinds and validates its own uploads; legacy retained selection resolution must not run for that path. Added a request-scoped opt-out for historical selection only (typed grants still win); source permission snapshots remain guarded. Existing six real identity quote regressions pass without changing their assertions. Combined identity/continuity/typed/legacy:286passed. Final full safe suite restarted on corrected code.
- Both review axes rechecked the exception/status correction with0remaining findings. Historical-grant receipt authorization retains existing idempotency infrastructure; dedicated legacy identity path retains its previous receipt/validation behavior.
- Final two-axis review of the identity compatibility correction: Standards0findings; Spec0findings. No remaining high-severity review issue.
- Verification checkpoint: focused public/owner/launch/identity matrix286passed; mobile slot browser passed320/390/430px; direct reviewed-module production-data preview passed the incident layout and both fixed-file existence checks. No migration/config/admin/pricing changes. Final full-safe-suite, exact-head protected CI and exact-SHA deployment/smoke evidence are tracked in PR https://github.com/Bambale0/banano_kling/pull/358 as they complete; do not infer deployment from this checkpoint.
- Release infrastructure blocker: exact-head safe regression passed on GitHub, but both browser runners spent10–15minutes downloading Ubuntu WebKit dependencies from azure.archive.ubuntu.com. Cancelled only the older redundant browser workflow to obtain logs: package transfers stalled/retried (e.g.7.5MB fonts and9MB libcodec2); no browser assertion had run or failed. Required gate remained enabled. Necessary release prerequisite: rewrite that Azure HTTP mirror to the official HTTPS archive.ubuntu.com in both browser install paths, preserving suites/security mirror/Signed-By and all tests; bound the install step to10minutes. Both workflow YAML/shell checks and a synthetic apt-source rewrite pass. New exact-head CI must pass before merge; no production host apt configuration changed.
- Fresh standalone browser workflow passed all critical/iOS assertions. Its complete logs exposed a CI configuration correction: hosted images use mirror+file:/etc/apt/apt-mirrors.txt, so rewriting only .sources/.list files had not selected the new mirror; that runner recovered through a fast Azure path independently. Include the verified mirror-list path in both rewrite loops. Execute the actual extracted workflow shell against a synthetic hosted-image layout: priority preserved, official HTTPS archive selected, security mirror and Signed-By unchanged; both pass. Application code and prior3976-pass suite remain unchanged. Exact-head CI will verify the corrected infrastructure path.

- Integration update: parallel PR357 advanced tanyapi to8870702c during release verification, causing an execution-ledger append conflict and preventing new pull_request CI creation. Merged current tanyapi normally, preserved both complete ledger sections and all Kling4 application/browser/PostgreSQL changes; no force-push or release-gate bypass. Repeat compatibility changes remain isolated. Fresh integrated tests/CI required.

## 2026-10-22 — Kling 4 via KIE, administrator release

Baseline: `727052816782b551a13407cb32e556b4ceb0a87c` (`origin/tanyapi`). Task branch `feature/kling4-admin`, isolated worktree; production `data/price.json` is intentionally preserved.

Result: one Kling 4 card with Reference and Keyframe modes in Mini App, complete Telegram editor, owned uploads, named elements/voices, ordered frames, measured quote, durable task/result/history and retry-safe launch. Every server entry requires a current administrator. Public opening is a separate explicit operator decision; this release cannot charge or expose Kling4 to ordinary users.

Preflight: KIE transport/HMAC, authenticated actor extraction, owned chunk storage/SSRF protection/media probe, common generation history and admin-free semantics already exist. Wan3 lifecycle is deliberately model-specific; reusing its billing would produce incorrect Kling4 video quotes. Reuse media infrastructure, implement a separate explicit adapter and durable admin lifecycle. Missing: both Kling4 IDs, exact validation, tariff snapshots, editor/FSM and tests. No unrelated model refactor. No payment/referral schema or customer balance changes (admin-only zero retail charge). Additive SQLite/Postgres tables only.

Contract: official KIE Reference/Keyframe JSON schemas independently researched; see `docs/kling4.md`. Two IDs, six rates. Unknown submission never retried automatically. Signed callbacks are wakeups; authoritative GET confirms model/task/result. Unknown or malformed success remains recoverable. Result persistence precedes success; delivery retries never regenerate. Owned input hashes/metadata are frozen with request. Visibility enforced at catalog, HTTP, Telegram and lifecycle; unsupported generic generation routes reject Kling4.

Configuration: versioned DB settings with authenticated admin API and audit actor/time; provider rates, concurrency, poll/timeout/storage policy editable. Secret API/HMAC keys remain existing environment secrets. Administrator free generation reports provider expenditure separately. Public access stays closed independently from mutable settings until Igor commands release and public billing is reviewed.

Steps / acceptance:
1. Exact provider validator, measured six-tariff quote, owned media, adapter; public-seam regression tests.
2. Durable intents before POST, idempotency conflict detection, no blind retry, canonical reconciliation, retained result and independent delivery.
3. Authenticated API + model catalog + Telegram FSM + Mini App form (two modes, media, elements, voices, ordered frames, quote/confirm/history/repeat).
4. Controlled paid API contract research using synthetic fixtures, <=2000 KIE credits ($10), task IDs/cost evidence; Playwright admin/nonadmin journeys.
5. Parallel Standards/Spec review per primary playbook; full applicable regressions/build/deploy validation; PR -> protected tanyapi squash auto-merge -> exact SHA CI/autodeploy -> health/static/admin smoke/logs.

Verification seams: domain/provider contract, SQLite integration/concurrency/restart, API auth/admin/ownership, Telegram callbacks/FSM, browser media editor and quote staleness, live KIE, production. Existing financial invariants remain unchanged because ordinary users cannot launch. No destructive migration.

Progress: official contracts verified; isolated worktree created. Skills: Bambale0/skills wayfinder-style research, grill-with-docs/to-spec/to-tickets/implement/tdd/code-review; Bambale0/claw PR checklist; anthropics/skills webapp-testing. Research ambiguities (video-element-only, fractional input billing, missing first-frame behavior, audio) require live evidence and remain explicitly unverified until recorded.

Implementation evidence (pre-release):
- Typed strict Kling4 adapter/validator, measured media, six versioned provider tariffs. Paid API research corrected the draft guide: only ordinary video_urls select video pricing; ceil the sum of ordinary input seconds; elements are excluded from billed input. Regression includes same URL in two different material roles.
- Additive `kling4_intents`, settings and settings audit tables; no user debits. Intent+common history commit before POST, per-owner idempotency, recoverable unknown acknowledgement, canonical task/model GET, durable local original before success, independent Telegram delivery, current admin gate on every facade.
- Mini App and Telegram editors support both modes, ordered frames, uploaded/imported media, named elements, bound and standalone voices, sound control, quote+confirm, history/download/repeat. Separate mode drafts retained. HTTP uncertainty freezes the draft and preserves the same launch key. Original picker bytes retained/copied before network; no implicit browser image conversion.
- Both review axes completed; all initial P1 issues corrected (public URL mapping, webhook delivery wiring, watchdog ownership). P2 corrections cover normalized adoption, native picker lifetime, mode draft preservation, mixed-role billing and result expiry. Retention now locks against publication and skips protected rows before its page limit; sequential/concurrent and full protected-page regressions added.
- Real paid KIE smoke:12/12 success,1328.5 credits ($6.6425), under2000 cap; all outputs downloaded+hashed+ffprobe verified. Structured safe evidence `docs/kling4-live-smoke.json`.
- Local focused SQLite/API/FSM/media/lifecycle regression:28 passed. Dedicated real PostgreSQL regression:1 passed (four concurrent launches ->one provider POST, unchanged balance, settings CAS, canonical failure and ambiguous restart). Real PG schema/adapter script also passed. Browser Kling4 Playwright passed mobile375/430 including unchanged original bytes, elements, preserved drafts, frame order, quote invalidation, admin catalog filtering, pending lock and network retry same-key. Existing559 frontend tests passed. Production export builds/typecheck passed. Full backend regression and release CI still pending; do not claim deployed yet.
- CI now includes Kling4 Playwright in required Mini App gate and dedicated Kling4 PG case in PostgreSQL runtime workflow. No new secrets, providers or external packages required.

Release candidate checks: full safe backend suite `pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short`:3993 passed,113 skipped,76 subtests (310.26s). Follow-up focused final `tests/test_kling4.py tests/test_task_watchdog.py tests/test_wan3_retention.py tests/test_wan3_result_retention.py`:56 passed. `RUNTIME_POSTGRES_TEST=1` dedicated Kling4 PG case:1 passed. Frontend:559 Jest tests passed; production Next export/TypeScript passed; new Kling4 Playwright and existing critical-flows journeys passed. Ruff on new Python modules/tests and diff whitespace passed. Required tanyapi branch protection verified `strict=true` and all four expected gates still configured. Deployment remains pending until exact merged SHA verified.

Additional auth refinement before merge: cryptographically verify Telegram and reject nonadmins before any channel probe or user creation. This keeps forged admin checks free of production user writes and independent from subscription state. Focused final Kling4 suite29 passed. The exact PR head will receive a fresh full CI run.

Telegram concurrency hardening: apply per-actor state mutations under an async lock while keeping media network I/O outside it. Each field selection has a separate media session so an old upload cannot attach to a reopened editor. Regression covers simultaneous file messages preserving both slots and a delayed old upload after reopening the same field. Final focused Kling4 suite30 passed. Shared history label now consistently reads “Kling 4”; generic model selectors defer pricing to the measured quote instead of showing an invented fallback cost.


## 2026-10-22 — Kling4 production multipart regression

Baseline8870702c1b5282d7f33e32ffab265fd7ec2dac7d. Exact release CI/autodeploy passed; frontend/container SHA and health verified. Production auth checks:401 unauthenticated quote,403 for all12 nonadmin actions including media; runtime prices preserved. The first owned upload failed before any paid production create. Diagnosis: global add_post ban guard eagerly calls _miniapp_payload, consuming multipart before the bounded chunk reader. Earlier HTTP test used /kling4 outside the guarded /mini-app/api prefix and missed that production chain. Actual production wrapper + real prefix + real route setup regression now reproduces400 invalid_upload_multipart (1 failed,29 deselected,4.89s).

Fix: register the self-authenticating Kling4 routes with add_route(POST), as the existing Genjutsu integration does. Own actor boundary still verifies Telegram/current admin/bans before media parsing. Regression retains real owned bytes, quote, foreign ownership rejection and explicit banned-admin403 checks. No schema/config/payment changes. No provider POST occurred during the failed upload; paid smoke budget is unchanged. Acceptance: regression green; required CI/review/autodeploy exact fix SHA; repeat production original upload, two API tasks and one actual Playwright generation/delivery. Pending until verified.

Follow-up local verification:30 Kling4 tests passed with the production wrapper installed; both spec and standards review axes found no blockers. Ruff check/format and diff whitespace passed. Required CI/autodeploy and paid production smokes remain pending.

Updated base66c34832 preserves the parallel historical-reference fix. Follow-up focused suite46 passed. Repeated hosted-runner stalls also affect ffmpeg apt installation; extend the already-merged Ubuntu archive mirror switch from the browser gate to media tools, with bounded apt network/step timeouts. All required test/image gates remain unchanged. This avoids depending on the stalled Azure HTTP mirror for release checks.

The bounded media dependency attempt reached its5-minute timeout before tests; log /tmp/kling4-media-install-failure.log. Avoid apt entirely when both binaries already exist; otherwise retain failure limits, use canonical Ubuntu HTTPS for archive/security and show apt progress for diagnosis. Runtime version checks and full tests remain mandatory. No claim that the hosted image includes these binaries; the next CI run verifies it.


## 2026-10-22 — Kling4 PostgreSQL worker dispatch recovery

Baselineca43124ae99753f9e2857a5a20d6ea6d1b3aef4d. Exact CI/autodeploy, SHA/static/health/TLS/runtime-price checks passed. Production original uploads and idempotent API launches passed;2API+1Playwright jobs were created exactly once,85.5 credits quoted each. The production worker left all3 intents pending without canonical polling. Scoped diagnostic tick on these existing rows invoked no provider create and reproduced the no-op. Root cause: PostgresRow is a Mapping and its iteration yields column names. Tuple-unpacking rows dispatched deliver('task_id') instead of processing actual IDs. Startup itself was functioning.

Regression: real PostgreSQL test now goes through tick instead of calling reconcile directly; red pending!=failed reproduced (1 failed,2.93s). Minimal fix reads row[0]/row[1], compatible with both adapters. Real PostgreSQL success/failure parameter cases now exercise canonical terminal state, durable original, second-tick Telegram mock delivery, unchanged balance, idempotency and ambiguous restart;2 passed (2.58s). Both spec/standards reviews found no blockers. No schema/config/payment changes and no new paid provider jobs. The existing3 saved intents must resume automatically after normal CI/autodeploy; no recreation or manual SQL.

Additional smoke-harness correction: signed test sessions must preserve operator profile fields. Initial minimal test claims cleared operator metadata; exact pre-smoke fields were restored through the authenticated product API and checked against a read-only predeploy backup. Both API and browser helpers now preserve them; repeat preflight verified no further changes. Private identity snapshot remains outside Git with0600 permissions. Browser disabled-state assertion now uses inherited fieldset semantics; a saved task/intent guard prevents another paid generation. Its final result is verified through genuine history/download recovery and native browser MP4 playback.


## 2026-10-23 — Seedance 2.5 birthday trend create rejection

Baseline `ae8053d3b7ea27f1c94a8a3210198836d20ac9b0`; isolated branch `fix/seedance25-trend-create`. Production price file preserved. Screenshot matches trend2303, six immediate create rejections across2302/2303, first-frame,8s,720p. Provider raw response was discarded by callers; existing logs record request scenario/counts but no rejection cause. Other multimodal Seedance requests have been accepted. Existing trusted trend resolver, owned references, server quote, debit/refund and request claims are reused. No speculative provider-mode fallback.

Steps:1.capture exact provider rejection using one operator-authorized diagnostic create(max$3; initial$1 cap increased after tariff verification), with no customer debit;2.add deterministic regression at adapter/trend seam;3.fix evidence-supported cause and safe diagnostics;4.focused/full checks, two-axis review, protected PR to tanyapi;5.exact-SHA CI/autodeploy/health/logs. Acceptance: provider reason preserved safely, private prompts/media/secrets never exposed, rejected create refunds once, successful launch persists existing task metadata.

Configuration/migrations: none intended. Mutable tariffs/prompts stay managed. Observability: structured rejection code/model/scenario/trend IDs, sanitized diagnosis without raw request. Test seams: provider adapter and Mini App trend handler, refund regressions, existing Telegram/public Seedance tests. UI/browser only if UI changes; DB migration, payment/referral schema not applicable. Rollout: normal protected auto-merge/CI only. Primary playbook diagnosing-bugs; claw PR checklist; anthropics webapp-testing guidance inspected.

Evidence: exact incident input reconstructed by matching stored SHA256 request fingerprint against owned reference and screenshot field values. One permitted create returned422 with explicit first/last-frame adaptive-only constraint, no task ID. No second paid create attempted. Red regression reproduced5failures/2pass, including the original502 trend symptom. Adapter/shared validation normalize valid frame ratios; persisted trend/public metadata and response use effective adaptive. Both Mini App forms and active Telegram keyboard restrict frame geometry, stale callbacks normalize; other modes preserve ratios. Safe rejection logs omit provider text. Focused backend232passed; form Jest11passed. Full safe backend/frontend/build and release pending.

Review: primary playbook code-review completed two independent read-only axes against64d2382c: Standards0material findings, Spec0findings. Minor ledger cap corrected from initial$1 to approved$3. Complete frontend Jest562passed/72suites; Next production export and TypeScript passed; changed-file ESLint and changed-line Ruff passed(15pre-existing unrelated diagnostics excluded). Full backend first collection lacked declared pypdf dependency in shared legacy venv; installed pypdf6.21.2 only under/tmp/seedance25-frame-test-deps and restarted full suite with isolated PYTHONPATH; runtime venv unchanged. Branch protection verifiedstrict=true and all4required contexts.

Final local verification: full safe command `PYTHONPATH=/tmp/seedance25-frame-test-deps:. python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short`:4019passed/115skipped,1PDF-test environment failure. Root cause of that failure: bounded PDF worker starts Python with-I, which correctly ignores PYTHONPATH; shared legacy venv lacks declared pypdf. Isolated/tmp venv with explicit site dependency paths fixes the environment without changing runtime or source. `python -m pytest tests/test_wan3_media_integrity.py tests/test_seedance25_frame_ratio.py -q --tb=short`:19passed, including the formerly failing real50-page PDF probe. No unresolved local test failure. Complete browser critical-flows chain exited0, including mobile Seedance upload/identity/ordinary-reference and Wan/history journeys. Frontend562passed, export/TypeScript/ESLint/changed-line Ruff and shell validation passed.

Release evidence is maintained on [PR361](https://github.com/Bambale0/banano_kling/pull/361): native SQUASH auto-merge armed, strict4-gate protection verified. Exact-head CI, merge SHA, autodeploy, backend/frontend revisions, health and production offline replay are recorded there as they finish. Production replay must intercept provider transport(no new paid create/customer mutation); the single authorized live create was already used to establish the422. No config/schema/admin-price changes.


## 2026-10-23 — Kling 4 automatic Telegram composer

Baseline `6c0d09f05a9e04ac3d825ccf8bd5ef4314d103d9`; task branch `fix/kling4-automatic-telegram`, isolated worktree. Direct user request overrides the previous explicit prompt/media/quote/confirm navigation: remove Main Menu and manual launch stages; entering prompt launches automatically; detect media automatically; expose direct duration(-1/current/+1) and aspect ratio choices. Server-side admin-only access remains.

Preflight: existing typed adapter, owned measured uploads, current admin gate, versioned quote, durable launch intent and idempotency are reusable. Telegram currently ignores ordinary messages in editing state; prompt/media require field selection; duration is numeric input; ratio cycles; quote and confirmation are manual. Mini App already has a separate deliberate quote flow and remains intact. No provider or financial-schema changes needed. Current risk areas: albums/captions, pending upload vs prompt races, stale callbacks/uploads after navigation, duplicate messages and unknown provider acknowledgement. Existing prompt fragment coalescer supplies managed quiet-window settings; no new arbitrary delays.

Accepted public seams from the user's requested Telegram flow: genuine Telegram messages/callbacks/FSM and lifecycle boundary with provider transport stubbed. No extra seam approval requested: repository autonomy and explicit user behavior supply scope. Test layers: Telegram keyboard/update integration, actual domain/lifecycle/SQLite and existing PG coverage, auth/admin, owned media validation, quote/key idempotency and unknown outcomes, unaffected Mini App contract, existing browser/CI/deploy gates. No migration/payment/referral mutation; ordinary users cannot launch. UI browser changes not intended.

Steps:1.simplified inline keyboard and safe legacy callbacks;2.typed automatic media intake, ordered concurrent uploads and caption/text prompt coalescing;3.internal quote+idempotent launch on prompt, no confirmation buttons;4.regressions/docs/full safe checks/two-axis review;5.protected PR/native squash auto-merge to tanyapi;6.exact merge-SHA CI/autodeploy/health/static/production offline Telegram smoke and telemetry.

Acceptance: open Kling4 -> upload arbitrary supported references without picker -> send prompt -> one durable launch with measured quote; no prompt/calculate/confirm/Main Menu buttons; duration and supported ratios directly available; no silent media loss or launch on settings changes; nonadmin denied; old callbacks cannot duplicate accepted jobs. Defaults/tariffs/provider policies remain existing managed settings. Logs expose actor/task/request ID, media counts and outcome without prompt/media/secrets. Skills: primary tdd and code-review; claw PR checklist; anthropics webapp-testing guidance inspected. Paid provider calls are not authorized for this task and will be intercepted in smoke tests.

Implementation evidence: simplified editor/navigation; automatic typed intake with per-session pending upload tracking, restart-safe failure markers and ordered Telegram receipts; internal measured quote and durable message-based launch key. Caption albums and prompt fragments reuse existing managed quiet windows. Exiting/clearing invalidates pending work; unsupported attachments block instead of being silently omitted. Explicit provider frame tags infer frame intent; new files return to ordered intake before resolving the next prompt. Old callbacks remain compatible, without Main Menu. Documentation updated for Telegram versus Mini App behavior.

Test-first evidence: initial editor regression failed on the old Main Menu button; prompt regression failed because editing-state handler did not exist. Focused final `python -m pytest tests/test_kling4_automatic_telegram.py tests/test_kling4_navigation.py -q --tb=short`:43 passed. Covers actual aiogram router, direct settings/bounds, auto-detected photo/video/audio/documents, captioned concurrent albums, fragment coalescing, failed/unsupported uploads, navigation/clear races, frame inference, nonadmin denial and real lifecycle unknown outcome/idempotency with unchanged balance. Ruff check/format passed on changed modules/tests. All provider creates intercepted; no paid request. Full safe regression, independent review and release verification pending.

Independent review found two real edge cases and both were reproduced before correction: Spec P1 legacy prompt/quote/launch bypassed pending reference readiness; Standards P2 a high-water ID discarded unseen out-of-order fragments. Four new regressions failed before the correction. Legacy prompt/quote/launch callbacks now only open the automatic editor; persisted old prompt input enters the shared intake pipeline. Exact per-session receipts replace the high-water heuristic. The existing fragment coalescer gains opt-in Telegram message-ID ordering for Kling4 only; other model behavior keeps its default. Final focused `python -m pytest tests/test_kling4.py tests/test_kling4_automatic_telegram.py tests/test_kling4_navigation.py tests/test_prompt_fragment_coalescer.py -q --tb=short`:81 passed (6 existing aiohttp AppKey warnings). Full regression is repeated for the final reviewed code because the shared coalescer changed.

Final independent re-review at64a46359: Standards0 remaining material findings (independent automatic/coalescer run28 passed); Spec0 remaining findings (independent legacy/order/unknown run5 passed). Changed-line Ruff on all6 Python files:0 relevant/0 legacy diagnostics. Targeted Ruff format, deploy shell syntax and Python compile checks passed. Offline predeploy composer smoke passed with isolated MemoryStorage and mocked actor/lifecycle/upload/Telegram boundaries: direct settings, automatic photo, prompt launch, duplicate suppression, catalog exit and nonadmin denial;0 provider calls/Telegram sends/persistent application writes. Current production remains baseline6c0d09f and healthy; runtime price SHA256 recorded outside Git for preservation verification.

Final full safe regression on reviewed source64a46359: `python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short`:4067 passed,115 skipped,76 subtests passed (273.57s), no failures. Isolated test interpreter/dependency paths avoid modifying the production venv. No frontend changes; required browser/Docker CI gates still apply. Configuration/migrations/admin settings: none. Release proceeds through protected tanyapi PR; exact merge CI, autodeploy revision, health/static, price preservation, offline deployed-code smoke and telemetry must be verified before claiming production updated. Evidence continues in the PR conversation to avoid documentation-only production releases.

PR363 first hosted lint found UP017 in the new router test because hosted Ruff0.17.2 is newer than the shared local binary. Replaced datetime.timezone.utc with datetime.UTC; no application behavior changed. Installed Ruff0.17.2 only under/tmp and rechecked all6 changed Python files:passed. Re-ran actual Telegram router regression:passed. Full4067-test result remains for unchanged application code. PR head receives fresh required CI; native auto-merge method verifiedSQUASH and branch protectionstrict=true/all4gates.

## 2026-10-23 — Kling4 repeat session follow-up

Baseline277ebd7d8f7af41cafecca6ae325ad0291944dfa; branchfix/kling4-repeat-session from currenttanyapi. Final targeted audit reproduced P1 in legacy Repeat: a pending old caption/upload survived recipe replacement, merged into restored references and launched without a new prompt. All I/O mocked; no live create. Cancelled normal autodeploy39938250167 while it was still verifying release CI; production remains healthy6c0d09f. No manual deploy, price/config or database change.

Reproduction test extended the public callback/upload regression: Repeat case failed(1failed/2passed) before correction. Minimal fix shares intake-session reset between Clear and Repeat, clearing pending reference/error/album bookkeeping and rotating session ID before saving restored recipe. Existing durable message receipts/idempotency remain. Acceptance: late old work has no effect; a new prompt uses exactly the saved media/settings and launches once. Focused Kling4/coalescer, changed-line current Ruff, two-axis review and fresh protected PR to tanyapi required; final exact-SHA CI/autodeploy/production verification still pending. Same tdd/code-review + claw checklist + anthropics testing guidance as parent task.

Follow-up focused verification `python -m pytest tests/test_kling4.py tests/test_kling4_automatic_telegram.py tests/test_kling4_navigation.py tests/test_prompt_fragment_coalescer.py -q --tb=short`:82 passed(9.01s,6 existing aiohttp warnings). Ruff0.17.2 check/format passed. No paid calls or actual Telegram sends. Full safe/browser/image release gates apply to the new PR; local parent full result4067passed is retained as baseline evidence, not claimed as a new full run.

Follow-up independent review at58bac5db: Spec0 actionable findings(independent7 targeted tests passed); Standards0 material findings(independent3 replacement/navigation cases passed). Current Ruff changed-line gate0relevant/0legacy on2Pythonfiles; worktree otherwise clean. Parent release stopped before SSH; only final corrected SHA may be deployed. Required fresh full/backend/browser/image CI and normal autodeploy evidence will be recorded on follow-up PR.

## 2026-10-23 — Final composer release verification

PR363+364 release668d9d6727f469fd00e5e911e76d37bf61807198 verified: exact CI39940991575 and normal autodeploy39940991578SUCCESS; Docker OCI/root checkout/served Mini App revision matchexactSHA, healthy container and HTTPShealth200/statusok. RuntimepriceSHA256 unchanged. Installed-code offline Telegram smoke passed simplified keyboard/settings/auto-reference+prompt/dedup/Repeat isolation/catalogexit/admin gate,0provider calls/Telegram sends/persistent application writes. FinalPRCI4068passed/115skipped/76subtests; focused82passed. Scoped postdeploy log snapshot0Kling4errors; unrelated live Seedream/Seedance failures observed without expanding scope. Full evidence onPR364. No migrations/config/admin-price changes.

## 2026-10-23 — KIE Agent Kling4 reference binding audit

Baseline668d9d6727f469fd00e5e911e76d37bf61807198; branchfix/kling4-reference-mentions from currenttanyapi. User explicitly asked to use https://docs.kie.ai/ai-agent/overview and supplied @Image1/@Image2 identity-binding examples. Installed official kie-models via its documented discovery/installer into/root/.agents/skills/kie-models; readSKILL.md+Englishreference. FIND/READ workflow called authenticated read-only live catalog and both returned Kling4schemas(3GETs,0create). Existing modelIDs/method/fields matchlive schema. Provider syntax is@image_1/@video_1 and named@name; array order is1-based. Frame mode uses@first_frame/@keyframe_N/@last_frame. Current server rejects copied@Image1 tokens; Telegram automatic editor does not show the actual mappings. MiniApp already offers canonical tag chips.

Read-only runtime audit of4admin intents: latestReference task includes1image+1video, saved order preserved, no explicitbuiltin tags; other2keyframe+1text tasks also observed. This is not enough to diagnose visual identity quality or the user's exact two-person output. No private prompts/URLs/identities printed, no paid generation. Diagnosis hypotheses:1.tag-syntax mismatch(local supplied-example regression);2.media/order lost(compare persisted snapshot and provider echo);3.wrong mode(verify provider model);4.model fidelity(no visual claim without a scoped paid comparison). Keep fix scoped to deterministic binding, not speculative prompt rewriting.

Plan/acceptance: regression for common@ImageN/@VideoN aliases normalizing only to existing declared builtin tags, exact declared custom names retain precedence, missing/unknown tags fail beforePOST, normalized prompt respects8000char limit, original user request remains unchanged for durable idempotency. Show actual reference/frame/name mapping as text in Telegram with no new buttons. Shared validator covers MiniApp+Telegram; keep canonical MiniAppchips and provider fields unchanged. No DB/config/payment changes or hardcoded identity prompts. Tests at provider-contract/lifecycle/HTTP and Telegram seams, existing safe/browser/imageCI, two-axis review, protectedPR/native squash, exact-SHAautodeploy/smoke. Visual likeness is outside the verified claim; no paid test authorized for this follow-up. Skills:kie-models, diagnosing-bugs/tdd/code-review, clawPRchecklist, anthropics testing guidance. All3engineering playbooks refreshed before edits.

KIE evidence: read-only recordInfo on the latest persisted Reference task confirms provider model, prompt and image/video arrays/order exactly match the prepared snapshot; state success. Files are connected; no evidence of transport loss. No inference that this is the user's exact two-person incident. The reproducible local issue is the copied@Image1/@Image2 syntax: initial public-contract/HTTP/UI suite7failed/7passed before changes. Shared normalization preserves canonical tags/custom names, checks alias target existence, rechecks final8000char length, leaves raw request unchanged. Two additional red tests caught custom-name case collisions; they now reject ambiguous aliases rather than bind a different asset. Telegram displays actual typed reference/frame/name labels as text; MiniApp canonical chips remain intact.

Real owned PNG HTTP and Telegram seams verify two distinct file URLs reach the reference model in order with the canonical role prompt; repeated same request/message creates once; missing third image rejects before create; banana balance unchanged. Provider transport remains mocked. No DB/config/schema/payment changes. Focused/full validation and two-axis review underway; final release follows the existing protected tanyapi workflow.

Final focused source verification: `python -m pytest tests/test_kling4_reference_mentions.py tests/test_kling4.py tests/test_kling4_automatic_telegram.py tests/test_kling4_navigation.py tests/test_prompt_fragment_coalescer.py -q --tb=short`:100passed(11.13s,8 existing aiohttp warnings). New seam includes real owned PNG storage and actual MiniAppHTTP/Telegram composer through lifecycle to intercepted provider transport; idempotency/unchanged balance/unknown tags preserved. Current Ruff0.17.2 check+format and whitespace passed. No frontend source change required: existing canonical tag chips already align. Full safe suite and independent review are next.

Final local gate: isolated test Python full safe suite `python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short` exited0:4086passed/115skipped/76subtests(285.08s),732existing warnings. Both independent read-only review axes at69836e12 found0actionable findings; each independently ran the18new cases successfully. Current Ruff changed-line gate relevant0/legacy0 on all3changedPythonfiles. Prepared offline production replay passed locally: canonical two-image role prompt, exact adapter JSON/model/order, unchanged raw request, equivalent quote, visible labels and missing-reference rejection;0network/Telegram/DBwrites. Strict=true and all4required CI contexts verified; origin/tanyapi remains baseline668d9d67. No config/migration/admin changes. Release evidence will be recorded on the protected PR after exact-SHA CI/autodeploy and installed-code smoke; visual face fidelity remains untested.

## 2026-10-23 — Kling4 complete native Telegram controls and Elements

Baseline22c812a48a65f09c72bc61dfa84e16a878c01a28; isolatedfeature/kling4-full-controls from freshtanyapi. User requests full aspect controls, visible Elements, reference mode on open/upload and supplied dense inline-keyboard UX. Existing shared contract/MiniApp already support all native5ratios,720p/1080p, named image/video elements+voices, measured quotes/admin gate/durable intents. Telegram removed their visible entry points; legacy material editors can be reused. Fresh officialkie-models catalog+bothschemas(3GET,0create) confirm onlyauto/16:9/9:16/1:1/21:9,720p/1080p,3–30s,8000char prompt. Unsupported screenshot fields(4:3/3:4/480p/30000chars/global audio-off/filter/web/format) must not be represented as functional KIE capabilities. User informed of ratio restriction. No provider/schema/config/price/billing changes planned.

Acceptance/spec:1.open defaultsReference and visibly marks it;2.explicitReference/Keyframe buttons preserve separate drafts and do not generate; ordinary new references in a frame draft switch toReference retaining frames in order;3.all5native aspect ratios and both qualities directly selectable, selected state visible;4.duration stays−1/current/+1;5.Elements/voices reachable from main editor, create named2–4photo or singlevideo element and optional voice/tag/description, edit/remove/reorder with clear primary-image guidance;6.original-sound control only applies to reference videos, native-audio behavior explained;7.send prompt auto-launches once through existing lifecycle, noMainMenu/manualquote/launch;8.server admin enforcement, upload cancellation/session safety and exact provider payload retained. MiniApp already meets defaultReference/native ratios/Elements; audit its paths without redesigning its separate deliberate confirmation flow.

Public test seams are the existing Telegram callback/message/FSM and lifecycle/provider-adapter boundary, as authorized by the user's explicit behavior request and repository autonomy. Numbered implementation:1.red main-control behavior;2.restore validated controls and direct mode choices;3.red Elements upload/edit/lifecycle vertical slice and session/order cases;4.minimal reuse/refactor of material editor;5.docs/focused+safe+browserCI/two-axisreview;6.protectedPR/nativeSQUASH to tanyapi, exact-SHA CI/autodeploy and installed-code offline smoke/health/static/log verification. No DB migration/referral/payment mutation; existing admin settings/tariffs remain managed. Main risks: mismatched native capability, upload ordering(primary view), stale nested media callbacks, duplicate create and frame/reference material loss. Logs reuse existing safe actor/session/task IDs; no prompts/media/secrets logged. Primaryplaybooktdd/code-review; clawPRchecklist; anthropicswebapp-testing; officialkie-modelsFIND/READ. All3engineering playbooks refreshed before code edits.

Implementation progress: direct native-mode/quality/ratio keyboard; selected values visible; Element/voice menu reachable; new materials open their card; editing returns to card; image tag defaults to native inference and all categories remain selectable; frame pickers reachable. Original-sound button changes only reference-video audio, otherwise explains native audio. RED→GREEN public tests reproduced missing controls/card, reversed album primary image + duplicate receipt, duplicate generated name after deletion, and lost saved Elements/frame draft during automatic mode return. Fixed upload ordering/dedup within a field session, preserved explicit reordering, generated unique names across both namespaces, and resumed saved Reference materials while retaining the frame draft. Existing legacy field session regression exposed an absent-list append case; corrected and reran successfully. Focused103passed(11.38s,8existing aiohttp warnings); real owned-PNG Telegram→lifecycle→intercepted provider test verifies selected1080p/9:16+named element exactly once and unchanged balance. No paid creates. Full safe and independent review next.

Two-axis review at427ad05a: Spec0findings(7tests independently passed); Standards found one ordering bug when restoring previously auto-uploaded ordinary images plus frame images. Public Telegram regression reproduced old@image_1rebinding(RED1failed). Freeze restored+frame image order as a fixed prefix before appending new references; finalfocused104passed(13.93s), including new regression. Prepared offline full-control production replay now passes locally: all native controls, named photoElement/primary order/dedup, automatic launch, reference/frame draft preservation and original sound;0provider/Telegram/persistent writes. Local replay initially lackedADMIN_IDS in isolatedworktree; uses a synthetic administrator locally, production uses configured administrator without exposing its ID. Ruff check/format/changed-line and whitespace pass. Final fullsafe rerun and final review of the correction follow.

Final local verification at60897e01: full safe `python -m pytest tests/ --ignore=tests/live -m 'not live_smoke' -q --tb=short` exited0 with4094passed/115skipped/76subtests(308.45s,731existing warnings). Final focused104passed, each independent final review ran8newcases successfully; both axes0unresolved findings. Local isolated offline replay includes the saved-image-numbering correction and passes. Current Ruff check/format/changed-line gate and whitespace clean. No frontend source change: existing MiniApp already exposes native ratios/qualities/Elements and defaultsReference; mandatory browserCI remains required. No migration/config/admin-price/payment changes. Exact-SHA release/installed-code smoke/health/static/scoped logs remain pending and will be recorded on the protectedPR.

## 2026-10-23 — Kling 4 MOV reference regression
- Baseline: 548e6ad6, tanyapi. No schema, public-access or pricing changes.
- Evidence: accepted Telegram MOV upload reaches quote, then MP4-only contract rejects before KIE POST. Input duration is valid for an ordinary video reference.
- Acceptance: existing owned MOV recipes quote and launch with a persistent MP4 derivative; original recipe/hash/media preserved; no duplicate provider POST; ownership, concurrency, failure and byte-stream preservation checked.
- Red: test_kling4_mov.py::test_mov_quote_and_launch_preserve_original_and_reuse_mp4 failed with the exact user-visible video-format error.
- Implementation: shared lifecycle preparation used by both Telegram and Mini App, bounded local stream-copy remux and verified owner-scoped derivative reuse. No production provider requests in tests.
- Guidance: diagnosing-bugs (Bambale0/skills), provider metadata/idempotency rules (Bambale0/claw); anthropics webapp-testing considered, not applicable to backend media conversion.
- Verification: 100 focused Kling tests passed, including four new MOV tests; Ruff and diff whitespace checks passed. Synthetic MOV/MP4 video and audio packet hashes match. Exact-head CI and post-deploy replay of the affected draft quote pending.

## 2026-10-23 — Preserve Kling MOV inputs for Repeat

- Baseline: `847e316357f23d1effcd6da55d4bc9d8a713b651`, current `tanyapi`; inspected open PRs and found no active MOV-retention fix.
- Evidence: MOV preparation changes provider URLs; history stores that snapshot while owner Repeat restores `kling4_intents.recipe`. Existing cleanup did not inspect intents. Actual production file loss and configured TTL are not established.
- Scope: retain original and prepared intent references, including historical/terminal/private intents, under the existing storage lock and cursor. No backfill, schema/config/UI/API/access/pricing/provider-payload changes. No new lifecycle metadata duplication.
- Steps: (1) inspect shared lifecycle/retention/probe and CI; (2) add aged-MOV Repeat, snapshot, orphan and failure regressions; (3) include intent recipe/snapshot in optional lookup sources; (4) document and review the isolated draft; (5) execute safe verification when a compliant executor is available.
- Failure safety: absent table stays compatible; discovery/query errors propagate rather than permit deletion of the affected candidate. Existing filename-boundary and owner/admin semantics remain unchanged.
- Tests prepared: ordinary and element MOV across submitting/pending/unknown/done/failed, paged orphan cleanup, actual owner-recipe/quote/repeat with synthetic FFmpeg files and fake transport, snapshot without history, failed discovery, malformed recipe/snapshot columns, absent Kling table. Existing ownership/idempotency/conversion tests remain.
- Verification limitation: shell returned “No usable execution environment is available.” No Python/pytest/Ruff/FFmpeg checks have run in this task. No claimed red/green test result. Guided by Bambale0/skills diagnosing-bugs (execution phases blocked), Bambale0/claw small-change/test/idempotency guidance; anthropics webapp-testing considered but no frontend changes.
- CI safety audit: normal PR workflows include Wan Prime and Creator Tariff PostgreSQL jobs that would import the prohibited adapter. GitHub documents `[skip ci]` for push/pull_request; all repository workflow triggers were inspected. The only pull_request_target workflow is Tanya Auto Merge, whose job excludes draft PRs and runs no application code. No workflow_run trigger found. Publish only a draft with `[skip ci]`; do not bypass or change required checks. Unrun checks block release.
- Release boundary: no merge, auto-merge, production deployment, DB access, paid generation or live monitoring authorized or performed. Do not remove the CI skip directive while the import prohibition applies. A compliant isolated executor is needed for focused SQLite tests; release needs separately authorized verification and deployment. Retained bytes still consume normal quotas; deleted originals cannot be reconstructed by this fix.

### Follow-up verification at e714f275

- A fresh isolated executor became available. Initial execution exposed a test-fixture defect: the existing 320x320 MOV was too small for a video element (minimum short side 700). Corrected only the synthetic fixture to 720x720 in `e714f275d606e5eeb5b78d0fcfd1b67aa250f661`.
- Final exact changed source blobs verified: retention `b2df1e9bcc61fe4926de251235fc87f7b48e8dca`; MOV tests `f64aa455abc6cda9438d107682f48f8eafc95f43`.
- Isolated pytest runner invoked `pytest -p pytest_asyncio.plugin -q tests/test_kling4_mov.py tests/test_wan3_retention.py --tb=short`: **22 passed in 13.21s**, exit 0 (19 MOV + 3 existing retention).
- Execution isolation: Python 3.12.14/FFmpeg 7.1.5; allowlisted source only, actual application/test files, SQLite, fake transport, cleared environment and project dotenv disabled. Plugin autoload disabled; the eager `bot.services` package initializer was replaced by a namespace package. Network, PostgreSQL import and forbidden-file audit guards installed before pytest; zero guard violations. This does not validate package startup or PostgreSQL behavior.
- `ruff check --isolated bot/services/wan3_prime_retention.py tests/test_kling4_mov.py`: all checks passed. `python -m py_compile` on the same two files: exit 0.
- Red/green: with baseline `847e316` retention only, the done/ordinary expiry regression failed (`removed == 2` instead of 1, original incorrectly removed). Restoring the patch passed; final full focused run above used exact final source blobs.
- Independent static review found no blocking defect. Required CI/full-suite/PostgreSQL/build/release checks remain unrun. Keep draft and `[skip ci]`; no prohibited adapter access, paid generation, production DB access, merge or deployment occurred.

### CI and conditional release authorization — 2026-10-23

- The owner approved the narrow exception: the existing automated tests for PR #368 may read/import the PostgreSQL adapter, without changing it. Local read/import/restore remains prohibited. The prior CI hold above is historical and superseded only to this extent.
- Release is authorized only after genuine mandatory checks pass. Keep draft until checks/review are resolved; do not bypass protection, fabricate statuses, change workflows or run paid tests.
- Resume normal CI with this no-skip follow-up commit. The implementation and tested Python blobs are unchanged. Track current-head checks, then merge-SHA CI and the standard deployment pipelines; report deployed only with exact-SHA evidence. No ongoing runtime monitor is started.

## 2026-10-23 - Kling 4 targeted-media prompt dispatch

- Baseline: `100b2bb39cbc967fec6959427654ac7a2dcd0720`, `tanyapi`.
- Evidence: text entered after selecting a targeted media field was interpreted
  as a URL, and the automatic composer only accepted the main editor state.
- Scope: Telegram Kling 4 prompt dispatch only. No provider request, pricing,
  payment, public-access, schema, configuration, or deployment change.
- Behavior: plain text and media captions in a targeted picker are queued as
  prompts; dispatch waits for in-flight uploads, preserves the active field and
  ordering, coalesces prompt fragments, and launches once through the existing
  lifecycle. Explicit HTTP(S) text continues to import media.
- Race safety: queue entries are bound to the draft session, exact FSM state,
  and media-picker session. Navigation or a new picker invalidates stale input;
  existing message receipts retain idempotency.
- Verification: isolated Telegram/FSM lifecycle doubles passed 13 cases covering
  ordinary targeted dispatch; in-flight waiting; captions; first/last frames;
  Element images; Voice audio; validation and unexpected upload failures;
  out-of-order albums and duplicate messages; back, clear, and replacement
  media sessions; and an unknown launch outcome followed by duplicate delivery.
  Python compilation, Ruff, and whitespace validation passed.
  The isolated harness blocks the PostgreSQL adapter import and performs no
  network or provider operation.
- Remaining blockers: the two Library PNGs could not be installed locally
  because the official materializer requires `os.setxattr`, unavailable on this
  Windows executor; therefore visual UI parity is not claimed. No Kling 4 retail
  banana tariff exists in the inspected catalog, so no price was invented.
  Normal PR CI and deployment restore/import the prohibited PostgreSQL adapter;
  publication, CI, merge, and deployment remain pending explicit authorization.

### Admin-managed Kling 4 retail tariff

- Decision: the user confirmed that an administrator will set the price through
  the existing tariff administration surface. No numeric retail rate was added
  to source, `data/price.json`, or a database.
- Configuration: a complete `kling_4.billing_rates` block under the existing
  versioned `costs_reference.video_models` map contains per-billed-second rates
  for `reference`, `keyframe`, and ordinary-video reference categories at 720p
  and 1080p. The categories, quality and measured billed seconds come directly
  from the existing provider quote; no new aspect/Element/Voice/sound multiplier
  was inferred.
- Missing configuration: quote and launch stop with `Цена Kling 4 не настроена`;
  provider credits, zero, or a screenshot price are never substituted.
- Admin display: the nominal frozen `cost` is shown before launch, followed by
  `Для администратора списание отключено`; `charge_cost` remains zero and KIE
  credits remain a separate diagnostic value.
- Validation: the existing tariff publisher rejects partial, non-numeric,
  non-finite, zero, or negative Kling 4 rate blocks. Tariff changes alter the
  retail revision and immutable quote hash.
- Local verification: the initial 24 isolated cases passed across tariff calculation/admin
  validation and targeted prompt dispatch. The harness hard-blocks the forbidden
  PostgreSQL adapter and performs no provider, database, or production write.

#### Telegram tariff editor completion

- Audit found that the first tariff diff exposed only the whole-config publisher;
  no reachable Telegram button existed for Kling 4. The standard price editor now
  exposes `Admin → Prices → Video → Kling → Kling 4` even while unconfigured.
- The detail screen contains six stable buttons for Reference, Keyframe, and
  ordinary-video reference at 720p/1080p. Each button uses the existing numeric
  input FSM, saves through the price manager, verifies readback, and logs actor,
  category, quality, old value, and new value without prompts or secrets.
- Partial entry is allowed so the admin can fill the six cells one by one, but
  quote/launch remains blocked until the complete block validates. No numeric
  seed or production config mutation was added.
- Billing compatibility: `generation_tasks.cost` remains the actual debit `0`;
  nominal price is `quote.cost`, actual debit is `quote.charge_cost=0`, and
  `admin_free=true`. Kling 4 task IDs remain excluded from generic watchdog
  failure/refund processing.
- Local verification now covers 28 isolated cases: 12 tariff/config/history cases,
  2 real Telegram-admin navigation/save/readback cases with a manager stub, and
  14 prompt-dispatch/FSM cases. The normal database-backed lifecycle assertions
  for stored `cost=0`, nominal quote cost, `charge_cost=0`, admin-free metadata,
  and watchdog exclusion are prepared but not run under the adapter prohibition.


## 2026-10-24 — Kling 4 Telegram reference intake latency

- Baseline: `587b62bf2c4d03c1467a44dd93d54849a3a05af3`, current `tanyapi`, production container revision verified independently.
- Report: attaching a photo in the Telegram Kling 4 editor appears to load for much longer than ordinary photo intake in other models.
- Runtime evidence: a 223,657-byte photo handler took 69.218 seconds. The upload reservation was created only after the input-retention transaction completed; reservation creation through successful persistence then took 0.120 seconds. Concurrent ordinary photo handlers completed in 259–444 ms. No raw user media, prompts, tokens, user IDs or production dumps are included in this change.
- Root cause: the shared input-retention sweep holds the global storage/quota row lock over a batch of reference lookups. The production worker uses `limit=50`; each candidate can scan approximately 337,000 generation-task rows with an unindexed substring lookup. A live PostgreSQL activity/lock snapshot confirmed this lookup running in a long transaction while the storage relation was locked. Telegram download and KIE submission are not the waiting stage for the observed photo.
- Current scope: remove batch-wide contention between retention and new uploads; retain ownership checks, quota accounting, reference protection and deletion failure behavior; add stage timings to the existing Telegram upload path. Do not change models, prices, reference limits, provider payloads, Telegram FSM, public access or database schemas.
- Acceptance seams: the public media-upload/storage boundary must complete while protected-old-media discovery is deliberately paused; a candidate pinned after discovery must survive the final deletion check; existing expiry, quota, MOV/repeat and cancellation behavior must remain valid.
- Implementation plan: (1) record a deterministic failing concurrency regression; (2) shorten retention critical sections and recheck deletion safety; (3) log reservation/download/persistence timing without URLs or file IDs; (4) run focused regression, independent review and required CI; (5) verify the exact released SHA and production storage-lock behavior.
- Working copy: dedicated `fix/kling4-reference-latency-20261024` branch from the verified production baseline. The production checkout's mutable `data/price.json` is not edited.
- Guidance consulted: `Bambale0/skills/skills/engineering/diagnosing-bugs/SKILL.md`, `tdd/SKILL.md`, `code-review/SKILL.md`; focused `Bambale0/claw/.agents/skills/release-hardening/SKILL.md` guidance. The Claw-specific instruction index/registry files are absent here; this repository's AGENTS.md controls release. `anthropics/skills/skills/webapp-testing/SKILL.md` was considered; this change has no UI code and uses the repository's existing required browser gate.
- Verification plan: isolated unit/integration tests with a fake provider; no paid generation or outbound user message. See final implementation evidence below. Production acceptance compares the actual revision, health, current logs and bounded storage-lock admission during cleanup.
- Rollback: a normal reviewed revert through the protected `tanyapi` release path; no migration or data rollback is required.


### Implementation and verification

- Implemented independent expiry transactions for sessions, a committed page/cursor claim, unlocked protected-media screening and a fresh per-candidate locked ownership/identity/age recheck before unlinking. The final check discovers optional schemas again. All previous reference sources and fail-closed lookup behavior remain.
- Added Telegram reservation, probe admission, download, conversion, persistence and release timings, including failure/cancellation stage and exception type. Existing cleanup/exception semantics are preserved.
- RED evidence on unchanged baseline implementation: the new upload/retention concurrency test failed on SQLite (4.18s) and PostgreSQL (4.21s) because the real `init_upload()` waited for the paused lookup.
- GREEN, final candidate: `pytest -p pytest_asyncio.plugin -p pytest_mock -q tests/test_wan3_retention.py tests/test_wan3_prime_storage.py tests/test_kling4_mov.py tests/test_wan3_media_integrity.py tests/test_wan3_preprocess_admission.py tests/test_kling4_automatic_telegram.py --tb=short`: **71 passed in 21.63s**.
- PostgreSQL: `pytest -p pytest_asyncio.plugin -p pytest_mock -q tests/test_wan3_prime_postgres.py --tb=short`: **15 passed in 5.94s**, including both new concurrency cases, quota/idempotency and existing storage/lifecycle contracts.
- All tests used cleared application environments, project dotenv disabled, synthetic users/media and a fake provider. PostgreSQL ran in a dedicated disposable loopback-only container using the existing guarded test database. The old test interpreter lacked the runtime PDF parser; a separate QA interpreter with the unchanged runtime parser resolved collection/subprocess dependency errors without changing production packages or application guards.
- Ruff on all four changed Python files: pass. Python compilation and `git diff --check`: pass.
- Independent reviews: specification/concurrency review found no blocking issue; standards/security review found a missing release-failure timing, which was fixed and re-reviewed as closed. DB context-manager rollback/release semantics were verified in the unchanged adapter and pool.
- Residual limits: individual true-orphan checks and one session's filesystem deletion still hold their own lock. No full audit or new atomicity claim is made for reference writers outside the established storage-lock contract. The fix does not optimize the underlying substring queries.
- Documentation updated in `docs/kling4.md`. No schema, configuration, pricing or provider contract changes. Required CI and exact-SHA production acceptance remain pending release; no production deployment is claimed by these local results.


## 2026-10-24 — Kling 4 duration card

Baseline: fba034f1 (tanyapi). Duration callbacks called show(), which always sent a new message. Reproduced with 7 failing callback regression cases. Fix: opt-in editing for duration callbacks only; unchanged-message errors are benign, other Telegram errors propagate without duplicate send. Existing actor lock serializes changes. No migrations, pricing/config/provider/payment changes; Mini App unaffected. Tests cover increment, decrement, bounds, zero delta, unchanged and unrelated Telegram errors. Release via task PR and protected tanyapi CI/autodeploy. Production verification pending. Guidance: diagnosing-bugs (Bambale0/skills), callback checklist (Bambale0/claw); anthropics webapp-testing inspected, browser layer not applicable to Telegram-only change.


## 2026-10-24 — Kling 4 clean user messages
Baseline: 15cbe76c. Removed provider spend and raw statuses from Telegram launch/history/task/result notifications and Mini App generation/history screens. Provider recovery and JSON configuration controls are no longer shown in generation UI; backend support APIs and diagnostic logging remain available. Safe user validation stays visible; server/technical errors use neutral text. No billing, routing or schema changes. Seven callback regression cases failed before the fix; focused checks and release evidence recorded in PR. Release: protected tanyapi PR/autodeploy.

Verification: 14 new regression cases pass (launch, history/legacy callback, delivery, safe errors). Full selected run: 172 passed, one source-encoding assertion failed after JSX switched from Unicode escapes to readable Russian; assertion updated to retain exact admin-exemption copy, tariff suite then 16 passed. Production frontend build, TypeScript, and Kling4 Playwright mobile flows passed, including no provider metadata in visible text. ESLint: no errors, one pre-existing effect dependency warning. Guidance reused: diagnosing-bugs and callback checklist; safe config/pricing APIs retained while raw settings form removed from generation UX.

Уточнение Игоря: внутренние ID задач сохраняются в сообщениях запуска, истории, карточке задачи, результатах Telegram и Mini App. Расходы провайдера скрыты.

Final verification after preserving internal IDs: 173 Kling4 tests pass; rebuilt frontend and Kling4 Playwright pass. ID retention is asserted for launch and all delivery modes.
## 2026-10-25 — Public Kling 4 rollout in `tanyapi`

- Baseline: `3636431c11a079c6f85bb34e06567626326f8ce5`, branch `tanyapi`; production checkout and container label match this SHA and the container is healthy.
- User-visible result: ordinary users can open Kling 4 from Telegram and the Mini App, obtain the existing admin-managed retail quote, pay the frozen banana amount once, receive a result, and receive an idempotent refund on a proven provider failure. Administrators remain free.
- Runtime configuration: production already has all six Kling 4 retail rates configured at 4 bananas per billed second for 720p and 6 for 1080p. Public availability will be controlled by an explicit `public_enabled` flag in the mutable Kling 4 tariff block; missing/false remains admin-only. No rate is changed by this task.
- Current state: both clients hide Kling 4 from non-admins; HTTP, Telegram and lifecycle gates reject non-admins; lifecycle stores zero cost and has no paid settlement/refund columns; delivery is admin-only. Provider IDs, validation, durable intents, polling, result storage and nominal tariff calculation already exist and are reusable.
- Scope decisions: keep recipes/results private by default and keep prompt/publication actions disabled; enable the existing partner invite eligibility snapshot only for accepted paid user generations. Provider payloads, model limits, rates and KIE settings stay unchanged. Unknown create outcomes remain charged/reserved until operator reconciliation because a lost acknowledgement may hide an accepted generation.
- Security/data: Telegram `initData` remains server-verified; public access never trusts a client admin flag. Settings and provider-task adoption remain administrator-only. Owner checks remain on status/history/recipe. No secrets, prompts, media URLs or private IDs enter logs/docs.
- Schema: additive `charged_credits`, `refunded_credits` and `settled` fields on `kling4_intents`, created idempotently for SQLite/PostgreSQL. Debit and intent/task creation share one transaction; failure settlement and refund share one conditional transaction. Existing admin intents default to zero charge.
- Public test seams: authenticated Mini App HTTP boundary, Telegram FSM/catalog boundary, lifecycle balance/idempotency/provider boundary, and existing Kling 4 Playwright mobile journey. These are existing public seams and are selected from current repository prior art.
- Acceptance: (1) public flag off preserves admin-only behavior; (2) flag on exposes both catalogs and accepts ordinary authenticated actors; (3) quote freezes `cost`, `charge_cost`, tariff revision and admin exemption; (4) one idempotency key creates/debits once; (5) insufficient balance creates no intent/provider task; (6) deterministic or asynchronous failure refunds once; (7) unknown submission is not refunded or resubmitted and does not fill the ordinary active queue; (8) an audited admin-only reject refunds an unknown task only after exact `provider_not_created` proof; (9) success keeps the debit and delivers to ordinary users; (10) ordinary Telegram launch requires explicit price confirmation and duplicate confirmation cannot relaunch; (11) admin remains zero-charge; (12) settings/adoption/reject remain admin-only; (13) frontend shows payable price/balance and disables confirmation when locally unaffordable; (14) rollback is `public_enabled=false` plus a normal code revert if needed.
- Numbered execution: 1. add red pricing/access/billing/catalog/UI regressions; 2. implement config flag and actor-aware retail quote; 3. implement transactional debit/refund/partner metadata; 4. open Telegram and Mini App clients; 5. update Kling docs and run focused Python/frontend/browser/PostgreSQL checks; 6. review diff; 7. protected PR to `tanyapi`, exact-SHA CI/autodeploy, enable the live flag, and verify public catalog/API/health/logs without a paid production generation.
- Guidance: `Bambale0/skills` to-spec/TDD/code-review, `Bambale0/claw` backend-integration/telegram-miniapp/frontend-qa/release-hardening and KIE lifecycle guidance, and `anthropics/skills` webapp-testing. Claw-specific registries were checked remotely; this repository's `AGENTS.md` remains the controlling project instruction. No instruction conflict found.
- Local evidence: the public-release suite was written red first and is now green; the focused Kling regression set passes with the pre-existing POSIX-only directory-fsync upload case excluded on Windows. Review found and the implementation now covers waiting-then-failure settlement, queue capacity after unknown acknowledgement, an audited admin-only unknown rejection, and explicit Telegram confirmation before paid launch. Mini App has 74/74 suites and 567/567 tests passing, production build/type-check passing, ESLint with zero errors, and the Kling 4 Playwright journey passing for both a paid ordinary user and a free administrator. Python compilation and changed-file Ruff checks pass. PostgreSQL and full Linux browser coverage remain mandatory PR checks.


## 2026-11-01 — Admin preview for personalized repeats of published works

- Baseline: `da1aed2f4e5dd9069db9da60a52f595aa856b6c0` from `origin/tanyapi`; working branch `feature/admin-repeat-personalization-20261101`. No production deployment is authorized or claimed.
- User intent: an author can mark parts of a published image/video prompt as changeable (for example clothes or an object), and a person repeating the work chooses replacements. The server must retain the complete private/base prompt and the original image/video references. The earlier one-photo rollback is explicitly out of scope.
- Existing behavior: curated trends already have a safe `user_fields` contract and server-side rendering, but ordinary feed/profile publications expose only a free-form change field. The ordinary image and video repeat paths already compose edits with the hidden source prompt and restore typed/legacy references.
- Three prompt-loss hypotheses audited: (1) an empty or user-only client prompt replaces the private source prompt; (2) a second video handler/provider path overwrites the composed prompt; (3) legacy lineage or provider prompt limits truncate/drop either the base prompt or edits. Existing composition and continuity tests cover these boundaries; the new regressions extend them to structured values.
- Scope: add a separate admin-preview contract for ordinary published works. Configuration and use both require an explicit default-off feature flag and server-confirmed administrator identity. Public cards receive no configuration, public repeat behavior remains unchanged, and existing trend fields remain unchanged.
- Data: one additive table keyed by source generation stores canonical field definitions. Public/admin repeat DTOs strip `original_value`; only an authorized owner-detail/editor response may contain it. Unpublishing clears the configuration.
- Server boundary: normalize field definitions against the private source prompt, validate submitted values, render replacements into the hidden base prompt, then append any free-form changes with the existing remix composer. Apply this once at the shared image/video repeat boundary before provider submission; do not change provider routing or reference merging.
- Acceptance seams: authenticated publication API, safe feed/profile/deep-link DTOs, real image/video repeat endpoints through fake provider payloads, owner task detail, and Mini App forms. Tests must prove admin/flag rejection, hidden-base retention, exact replacements, reference preservation, unchanged legacy free-form repeats, and no leakage of original prompt fragments.
- Execution: write failing public-seam regressions; implement the smallest shared service/table and endpoint hooks; reuse the existing field contract in the Mini App; update operator/user documentation; run focused Python/frontend/browser checks where the local environment permits; perform independent standards and specification reviews before handoff.
- Rollback: leave the flag disabled (the default) and revert the reviewed code normally. No existing row or public flow depends on the new table.

### Release continuation

- Release authorization: Igor requested a production release on 2026-11-01 while keeping the feature administrator-only. The public gate remains unchanged: both the runtime flag and server-side `config.is_admin()` must pass.
- Rebased candidate: feature commit rebased cleanly from `da1aed2` onto current `origin/tanyapi` `0ca2dde`; candidate SHA before the release-evidence commit is `ccf0420`.
- Production preflight: server checkout and running image both match `0ca2dde`; container is healthy and local `/health` is OK. The only checkout differences are the protected mutable `data/price.json` plus its existing backup. The repeat preview flag is not yet present in production.
- Added release gate: `tests/test_repeat_personalization_postgres.py` exercises parallel revision writes through the real PostgreSQL adapter, and the existing `Runtime PostgreSQL Regression` workflow now runs it whenever this feature/schema changes.
- Local post-rebase evidence: repeat/image/video regressions **181 passed, 1 PostgreSQL-only skipped, 7 known legacy alias cases deselected**; adjacent publication/trend suite **22 passed**; focused Mini App Jest **28 passed**; changed Mini App ESLint passed; direct production Next build and TypeScript passed with an explicit Node heap limit; new Python files pass Ruff, YAML parse and Python compilation.
- Remaining release gates: commit/push, same-repository PR to `tanyapi`, native squash auto-merge, exact-head required CI including live PostgreSQL and browser/image gates, production autodeploy, production flag activation with `.env` backup, exact merge SHA/container/frontend health, admin-only smoke and logs. No paid generation is required for smoke.


## 2026-11-01 — PR 382 review recovery
Baseline 024525ea831010ef9e7b88c7f8fc9dd158fea7c4. Production exact image revision verified, healthy, preview flag already enabled. Audit confirmed installed feed/profile wrappers, editor state, WAN path, shared full-unpublish cleanup and choice-type defects remain. Work occurs in isolated task worktree; runtime price changes remain untouched. Acceptance: regressions red then green, admin-only backend gate, photo/video/WAN full prompt and consented media preservation, editor save/reopen, shared cleanup, protected CI/autodeploy and live authenticated smoke without paid provider calls. Guidance: diagnosing-bugs, Claw engineering/release discipline, anthropics webapp-testing.

- RED: 11/15 new backend regressions failed on the deployed baseline; actual editor test reopened with red dress instead of saved black suit; both WAN browser-component cases had no choice buttons.
- Fixes: installed feed/profile DTO hooks; canonical editor state after save and clear after hide; WAN repeat-plan/UI/client recipe plus pre-probe admin gate, same-request idempotency and transactional configuration fingerprint; atomic cleanup in every shared full-removal operation with parent-first lock order; choice validation at author save.
- Independent Standards/Spec review found lock-order risk, stale editor fields after hide and cascading replacement. All addressed; a new collision regression failed before UUID masking and passes afterward. Reviewer re-ran exact collision scenario and verified deterministic output.
- Backend selected regression suite: 235 passed, 1 PostgreSQL-only skipped before final collision addition. Focused frontend editor and WAN suites: 23 passed. Type checking caught updateTask accepting Partial<Task> despite updating task details; patch contract now accepts Partial<TaskDetail>.

- Final candidate verification: selected backend 238 passed, 1 dedicated PostgreSQL-only skipped; full Mini App Jest 74 suites / 573 tests passed; production Next export + TypeScript passed; changed frontend ESLint zero errors; new/changed focused Python Ruff and compile passed (two pre-existing unrelated RUF059 warnings remain outside changed lines). New mobile Chromium E2E: 8 admin/non-admin × image/video/WAN/WAN Prime cases passed with all network mutations intercepted; hidden-prompt regression passed at 360px and 430px. CI now runs the new editor/WAN Jest and mobile personalization E2E, and reruns PostgreSQL concurrency on changed shared paths.
- No production source/config mutation made in this continuation; existing enabled admin-preview flag is preserved. Release through protected tanyapi PR/autodeploy; exact-SHA production acceptance pending.
### PostgreSQL schema follow-up

- Production merge `024525ea` deployed successfully and passed exact Git/image/frontend/health checks. The server-side flag and administrator authorization gate behaved correctly, while a read-only schema smoke found that `generation_repeat_personalization` was absent.
- Root cause: the PostgreSQL compatibility adapter intentionally skips SQLite-shaped `CREATE TABLE` and `ALTER TABLE` statements from `database.init_db()`. The first PostgreSQL regression had created the feature table manually, so it tested locking but not native bootstrap coverage.
- Fix: create and upgrade the table in `_ensure_postgres_helpers()`, which is the existing native PostgreSQL schema boundary. The real PostgreSQL regression now performs an ordinary feature read before any raw SQL and asserts the native columns; it no longer creates the table itself.
- Safety: the public repeat flow remains unchanged, the preview still requires both the feature flag and server-side administrator identity, and the follow-up performs no paid generation or data backfill.

- Exact-head CI exposed legacy refund fixture schemas without model. Removed the unnecessary model-column dependency from the locked watchdog RETURNING; guards now match the route by task_id. The original runtime PostgreSQL matrix is rerun unchanged. Added the new 20-test native PostgreSQL fallback suite to runtime-postgres CI and its path triggers.

- Automated review corrections: durable result directory excluded from real 24h cleanup (tested with aged private output); provider status/download exceptions isolated as unresolved so later KIE rows continue; terminal primary payloads retired; primary GET memoized per status lookup. New review regressions reproduced RED, then routing suite 26 passed on SQLite and PostgreSQL.

- Full safe CI ran 4295 passing tests and exposed an AST-isolated motion test dependency on a newly imported Mapping name. Removed that unnecessary global dependency from the watchdog Row protocol check; re-ran the actual motion financial lifecycle plus watchdog/routing suites unchanged.

- Follow-up review: ordinary Seedance25 default aligned to first fixed ratio, preserving explicit Auto and frame/edit adaptive; status RuntimeError isolated; content retries persist a finite budget and lease, terminal failure scrubs payload and enables refund; timestamped unowned ready/primary TTL cleanup runs on register and daily housekeeping. New regressions RED -> 30 passed on native PostgreSQL; public form/identity/edit Jest 22 passed. Both additional real image-reference fallback smokes completed; exact IDs retained in operational evidence.
