# NEUROMIX: cross-platform architecture audit — 2026-11-20

Scope: repository Bambale0/banano_kling, branch fix/web-independent-yandex-entry-20261120, PR #646 targeting tanyapi. Production Docker SHA before work: 0aac0576fe1f403b391957dd802d1c45af8ff327, healthy; current changes are isolated, not deployed.

Mission: one Mini App interface and backend execution lifecycle for native Telegram, independent Yandex/Google/Email browser logins and linked accounts. Account identity derives from verified server credentials. No synthetic Telegram identity for web-only users, no cross-account leakage, no double billing, no mutation of unrelated VK production.

Method: project AGENTS.md + README + ADRs; Bambale0/.agents skills: agents-global-router, cross-platform-contract-propagation-audit, codebase-design, frontend-ux-audit (full-audit-checklist), test-driven-development. Source-to-consumer propagation status categories: PROVEN, PARTIAL, MISSING, CONFLICT, UNKNOWN. No paid external tests or live database changes conducted.

## Executive finding

The provider backend largely exists. The obstacle is not the number of models but two distinct ownership, balance and generation/task lifecycles. Opening a second web workspace beside the Telegram Mini App increases the drift. A single UI cannot be switched on just by accepting a browser cookie because its legacy backend assumes a Telegram user ID and legacy financial writers.

## Evidence by layer

| Layer | Telegram/legacy | Browser PR #646 | Audit status |
|---|---|---|---|
| UI | app/page.tsx -> MiniAppShell/TabContent | account-platform-entry.tsx -> separate WebAccountWorkspace | CONFLICT: not one application |
| Auth | bot/miniapp.py::_get_user_context verifies Telegram initData and resolves numeric telegram_id | bot/web_auth.py::_session_account uses signed browser cookie and shared_accounts.id | PARTIAL: different actor contracts |
| Linked users | shared_account identity can link a verified Telegram user | web_auth_studio returns signed legacy initData only when a real linked Telegram owner exists | PARTIAL: compatibility bridge, not cross-platform account |
| Balance | users.credits plus legacy writers, refund, admin and provider job SQL | WalletService(live) in shared_wallets and append-only ledger | P0 CONFLICT: two authorities |
| Payments | legacy Telegram and platform payment handlers | web_commerce.py Lava invoice verification, credit and reconciliation | PARTIAL: account-only payment does not merge legacy funds |
| Catalogue | miniapp.IMAGE_MODELS and VIDEO_MODELS, plus dynamically injected Seedance 2.5/Kling4 | web_generation._models originally only static lists | P1 CONFLICT: missing models |
| Job execution | miniapp.py plus specialized Seedance/Kling/Wan handlers and generation_tasks | web_generation.py independent normalizer/dispatch/worker and web_generation_tasks | P1 CONFLICT: duplicate lifecycle |
| Media | existing uploads and S3, TG delivery/webhook and retry | web owner-scoped references, S3 output, own task history | PARTIAL: no unified history/delivery |
| Referrals | bot partner-policy and Telegram conversions | web_referral_attributions and browser referral links | PARTIAL: paid web commissions not unified |
| VK | older code and preview workspace remain after requested production rollback | VkAccountGate in frontend source | OUT OF SCOPE for production restoration |

## Verified model inventory

Isolated read-only Python inventory: static Mini App models = 10 image + 14 video = 24. VIDEO_MODEL_CAPABILITIES contains 23 entries. Ten capability keys are outside static VIDEO_MODELS: gemini_omni_audio, gemini_omni_character, gemini_omni_video, glow, seedance_2_5, seedance_2_fast, seedance_2_mini, v3_4k, veo3, veo3_lite. These are not necessarily ten additional purchasable models: some are submodes, aliases or capabilities. The static list also contains gemini_omni as the user-facing alias.

Seedance 2.5 is already public and integrated into Telegram backend: seedance_25_service.py and handlers/seedance_25_fullstack.py, seedance_25_public_release.py, chunk_upload, video_ref_pricing, webhook and provider fallback. It is injected into Mini App bootstrap at runtime, outside static VIDEO_MODELS. Existing provider routing in running production config is Neironych primary and KIE fallback; do not duplicate it for web.

Kling4 is another dynamic rollout source: miniapp_bootstrap conditionally adds kling4_catalog_entry when admin or kling4_public_enabled. Future common model registry must respect the actual rollout and authoritative pricing.

