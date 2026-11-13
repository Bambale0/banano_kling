# NEUROMIX VK Mini App: platform parity release gates

## Product contract

VK Mini App **must use the same MiniAppShell and TabContent with 7 visible VK tabs** (Motion remains Telegram-only) as
Telegram, with genuinely supported operations and no required Telegram account.
Do not gate core VK functionality on linked_platforms or fabricate a Telegram
user ID. Keep native VK SQLite money and paid generation tasks authoritative
until an audited and reconciled financial migration. Platform linking remains
optional and never silently copies credits.

## Verified current architecture (2026-11-10)

- A signed and revocable VK session exists in shared_accounts and VK can read
  its native VK balance and task summaries without Telegram.
- Common bot/miniapp.py:_get_vk_session_user_context currently requires a
  linked Telegram account to access legacy /mini-app/api routes. Nearly all
  common data and payment routes use that legacy actor.
- Frontend AccountPlatformEntry renders the full common MiniAppShell only if
  access.telegram_linked. Native VK-only visitors see VkStandaloneDiscovery,
  not the full same app. Showing tabs without backend routing is NOT parity.
- Common backend native photo bridge + owner-scoped image uploads + approved
  image trend repeat shipped in banano_kling#447. Native VK photo HMAC RPC
  shipped in tanyavk#72. A separate photo flag is enabled in production after
  quote-only and controlled generation smoke; provider success and duplicate
  request idempotency were verified. The synthetic test task 14216 was
  refunded exactly once; it must not be interpreted as a real VK-device E2E.
- Native VK video HMAC RPC is prepared in tanyavk#73, with an independent
  OFF-by-default VK_MINIAPP_VIDEO_WRITES_ENABLED switch. This branch adds
  the matching signed VK-session BFF route /account-preview/vk-video. Both
  remain OFF until provider, reconciliation, and UI checks finish.

## Required real parity acceptance

| Domain | Existing source | VK-only completion requirement |
|---|---|---|
| Actor/session | shared_accounts signed VK session | PlatformActor identity throughout all APIs; no Telegram surrogate |
| Shared layout | MiniAppShell, TabContent | Seven VK tabs, sharing all eligible TG screens, excluding Motion |
| Photo | native VK photos | full model/reference/ratio/quality parity, quote, paid task, delivery |
| Video | VK native video worker | all supported TG model/quality/reference options excluding Motion, quote, retries, reconciliation |
| Motion | Telegram only | Not in VK release scope; hidden in VK navigation and readiness contract |
| Feed/trends | shared catalog & private TG generations | VK-owned uploads, private repeats and publishing with ACL |
| Services | TG prompt, voice, music, AI assistants | platform-neutral processing, payment and delivery |
| Profile/tasks | native VK SQLite state + TG PG profile | VK-owned editable profile, tasks, media, status, saved references |
| Payments/referrals | VK native wallet vs TG wallet | native card/SBP payments, receipts, exactly-once ledger and rewards |
| Delivery | VK messages + in-app state | idempotent result delivery, durable URLs, user-permission fallback |
| Security | VK signed launch and HMAC BFF | replay, malformed, cross-user, linked/unlinked access tests |
| Release | two production services | same release SHA, full CI, signed WebView and paid/refund E2E |

## Financial invariants

- Quote does not mutate balance. Native VK service computes cost; ignore any
  client-supplied cost, role, identity or provider configuration.
- Every charged generation has one native task and one idempotency claim.
- Unknown provider state must be reconciled before re-submission or refund.
- Production feature flags default OFF for unsupported flows.
- On linked accounts, never double-charge or double-reward across wallets.
- No full-VK-shell switch until every required API is ready to serve the
  authenticated VK actor rather than silently creating a Telegram owner.

## Proposed boundaries

A typed verified actor should carry (platform, shared_account_id, external_id)
through the request. Platform-specific wallet, task, payment, reference,
notification and social-domain adapters must use it, while sharing provider
orchestration and frontend components. Migration must have a reviewed ledger
reconciliation and reversible cutover; database user_id equality across
Telegram/VK does not establish common ownership.

## Current status

Partial photo generation is production-enabled. The product is NOT 1:1 yet:
video/services/payments/publishing and the full seven-tab VK-only shell are
outstanding. Do not claim completion merely because a backend HMAC endpoint
exists or UI components can be rendered.


