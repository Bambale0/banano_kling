# Website-studio logout missing after linked Telegram sign-in

Target branch: tanyapi. No financial balance migration.

## Evidence and root cause

Production frontend on 41afa6d1 uses native ProfileTab for a
website-linked Telegram account after the /web-auth/studio exchange.
The backend mints an authenticated, revocable webstudio_* query_id
associated with the verified website session. ProfileTab's logout guard
uses isBrowserAccountSession(), which recognized only legacy browser_*
query IDs. As a result, linked website users did not see logout.

## Safe fix

isBrowserAccountSession() now reuses established isBrowserPaymentSession()
classification, which explicitly accepts browser_* and valid
webstudio_[A-Za-z0-9_-]{16,40} signatures while rejecting VK and native
Telegram entry.

The sign-out path remains unchanged: server revokes the HttpOnly web
session before local credential cleanup; stale caches and auth-bearing
URL search/hash are cleared before navigation to /login. Failed
revocation keeps the session for an explicit retry. This change never
reassigns funds or introduces a native Telegram logout.

## TDD and release gates

- RED: 2 tests failed: missing linked webstudio logout and zero server
  revocations for linked webstudio logout.
- GREEN: 49/49 focused unit/integration tests, including platform
  routing, payment surface guard, native Telegram, linked browser,
  read-only browser workspace, and server revoke/cleanup.
- TypeScript noEmit, changed-file ESLint, git diff --check passed.
- GitHub protected CI, production deploy exact SHA, browser linked
  website smoke and native Telegram no-logout are still required.
