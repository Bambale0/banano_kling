# Execution ledger

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
