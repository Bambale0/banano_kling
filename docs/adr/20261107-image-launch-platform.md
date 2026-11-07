# Image launch platform and result destination

Status: implemented on the task branch; exact-head CI/deployment not yet claimed.
Baseline after rebase: `tanyapi@b9834c795707dc3037340ea553f41c1ea50f0f9b`.

## Problem and boundary

A verified VK session currently resolves a linked legacy Telegram owner for
balance/task ownership. That ownership identifier must not implicitly authorize
sending VK-origin generation messages into the Telegram chat.

This slice addresses ordinary images, feed image remix and image trends on the
existing signed administrator surface. It does not create native VK-only users,
enable ordinary visitors, move balances or implement VK community messaging.
Those remain tracked in the independent VK journey map.

## Contract

- The server supplies `origin_platform` from its verified launch context; a
  client body field cannot choose it. Image task metadata retains the origin
  across local/provider ID replacement. The provider payload is unchanged.
- Existing tasks without an origin and Telegram/bot launches retain Telegram
  behavior. Historical origins are not inferred from linked identities.
- VK-origin images do not send queued, direct-result or failure notifications
  through Telegram. The installed generation-start UX normalizer follows the
  same contract, rather than relying only on the original notifier function.
- Callback/poller results remain completed and owner-readable through the Mini
  App. Asynchronous completion uses `available_in_app`, a terminal availability
  marker, not a VK-message delivery receipt. Direct results remain available in
  their successful API response and normal history.
- Completing in the app preserves normal acceptance/repeat bookkeeping. Failure
  uses the existing atomic failure/refund operation. Callback replay cannot
  double refund; completed/refunded tasks are not regenerated. Terminal result
  URLs remain stable on repeated completion.
- A Telegram delivery lease cannot be claimed for persisted VK origin. No
  Telegram chat ID or VK messaging capability is fabricated. Native VK message
  delivery will need a verified destination and the corresponding permission.

## Verification

Public seams: image HTTP handler with an opposing client platform, installed
runtime notifier, real task/provider-ID persistence, direct/queued responses,
polled result, authenticated KIE callback, legacy image callbacks, task delivery
lease and result/replay/refund transactions. All media/provider/bot boundaries
are synthetic; no live message, charge or paid generation is used.
Coverage includes empty-result and watchdog notifications and a controlled
interleaving of two completion calls. Completion hooks run without another
unconditional write of an earlier result URL.

Local focused tests pass on SQLite. Existing native PostgreSQL durability tests
also cover VK completion, concurrent refund/completion and terminal replay; their
isolated CI execution must be green before release. No database migration,
payment/provider setting, new credential or mutable business configuration.

## Rollout and rollback

Use the protected `tanyapi` PR and exact-SHA CI/autodeploy. Verify both frontend
revisions, backend health, authentication boundaries and focused completion
smoke. Do not replay a real customer task for testing.

Retain the origin delivery guard when rolling back other changes while VK tasks
are in flight. Older workers do not understand this metadata; do not strip it or
resume cross-platform delivery by guessing the original channel. New VK launches
can be stopped with the existing preview policy while pending jobs drain.
