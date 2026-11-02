# Contextual top-up inside a Mini App video repeat — execution ledger

- Date: 2026-11-02
- Project: NEUROMIX / Bambale0/banano_kling
- Baseline: `tanyapi` at `e584d005082ed818ec26cdbd4652dc3d20bfa9cc`
- Branch: `feature/contextual-repeat-topup-20261102`
- PR: https://github.com/Bambale0/banano_kling/pull/394 (draft until verified)
- Skills: `Bambale0/.agents` — `frontend-ux-audit`, `frontend-api-integration-patterns`, `payment-integration`, `test-driven-development`; project `AGENTS.md` and `Bambale0/skills` `to-spec`.

## User-visible outcome

When a repeat video requires more 🍌 than the user's current balance, show the confirmed generation cost, current balance, shortage, and the smallest configured package sufficient for the missing amount. Show a larger package (if available) and a link to all packages/methods. Explicitly separate rubles or Stars paid and bananas credited. Opening payment must not clear the open editor. After payment, update the wallet and let the user explicitly return to the same repeat and press Generate; never auto-start paid work.

## Observed baseline

- `frontend/miniapp-v0/components/forms/video-generator-form.tsx` already had server-side quote/hash for video references; the UI only displayed a disabled button when short.
- Additional editors: `trend-runner-dialog.tsx`, `seedance25-public-form.tsx`, `wan3-prime-form.tsx`.
- `balance-sheet.tsx` already creates checkout through `lib/payment-api.ts`, with Robokassa and reserve methods. Authentication and provider wrappers live in `bot/miniapp.py` and `bot/handlers/*payments*.py`.
- `lib/app-context.tsx` already polls authenticated bootstrap on focus/visibility and every five seconds.
- Package prices and bonuses come from existing `data/price.json` / backend preset manager and are configurable by admin. No new fixed prices/providers required.
- Live bootstrap error paths contained fallbacks to mock package prices. This can misinform customers.

## Design and security decisions

1. Add pure `selectTopupPackages` helper using live `PaymentPackage[]` only. Filter invalid prices/quantities; compare `credits + bonus_credits` against **shortage** `max(0, generation_cost - current_credits)`, not full generation cost.
2. Place a reusable contextual offer after a confirmed quote; never invent a price for video references, WAN reserved output, or unavailable models.
3. Pass a `BalanceRequest` (`packageId`, `requiredCredits`) into the existing balance sheet. Highlight/sort the selected package but leave every existing available checkout method untouched.
4. Keep the generation form mounted while payment is opened. Avoid full-window navigation fallback if popups are blocked; preserve the existing signed checkout anchor.
5. Do not store private prompts/references in localStorage, query params, client logs, or the payment transaction. When re-opening the Mini App from a fresh process, the original feed/trend link is the recovery entry point; restoring arbitrary unsaved custom edits across a terminated Telegram WebView is not yet guaranteed.
6. Recompute authoritative price before final generation if inputs changed. Existing quote hashes and backend checks stay authoritative.
7. No changes to money movement, webhook verification, charging, refunds, referral credit, or provider payloads. No auto launch after payment.
8. Do not show mock prices to authenticated users, even when bootstrap refresh fails.

## Changes in PR

- `lib/contextual-topup.ts` with selection and validation.
- `components/generation-funding-offer.tsx` with accurate explanatory copy and user-initiated checkout.
- `lib/app-context.tsx` with context-backed package selection, refreshed wallet, and no fake live-price fallback.
- `components/balance-sheet.tsx` with selected package at top, return-to-video affordance, and no navigation-away fallback.
- `video-generator-form.tsx`, `trend-runner-dialog.tsx`, `seedance25-public-form.tsx`, `wan3-prime-form.tsx`: shared offer wired behind validated pricing.
- Frontend unit and UI tests added for selection, billing clarity, no auto-launch, balance-return and package ordering.

## TDD and verification

- RED verified on test-only commit `68bbabad100186403ad179f3cc592d6f1b1d7b28`: miniapp-build failed at TypeScript with `TS2307 Cannot find module './contextual-topup'`, because the feature was absent. This is expected.
- GREEN: re-run on latest PR head after all code and tests; **pending CI verification**.
- Run focused Jest tests, TypeScript static build, lint and Playwright Mini App E2E on PR.
- Payment safety: no duplicate invoice creation on suggestion click, no duplicates on webhook replay, and no auto-launch; current underlying payment invariants must remain unchanged.
- Production release: only by protected PR into `tanyapi` and exact-head green CI + review. Verify deployed SHA, wallet bootstrap, iOS/Android Telegram payment exit/return, quote and launch manually. **Not yet deployed or manually verified.**

## Risks and follow-ups

- React form state is preserved while the existing Mini App instance remains mounted; fully terminated WebView with unsaved user input requires a server-side authenticated expiring repeat draft, outside this small financially safe slice.
- Some checkout providers might be disabled at runtime despite package metadata; existing backend remains final authority and returns an actionable error. Validate production methods before release.
- Trend editor uses nonmodal Radix mode so the top-level balance sheet stays interactive without remounting state. Check accessibility and outside-click behavior in browser E2E.
- No paid production generation must be used solely to prove this UI feature.

## Convergence follow-up after PR #394

- PR #394 merged while the direct video-repeat task was in CI. Its shared contextual offer for videos, trends and WAN remains the base implementation; the follow-up preserves those surfaces instead of replacing them.
- The user's voice instruction requires an insufficient repeat to land immediately in the payment form. After an authoritative repeat quote, the shared offer now opens the existing balance sheet once with the recommended package selected. This only opens UI; invoice creation still requires an explicit user tap and generation never auto-starts.
- The automatic sheet states required credits, live balance and exact shortage, offers one direct configured checkout action, and retains the complete package/payment list. Closing it leaves the shared inline offer available for an explicit reopen.
- Recommendation uses the smallest configured total grant (`credits + bonus_credits`) that covers the shortage. A Stars-only package is labelled and invoiced in Stars rather than promising a ruble checkout.
- Generic video repeats use the existing repeat-session identity for deduplication; Seedance identity repeats use their own repeat session. Administrators and server `admin_free` quotes never open payment.
- Added focused component and mobile browser regressions. The mocked browser scenario asserts `15🍌` required, `7🍌` balance, `8🍌` shortage, a configured `10🍌` package, explicit reopen, and no generation mutation at 320/390/430 px. No real payment or paid generation is used.

### Follow-up verification for PR #396

- Reconciled on `tanyapi` at `72716c92a1172f1449e6ca693cc7ec633daa4a2c`, preserving the shared PR #394 implementation.
- Local GREEN: 79 Jest suites / 606 tests, TypeScript `--noEmit`, changed-file ESLint, production Next.js export, and the mocked mobile browser flow at 320/390/430 px.
- Independent spec and standards reviews found no remaining actionable issues after fixes for server-free quotes, bonus credits, Stars-only packages, and the no-single-package fallback.
- Production merge and exact-SHA deployment verification remain gated on protected PR #396 and required CI. No real invoice, payment, or paid generation was used.
