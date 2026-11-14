# VK #451 — actor-neutral shared Mini App bootstrap slice

Base: tanyapi@aa60ac1b6015c3ec673482f30bc698484a9371c9
Branch: feat/vk451-independent-shared-bootstrap-20261114

## Goal

Make the already implemented VkNativeAppAdapter.bootstrap reachable through
the SAME /mini-app/api/bootstrap endpoint as Telegram, using a signed VK actor
and the authoritative native VK wallet/models/tasks, without a fabricated
Telegram user, cloned wallet or separately priced catalog. Do not advertise
full 10-domain parity or mount the common shell prematurely.

## Preconditions / architecture

- AGENTS.md, VK parity issue #451, gateway/native bootstrap/actor/backend,
  linked legacy studio and API routing were inspected before changes.
- VkNativeAppAdapter handles exactly bootstrap + tasks and explicitly advertises
  ready_operations={bootstrap,tasks}; full_vk_adapter requires all 10 domains.
- Bot native bridge signs upstream HMAC, validates response and uses the
  *later* native commerce balance as the authoritative snapshot; no
  transactional claim that independently read state/commerce prices match.
- Previously VK full gateway could route bootstrap only with ALL domains ready.
  A signed VK bootstrap when full parity was off could silently reach the
  legacy handler; downstream Telegram auth normally denied it, but an
  explicitly fail-closed VK gateway is the correct protocol boundary.

## Implementation

1. RED: 8/9 initial focused tests failed because independent VK bootstrap
   was forwarded into the legacy Telegram route.
2. Add VK_NATIVE_BOOTSTRAP_ENABLED=1 as a separate, default-OFF gate for the
   ONE native /mini-app/api/bootstrap route. Bootstrap is dispatched to the
   real VkNativeAppAdapter only if it still explicitly advertises the
   incomplete ready_operations={bootstrap,tasks}.
3. When native domain routing is OFF, reject vk_session bootstrap/history
   instead of passing the credential to the legacy Telegram handler. When a
   native partial domain is enabled, reject signed VK requests to other
   unsupported shared API paths instead of misrouting to TG-owned money.
4. Preserve normal Telegram requests and all existing 10-operation
   full_vk_adapter readiness checks. A linked VK actor still reads its VK
   wallet and links cannot grant legacy studio when native bootstrap is on.
5. Preserve short bootstrap body and reject oversized requests with HTTP 413
   even while native bootstrap is disabled. No raw tokens in URLs.
6. Update old gateway regression to expect the strengthened VK fail-closed
   contract instead of the older legacy fallback response.
7. Keep public client common shell gate OFF until all domains are genuinely
   available. This is backend plumbing, not a complete VK 1:1 UI rollout.

## Verification

- 12 new independent bootstrap integration/security tests, including
  signed identity, linked VK, no synthetic Telegram ID, actor body spoofing,
  invalid/revoked session, unsupported domain 503, huge payload 413, upstream
  failure redaction and Telegram route continuity.
- 28/28 isolated native bootstrap/readiness tests passed, including preexisting
  bootstrap/service tests; Ruff 0.17.5 selected changed files clean; Python
  py_compile and git diff --check passed.
- Existing test_shared_accounts gateway regression tested separately with
  isolated Python dependencies where available; full protected CI mandatory.
- No real provider charge, payment, price mutation, VK messages or production
  DB change. Never turn on VK_FULL_APP_PARITY_ENABLED with this partial adapter.

## Deployment and rollback

PR to protected tanyapi, no forced merge and no manual production code patch.
VK_NATIVE_BOOTSTRAP_ENABLED remains default OFF; rollout needs signed WebView
and native wallet smoke. Disable this one flag to roll back native bootstrap,
with no data migration or financial side effects.
Full #451 remains OPEN for photo/video/service/feed/profile/payments/referrals
and real end-to-end shared TabContent parity, admin, delivery and VK acceptance.
