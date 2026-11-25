# Telegram original downloads

New image/video result buttons, result caption links, and Wan oversize fallbacks
use `GET /api/media-download/<path-relative-to-uploads>` for managed originals.
The same route accepts `HEAD`. Both `neuromixbot.com` and
`tanyapi.chillcreative.ru` already proxy `/api/` to the backend. No DNS, Nginx,
bucket policy, database migration, or new environment variable is required.

## Storage and access contract

- S3 GET: the route returns a `307` redirect to a newly signed `get_object`
  request. `ResponseContentDisposition` requests `attachment`, with
  a safe ASCII `filename` and UTF-8 `filename*` retaining the stored extension.
  `ResponseCacheControl` and the redirect use `private, no-store`.
- S3 HEAD: Selectel ignores response overrides on a signed HEAD (verified on
  the real bucket). The endpoint reads metadata only through SDK `head_object`
  and returns 200 with attachment, original Content-Type/Content-Length and
  private/no-store headers. No object contents are read; missing objects yield
  404 and storage failures 503.
- The existing `MEDIA_S3_PRESIGN_TTL_SECONDS` applies (60–900 seconds). A saved
  bot link obtains a fresh signature when clicked. It does not embed a signature
  that expires while the message waits in the chat. Existing object deletion
  and retention behavior still applies; absent originals cannot be recovered by
  this route.
- S3 transfers bytes directly to the client, including Range requests. The
  application does no media-body GET, materialization, transcoding or upload.
  Local mode serves the existing file with aiohttp `FileResponse`, bounded
  transfer and existing HEAD/Range support, without a second file copy.
- The opaque public upload path carries the same access as existing `/uploads/`
  links. This endpoint does not add an owner login to existing public media or
  change S3 ACLs/policies. It is not an arbitrary URL proxy; callers can only
  request a validated key below the configured uploads prefix/root. Local
  traversal and symlink escapes return 404.
- Private Genjutsu media remains on `/genjutsu/media/...`, with its existing
  signature, expiry and repository checks; only its already-supported
  `download=1` presentation flag is added when such a URL is used.
- URLs on external providers and URLs with unknown authorization/version query
  parameters are preserved. They are not fetched or resigned. If a legacy
  result never reached managed storage, its download behavior still depends on
  its provider. Existing messages are not rewritten; newly rendered result
  keyboards/captions use the new contract.
- Preview URLs, persisted `result_url`, Telegram media input URLs, Mini App
  playback, payment and generation contracts remain unchanged.

## Telegram clients

An attachment response asks the client to download the original. Telegram on
iOS, Android, desktop or the browser may open a confirmation, system sheet or
external browser according to client/OS settings. This does not silently save
to the photo library or bypass user confirmation. Real client acceptance is a
separate smoke step; HTTP tests cannot prove it. No automatic paid generation
or unsolicited chat message is needed to validate HTTP behavior.

## Verification and release

`tests/test_original_download.py` exercises result keyboards, attachment headers,
byte integrity, local HEAD/Range, S3 signing with the real SDK and configured
TTL, path and origin protections, and safe UTF-8 filenames.
`tests/test_wan3_prime_delivery_links.py` retains `TelegramEntityTooLarge`,
terminal link receipts and uncertain-response behavior. Existing storage,
migration, delivery recovery and origin-routing tests cover adjacent contracts.

Before release, a streamed read-only probe against the actual Selectel bucket
returned `206` with `Content-Disposition: attachment` and
`Cache-Control: private, no-store` for the override. Ordinary `/uploads/`
responses, including `?download=1`, lacked attachment headers on both domains.
Do not infer feature deployment from this provider probe.

Release through protected PR to `tanyapi`, required CI and exact-SHA autodeploy.
After deploy verify the running image revision, health, both domains' redirect
headers, final S3 GET/HEAD/Range headers and original checksum, ordinary preview
behavior, and delivery/error logs. Never print signed URLs or access keys in
reports. Roll back through a revert PR; stored media/URLs need no rollback.
