# WAN mobile upload transport candidate

Baseline: `tanyapi` `b0c77f579fbf7824846c98f59e5bbe2d2e88b8f2`

## User-visible outcome

WAN repeat Image1 uploads can use bounded JSON chunks in mobile WebViews,
while retaining the existing owned-upload session, quota, validation and storage.

## Evidence and uncertainty

- The screenshot shows a JPEG replacement failing before generation with
  `Некорректные данные запроса.`
- Production ingress at 2026-10-13 10:04:51–53 UTC shows init 200, chunk 400,
  cancel 200 from an iPhone iOS 18.7 client. The same sequence recurred after the
  baseline deployment at 10:35:51 and 10:37:06 UTC. No upload-complete request
  follows those failed chunks.
- The deployed WAN HTTP boundary maps unhandled ValueError/UnicodeError to
  precisely that generic message, without logging their source.
- The existing general uploader already selects JSON for affected mobile
  clients. WAN still only uses multipart. Its previous WebKit regression test
  documents a missing-starting-boundary failure.
- A local actual-route test with malformed WebKit multipart reproduces the
  exact screenshot message on the baseline. A valid multipart request succeeds.
- This proves the missing alternate transport and matching failure mode; it
  does not prove which ValueError caused the original production request.
  The production request body was not captured and must not be logged.

## Change

1. Authenticate through the existing signed header before body parsing.
2. Accept strict, bounded JSON/base64 at the existing WAN chunk endpoint.
   Limit encoded body and decoded bytes to one existing 7 MiB chunk plus a
   small metadata allowance. Reject duplicate/unknown keys and bad types.
3. Pass both transports to the same save_chunk(actor, upload_id, index, total,
   chunk) transaction. No changes to ownership, quota, hash/idempotency,
   finalization, URL permissions, billing, provider calls or model settings.
4. Prefer JSON chunks on iOS, desktop-mode iPad and Android. Desktop multipart
   may retry exactly once as JSON only for an explicit multipart-parser error;
   later chunks use that transport. No auth/storage error transport retries.
5. Keep FileReader bounded to one chunk, abortable and within the existing
   per-request timeout. Cancellation retains existing session cleanup.
6. Log only multipart parser exception class, never request contents or auth.

## Verification

- Baseline: JSON transport tests fail; malformed WebKit multipart returns the
  screenshot's exact 400 validation message.
- Candidate: 12 actual-route isolated HTTP tests pass, including real multipart,
  exact JSON bytes/actor, auth ordering, 7 MiB maximum, decoded over-limit,
  Content-Length and streaming body limits, bad base64/types, duplicate keys
  and the unchanged storage 404 contract.
- Candidate: 41 frontend tests across new transport, existing WAN API and
  cancellation suites pass. Covers iPhone/iPad/iPod/Android, desktop fallback,
  same session/index, cancellation during reading and read timeout.
- Targeted TypeScript check passes with incremental cache disabled. Python
  source compiles without importing the application.
- Local and production aiohttp versions both verified as 3.14.4.
- Production ingress body limit is 110 MiB and application limit 220 MiB,
  above the approximately 9.8 MB encoded maximum request.

Commands:

    python tests/isolated/test_wan3_chunk_transport.py
    cd frontend/miniapp-v0
    node_modules/.bin/jest --config jest.config.ts --runInBand lib/__tests__/wan3-chunk-transport.test.ts lib/__tests__/wan3-prime-api.test.ts lib/__tests__/wan3-prime-upload-cancel.test.ts
    node_modules/.bin/tsc --noEmit --pretty false --incremental false

## Release gates still required

Apply only the five files in the candidate patch to a dedicated branch from
current tanyapi, then run the repository's maintained CI and build gates.
The isolated candidate's api.ts/types.ts test scaffolds and copied build
configuration are not deliverable changes. Full application/DB imports were
not run in this diagnosis workspace.

After authorization, publish through the normal PR/release flow. Verify exact
deployed SHA and a real mobile WAN upload through init/chunk/complete, without
starting a paid generation. Until that smoke succeeds, do not claim the
original user's upload is fixed. Roll back the release if ownership, storage,
or cancellation regressions occur.