This PR now projects seedance_2_5 from existing model capabilities in the browser catalog with enabled=false and explicit reason. That accurately reflects its existing Telegram availability without enabling an unverified web charge. Isolated web catalog after fix: 25 positions; 22 have enabled=true from checked-in test price/config. This is NOT a count of proven live models; WEB_NATIVE_GENERATION_ENABLED defaults off.

## P0: financial authority and migration

Project ADR docs/adr/20261106-opening-balance-readiness.md states production shared-wallet cutover is NOT READY. Existing opening claims schema only permits sandbox scope. Old Telegram and VK writers remain authoritative; existing historical balances are not transferable with a simple join or read fallback.

Required cutover: inventory and fence every writer/webhook/refund/bonus/partner path; immutable cohort balance manifest with exact precision policy; outstanding paid jobs/reserve/partial refund snapshot; event watermarks and replay dedup; one-time shared opening claims; PostgreSQL concurrency and crash/rollback verification; reconciliation with zero unexplained differences. Never sum or max legacy balance with new wallet balance. Never use client account_id or a synthetic TG ID.

Release gate: all credits/debits/refunds operate on one authoritative wallet per canonical shared account with exactly-once event semantics and no legacy double writers, before exposing shared balances in one UI.

## P1: authentication and user interface

Existing browser-only user was mistakenly treated as Telegram by browserEntryMode when unauthenticated. RED Jest reproduced. The first attempt to navigate with Next router to /login became /mini-app/login/ because of Next basePath; Chromium E2E reproduced. Changed to a document-level navigation to the real /login page, with allowlisted referral and payment context. Native Telegram launch precedence unchanged. The prior white-screen config loading state now has a status message, a 10s timeout and actionable retry.

Remaining: unify server-side ActorContext(account_id, verified channel, optional telegram_id, entitlements) for all endpoints; ensure revocation, account merge, session expiry and cross-user access checks are consistent; move read-only bootstrap and history before touching any financial writer. Keep existing Telegram launch and Star checkout unbroken.

## P1: generation backend and model registry

Do not expand web_generation.py into another model-by-model dispatcher. Introduce one deep GenerationService interface for verified actor + canonical model request to price/validate/reserve/submit/status/settle/deliver, behind which existing Seedance, Kling, Veo, Wan, Gemini, KIE and other providers remain the implementations. Store task ownership by canonical shared_account_id; preserve legacy task mapping and failed/pending/refund history, not fabricate a new charge for previously paid tasks.

Build a catalogue whose producer is registered runtime models and configured entitlement/price, not hardcoded static tuples. For each model, test that the declared modes, durations, resolutions, refs, price and provider dispatch agree across Telegram/web. A model capability declaration does not imply that a separate priced product may launch.

## P1: history, delivery, payments, partners

A browser-only user currently sees WebAccountWorkspace and web_generation_tasks; Telegram user sees MiniAppShell and generation_tasks. Their history, repeat, feed and Telegram delivery semantics differ. Cross-platform release requires one owned task view and same app tabs. Persist S3 result once, deliver to any available channel separately, with retry/reconciliation IDs.

Web Lava payments and referrals have separate recorded flows. Real invoice/webhook callbacks, partner payouts, Star-only native TG behavior, account merge and linked wallet must be verified under feature flags before release. Do not infer correctness from mocked unit tests.

## P2: UX and observability

Add structured correlation fields: actor_id or privacy-safe account pseudonym, task_id, model, provider_task_id, request_key, wallet operation key, settlement status, S3 result and delivery status. Do not log cookies, auth tokens or full prompts. Audit UI buttons, performance waterfall, slow requests, mobile safe areas, Cyrillic/long filenames and slow-media retries. Chromium tests alone do not prove iOS Safari or Telegram WebView functionality.

## State-by-platform verification matrix

