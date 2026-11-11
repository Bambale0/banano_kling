# VK / Telegram — one Mini App shell

## Requirement

Both launchers must render the exact same `MiniAppShell` and `TabContent`
with seven VK tabs (Motion remains Telegram-only). No mandatory platform linking, no second VK-specific UI
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
   bootstrap, photo, video, trends, feed, services, profile, payments,
   referrals and tasks. Motion is explicitly not required in VK.

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

## Same-route VK API gateway

The shared Mini App endpoint prefix remains /mini-app/api on both clients.
When VK_FULL_APP_PARITY_ENABLED is absent or OFF, the middleware is a strict
pass-through and does not even read legacy Telegram JSON bodies. With the
flag ON, a verified vk_session token is resolved into PlatformActor, and
the request is passed to the single registered native VK adapter's
handle(request, actor=actor) coroutine. There is no synthetic Telegram ID.

The gateway requires the same full readiness manifest as the UI profile
contract. Any incomplete adapter is rejected for VK-only identities rather
than forwarding a VK owner to legacy Telegram billing. Legacy linked VK
sessions retain their old handler until the full adapter is registered;
Telegram callers are always passed through untouched.

Identity or role override fields are rejected at the gateway for signed
VK JSON requests, including when the signed launch token is supplied in a
header. Media multipart requests must carry signed init data in the
X-Telegram-Init-Data header once the native adapter is enabled: the gateway
does not consume upload streams in order to discover a form field. The
native adapter must independently validate role, reference ownership,
provider/model constraints, cost and idempotency.

**Current status:** no complete VK adapter has been registered in
production, and the flag remains OFF. This gateway alone does not implement
photo/video/social/commerce parity or switch VK users to the
common shell; it creates the safe routing boundary needed to do so.

## Release gates

- All seven VK tabs route to the verified VK actor under one UI and
  use the real native VK wallet and task ownership. No fake prices/zero
  balances or synthetic Telegram users.
- Video, reference upload, private/public trends, feed interactions,
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


## Unified native VK task-history projection (2026-11-11)

A verified VK actor's existing HMAC native-state call now includes
`recent_tasks` in the **same task-card DTO** as the Telegram Mini App.
The original `tasks` and `balance` fields are preserved unchanged.
VK task IDs are explicitly namespaced as `vk:<numeric_id>`, never passed
to legacy Telegram task endpoints by numeric ID. This is a read-only
projection, not a financial migration or new history store.

The projection covers real native VK task types observed in the production
database: photo, video, reference-video; Historical Motion Control tasks are mapped to video in the read-only
history if present; new Motion generation is not part of the VK release. Pending/submitting/processing map to the shared pending state,
completed/failed to the same shared terminal states. Native cost and media
URLs are preserved. Missing prompt/aspect values are left empty, **not
invented**. Unsupported/future task rows are omitted only from the
compatibility projection, never from the authoritative native `tasks`
array; a single such row cannot hide a user's balance or old native history.
All mutation and task detail/repeat adapters remain unavailable until
explicitly ported.

**Verification:** 73 targeted shared-account/link tests passed; 75 optional
PostgreSQL variants skipped locally, 14 frontend shell tests passed, TypeScript,
ESLint, targeted Ruff and Python compilation passed. VK static build passed.
Full GitHub PostgreSQL and end-to-end validations are independent release gates.

**Not yet shipped:** the shared seven-tab VK-only UI still cannot safely use
the TG legacy API endpoints. `VK_FULL_APP_PARITY_ENABLED` is not enabled.


## Native VK task history integration (2026-11-11, NOT production)

Native `tanyavk` has an HMAC-only, read-only API at
`POST /internal/v1/miniapp/users/{vk_user_id}/tasks/history` and
`POST /internal/v1/miniapp/users/{vk_user_id}/tasks/detail`.
The exact method/path/JSON body are signed by `INTERNAL_API_SECRET`
and scoped to the verified native VK actor; browser claims are ignored.
History pages contain 8 tasks plus a namespaced keyset continuation cursor
`vk:<id>`. Unlike the old summary, history is not limited to 40 recent
tasks. Stale/deleted/foreign cursors reset to the owner's latest page.
Details return an owned task only; raw prompts and reference recipes
are deliberately withheld because the native VK DB cannot yet determine
which copied trend recipes are protected.

`VkNativeTaskService` converts this signed data to the EXACT existing
`/mini-app/api/task-history` and `/mini-app/api/task-detail`
response contract. `VkNativeTasksAdapter` advertises only `tasks`
readiness. `VK_NATIVE_TASKS_ENABLED` is a separate OFF-by-default
switch for these two standard paths. No wallet/credit/provider actions
are performed and the complete `VK_FULL_APP_PARITY_ENABLED` readiness
stays false, since no full native studio has been implemented yet.

The native service must be released before enabling
`VK_NATIVE_TASKS_ENABLED` in the common backend. Tests include
HMAC, actor-collision, no synthetic Telegram user, foreign task 404,
cursor reset, blocked owner 403, replay and exact immutable account
balance. Local cross-repository test used a temporary SQLite DB,
not a production user or provider.

**Next gates to an actually identical VK and TG app:** real native
bootstrap (including truthful supported model/price metadata),
fully shared photo/video/service execution and delivery (Motion is Telegram-only), media
reference ownership, feed/trend publishing/repeating, checkout and
referrals with audited VK wallet, and a signed VK WebView acceptance
on the same code SHA. Never expose a supposedly ready common shell
before these domains are implemented.