## Shared BalanceSheet native VK checkout (review-only, 2026-11-12)

The shared VK navigation must not use Telegram `createPayment` or its
`bootstrap` request even when the visible package offers Lava. A verified VK
actor obtains its own `vk-commerce` view, `payments_enabled` gate and
Lava methods/packages from the authoritative native SQLite-backed service.
The same shared `BalanceSheet` mounts `VkNativeCheckout` only after that
verified read, and carries the exact native idempotency claim across close and
reopen. Disabled payments, transport failures and unregistered VK actors
render no checkout actions, never a Telegram fallback. No flag is activated by
the UI change.

**Not full #451 parity**: the backend still lacks callable native handlers
for the ten-domain shared shell, including services, feed writes, complete
video/references, referral/payout reconciliation and result delivery. The
shared-shell readiness must remain false until live VK WebView and financial
acceptance proves those end-to-end paths.


### Wallet snapshot and invoice immutability follow-up (review-only)

The shared VK BalanceSheet does not display balances, repeat deficits, or task
statistics from the legacy Telegram application state. It renders the signed
native VK commerce balance only after validating a finite, nonnegative numeric
snapshot. Invalid/missing native balances fail closed without an invoice action.
Once a native invoice request has been issued, the form freezes its package,
method and email for that checkout attempt: ambiguous timeouts and native
`creating`/`unknown` states may be retried **only with the exact original
payload and idempotency claim**. This prevents a second invoice being created
by editing the terms while the first provider result is unresolved.

A fresh invoice with a new idempotency key is available only after the
previous attempt has been **confirmed paid**; ambiguous and pending attempts
remain immutable until a verified status is returned.


## 2026-11-13 — Incremental VK native shared-shell bootstrap (#451)

`VkNativeAppAdapter` is registered only as an incomplete adapter (`bootstrap`, `tasks`). Its signed VK actor reads the authoritative native VK state, dynamic model catalogue and commerce wallet, not the Telegram account. The existing 10-domain `full_vk_adapter()` gate rejects it until the remaining native domains are implemented and verified. `VK_FULL_APP_PARITY_ENABLED` and the money/write gates remain OFF by default; no ledger migration or new paid action is introduced. This release slice does **not** constitute full seven-tab VK parity.

## 2026-11-13 — VK generation reconciliation (incremental, no wallet writes)

Native VK master 750d1a2a46bd97aec30a3a4a96b9a856d4d311cc provides a
signed read-only POST /internal/v1/miniapp/users/{actor}/generations/claim
over the existing atomic SQLite claim table. The common VK-only BFF authenticates
the signed owner and returns only task ID/type/status/cost, never private recipes.

The existing independent VK photo panel now checks the original claim after an
ambiguous timeout. A confirmed task displays its ID, rather than submitting
a duplicate; an unavailable lookup keeps the original idempotency key for a
manual retry. No silent repeated paid request, no balance migration or rate
override. This is NOT readiness for the full ten-domain #451 shared shell.

## 2026-11-13 — basic native VK video-trend repeat bridge (review-only)

A signed VK-only user may quote/repeat **basic** curator-approved image-to-video
trends through the existing `vk-trend` BFF. Exact editor prompt, model,
duration and ratio are read server-side from the approved and publicly visible
recipe. The worker's own dynamic model catalog validates the model, image
reference limits, duration, supported scenario and aspect, and computes the
native wallet cost. User references must be verified as owned by the signed
VK actor; the source ID never authorizes another user's media. A native
idempotency key protects repeat charging; the browser sees task ID and cost,
not the hidden recipe. This does not copy TG credits, create a second wallet,
or modify payments.

Only simple image-to-video recipes with one output and no fixed private assets
qualify. Any stored fixed trend_reference_assets rows, reference_contract,
video/audio assets, Genjutsu and Seedance editing recipes fail closed. Full
video/audio reference recipes and author-approved feed remixes still require
separate actor/media adapters. `VK_MINIAPP_VIDEO_WRITES_ENABLED` remains
OFF by default, on both BFF and native worker. A public repeat affordance is
only preliminary; native catalog validation and quote are authoritative.
No expanded full `VK_FULL_APP_OPERATIONS` readiness is claimed.