| State | Expected | Evidence | Status |
|---|---|---|---|
| Anonymous web + referral | /login with valid referral, no TG bridge | Jest + Chromium 390px | PROVEN after fix |
| Native Telegram initData | legacy MiniAppShell without extra login | Jest precedence test | PARTIAL; real Telegram WebView not run |
| Yandex-only linked to no TG | own cookie/account without forced TG | existing web tests and E2E | PARTIAL; different UI |
| Browser+verified TG link | optional legacy bridge, no spoofed user ID | existing tests/E2E | PARTIAL; no shared wallet authority |
| Google/Email-only | verified web cookie, no required Telegram | code tests | PARTIAL; live OAuth/OTP not checked |
| Browser Seedance 2.5 | visible, no unsafe purchase | web catalog + pytest | PROVEN fail-closed; actual web execution missing |
| Other runtime-only models incl Kling4 | visibility respects actual registry + rollout | source audit | MISSING common catalogue |
| Unified balance and history | same authoritative account across channels | separate ledgers/tables | MISSING, release blocker |
| Real Lava, KIE, S3 settlement/delivery | exactly-once paid operation and visible result | isolated mocks only | UNKNOWN live |

## Implementation in this worktree

- Anonymous external browser now uses root /login rather than legacy Telegram bootstrap, preserving only safe query keys.
- Loading state, timeout and recovery UI on browser auth.
- Seedance 2.5 capability projected into browser inventory from existing model registry; disabled in browser until account-aware shared execution exists, no false charge.
- Tests: new negative and positive Jest/browser checks and backend catalogue regression; no production flags or money changes.

## Required implementation sequence / release gates

1. Implement read-only ActorContext and shared catalogue/entitlements, prove linked/unlinked/no-TG users get the same safe data contract. Include real native WebView tests.
2. Finalize legacy financial cutover with writer fence, exact balance import, historical event watermark, pending jobs and refund mapping; approval and regression before any live shared debit.
3. Migrate task execution to a single module calling existing providers; start with Seedance 2.5 because public Telegram path and all media modes exist. Model contract matrix and real provider-paid smoke must pass.
4. Migrate history, media, publishing, notifications, referral payouts and optional Telegram delivery.
5. Switch root UI to one MiniAppShell/TabContent only after account/task/wallet parity is verified. Keep Telegram Stars and web Lava separately allowed by channel.
6. Full CI, Postgres concurrency, browser E2E at 320/390/768/1440, production-staging real KIE/Lava/S3 scenarios, rollback drill, deployed SHA, health and visible user result.

Verdict: single-app cross-platform production release is BLOCKED by P0 financial authority and P1 missing shared actor/task/lifecycle contracts. Do not merge Draft PR #646 as if it solves 100% parity. Preserve existing provider integrations; refactor shared seams, not per-model adapters.

## 2026-11-20 fresh production read-only financial census (no per-user data)

Script scripts/audit_shared_account_migration.py against the running production PostgreSQL, READ ONLY REPEATABLE READ:
- Telegram users: 94,490; generation_tasks: 392,126; transactions: 35,997.
- Legacy users.credits remains double precision; 93,636 exact 4dp balances, 854 precision_review, 0 invalid.
- Separate read-only calculation compared Decimal(str(float)) to ROUND_HALF_UP 4dp WITHOUT applying it. All 854 nonzero residuals are <= 2.119e-11, none > 1e-9. This is quantitative evidence of float noise, NOT automatic approval for a rounding policy.
- Current generation_tasks status aggregates: 356,801 completed; 35,341 failed; 3 pending; 4 processing. Seven tasks potentially in-flight require state/charge/refund reconciliation before snapshot.
- Current transactions status aggregates: 18,338 completed; 5,525 failed; 12,134 pending. Pending does not imply funds payable; reconcile provider IDs, source events and age first.
- Shared wallet preview: 40 sandbox wallets and 40 live wallets, each group with 0 aggregate available and reserved units. There are 0 opening claims; no production financial cutover has run. 883 shared_accounts, 877 shared_account_identities, 6 web_auth_sessions, 4 web_auth_identities at read-only inspection. These are not proof of a stable snapshot and must not be used as a new money authority.

## Incremental verified identity seam

PR #647 is a separate small non-draft PR targeting tanyapi with read-only AccountActor and source-scoped wallet_authority. This code is also included in Draft PR #646 to avoid future divergence. A backend-issued browser_* Telegram-shaped token is not native Telegram WebView authentication and now needs an active same-account website cookie; after logout it cannot claim the native legacy wallet through the new actor endpoint. Existing legacy provider handlers are untouched. PR #647 CI must pass before normal branch auto-merge/deploy. This identity seam by itself does NOT complete one Mini App or transfer historical funds.
