# VK / Telegram — one Mini App shell

## Requirement

Both launchers must render the exact same `MiniAppShell` and `TabContent`
with eight full tabs. No mandatory platform linking, no second VK-specific UI
as an end state. Only authentication and platform-dependent domain adapters
may differ. An existing Telegram account must never be fabricated from a VK
ID.

## Root cause

`AccountPlatformEntry` gated the common app solely on
`preview.telegram_linked`; VK-only users were routed to
`VkStandaloneDiscovery`. Separately, most endpoints in
`bot/miniapp.py` still resolve VK sessions through
`_get_vk_session_user_context` by requiring a linked Telegram identity.
Simply removing the UI gate makes the full app call APIs it cannot service
and risks credit misattribution, missing history and failed delivery.

## New transition contract

The backend returns `preview.full_app_ready` on the authenticated
`/account-preview/me` response. This boolean is **server derived**, never
provided by the browser. VK-only may enter the existing shared shell when:

1. `VK_FULL_APP_PARITY_ENABLED=1` on the backend;
2. a trusted, process-local `vk_full_app_adapter` is registered;
3. the adapter's readiness manifest includes all required operations:
   bootstrap, photo, video, motion, trends, feed, services, profile, payments,
   referrals and tasks.

The existing linked-account legacy shell is preserved until all native VK
adapters are implemented. Client handling is backward compatible for older
servers: when `full_app_ready` is absent, linked VK users keep their current
common shell. An explicit server `false` takes priority over a link.

**Current production:** no such complete native adapter exists, so
`full_app_ready` remains false for VK-only accounts even if an operator
sets the flag. DO NOT enable the flag or delete the fallback until each
operation has owner-scoped, audited real implementation. This branch is
**a contract foundation, not full cross-platform parity**.

## Verified platform actor foundation

bot.shared_accounts.actor.resolve_platform_actor(session_token) verifies an
unexpired revocable policy-scoped session. It returns immutable PlatformActor
containing the platform, external ID, shared account ID, linked platform list,
and optional linked Telegram ID without creating a legacy users row.

VK and Telegram actors with identical numeric external IDs remain different
owners: vk:<external_id> versus telegram:<external_id>. wallet_platform is
the verified launch platform, not the presence of an optional account link.
This owner key is not a database migration mechanism. User-supplied IDs or
roles must never replace server-verified actor identity.

Profile, native VK state and photo-write actor guards now use the same resolver.
Regression tests cover identity collision, revoked session, wrong platform,
disabled policy and absence of synthetic Telegram users after VK sign-in.

This is a foundation, not 1:1 parity: legacy /mini-app/api endpoints still
require Telegram IDs, and the VK-only full-shell readiness remains false until
all real adapters are implemented and validated.

## Release gates

- All eight tab operations route to the verified VK actor under one UI and
  use the real native VK wallet and task ownership. No fake prices/zero
  balances or synthetic Telegram users.
- Video, motion, reference upload, private/public trends, feed interactions,
  music, voice, assistants, saved files, referrals, payment checkout,
  webhooks, refunds, balance, history, status polling and notifications.
- No financial double-charge/credit after linking, concurrency/retry/
  webhook replay protection, authoritative provider receipt reconciliation.
- Exact committed SHA in VK and TG builds, all safe integration/browser E2E
  tests, and live signed VK WebView acceptance including actual payment and
  generation/delivery.

Rollback: clear `VK_FULL_APP_PARITY_ENABLED` and keep the native
VK backend's historical wallet untouched. Never migrate a wallet as a
side-effect of sign-in or UI navigation.


## Verified platform actor foundation (2026-11-11)

The signed session now resolves to immutable `PlatformActor`
(`platform`, `external_id`, `shared_account_id`,
`linked_platforms`, `linked_telegram_id`). This is the one trustworthy
owner boundary for future native adapters.

- `vk:2001` and `telegram:2001` are different external identities even
  if their numeric IDs are identical. Their owner keys and initial shared
  account UUIDs do not collide.
- A signed VK-only session creates no `users` row and never fabricates a
  Telegram ID. Revocation and wrong-platform access deny as before.
- After optional link, the current launch platform remains authoritative
  for the wallet and notification adapter. Identity linking can succeed
  without a legacy `users` row; `linked_telegram_id` then remains None.
  This is not a reason to force users through Telegram onboarding.
- `profile` and `vk_native_state` now share the same session resolver.
  The original policy-disabled HTTP 404 response remains unchanged.
- Native photo writes for **linked** accounts retain the existing deny
  path until actual wallet-owner routing is implemented; avoiding silent
  cross-wallet charges is more important than opening a premature button.
- Server-side `full_app_ready` still requires a real registered adapter for
  all domains and is OFF by default. This is not yet a 1:1 release.

Test evidence: 52 shared-account tests passed and 52 PostgreSQL cases
were skipped locally; Ruff and compileall passed. The complete
PostgreSQL matrix and common shell end-to-end tests remain release gates.
