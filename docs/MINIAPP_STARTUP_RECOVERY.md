# Mini App startup recovery (2026-10-20)

## Incident and scope

The October 20 09:20 MSK screenshot showed the server-rendered loader, not proof of a Telegram-auth wait. At the matching time a client with the same Android device/Telegram user-agent fetched HTML and assets but never called bootstrap. A page chunk returned zero body bytes; another transferred only 49,152 bytes before disconnect. Other users completed bootstrap in under a second. Transport interruption is observed; the operator/carrier/VPN cause is not established.

Two indefinite-wait paths were reproduced: a stalled initial entry chunk before React, and a bootstrap response (including its JSON body) without a deadline. A single failed entry download already had a Next retry; the fix deliberately does not compete with it.

## Behavior

The existing early Telegram-ready script now includes a dependency-free 12-second startup watchdog. Native recovery works without React, Telegram SDK, or downloaded CSS, and survives Next's fatal chunk-error document replacement. Its click listener is registered early in capture phase: React hydration event replay must not swallow it. Explicit reload preserves the launch hash, query/start parameters, and session data; a cache-busting query parameter is the only addition. There is no automatic page-reload loop.

The Mini App shell disarms this watchdog on mount, so it never interrupts an active form, draft, task, or payment. The initial loader no longer pretends to know that Telegram credentials are the blocking stage.

Bootstrap has a 15-second AbortController deadline covering headers and body; caller cancellation propagates and timers/listeners are cleaned up. A network failure with existing Telegram launch data presents an explicit connection retry, not a fresh Telegram login. No generation/payment request is retried by this mechanism.

Startup telemetry uses the existing client-log endpoint, event/phase and same-origin resource pathname only. No user identifiers, initData, URL query/hash or auth values are transmitted.

## Verification

Regression tests: `lib/__tests__/bootstrap-timeout.test.ts`, `lib/__tests__/startup-recovery.test.ts`. Browser test: `node e2e/startup-recovery.mjs`, using a static production export and synthetic/intercepted auth/API only. It covers normal startup, transient errors, persistent missing chunks, stalled delivery plus native reload preserving launch data, and a stalled bootstrap plus explicit retry. Run the standard repeat/navigation suite as well. Test results and exact release SHA are recorded in the PR/deploy, not inferred from HTTP 200.

## Operational blocker

The preceding release #342 failed before switching containers because free disk space was below the existing 10 GiB deployment floor. Production remained on #341 despite the newer source checkout. On October 20, unused Docker build cache older than 24 hours was pruned (20.19 GB reclaimed); media, databases, volumes, retained backup files and rollback images were not deleted. The deployment floor remains unchanged. Always compare both the running container revision and `/mini-app/revision.txt` to the merged release SHA.
