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
