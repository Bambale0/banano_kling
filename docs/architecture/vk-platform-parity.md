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

## Bootstrap readiness review (2026-11-12)

The incremental native bootstrap adapter rejects blocked/unregistered actors and
malformed upstream state, model and package data before exposing a shared view.
Balances from separate HTTP reads are not an atomic snapshot: a native payment
or debit may legitimately occur between them. Bootstrap displays the later
native commerce balance; it never compares two readings as a readiness gate.
Generation and checkout must still revalidate native funds and prices at write
time. Upstream errors fail closed through the gateway without private details.
This adapter still advertises only bootstrap/tasks, not full parity readiness.
