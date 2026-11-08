# Verified VK image-result delivery

Baseline tanyapi@4f6387d65135b04a17c2d448ebeef793c5b08482. The owner reports
that a VK-launched result is now in the Mini App but absent in the VK chat.
Read-only production evidence: the latest administrative VK image completed
with one reference and available_in_app; no VK recipient or chat attempt exists.

The common backend has no group token. The native VK process has an existing
sender, but its notification method mutates native task/refund/blocking state,
its internal API is read-only, and its photo download is unbounded. Do not call
that entire workflow, reuse the read-only HMAC for writes, or invent native tasks.

Use a transport-only VK adapter beside the common task store and one durable
outbox. This avoids a second cross-service queue/receipt protocol and networking
exposure while keeping all Mini App task delivery state together. It requires
explicitly configuring the existing community credential in this deployment;
never copy it into source, logs, frontend or API responses. Native VK generation
and financial tables remain untouched. Production activation still requires the audited delivery switch, protected
release gates and exact deployed-revision verification.

Persist the verified VK external ID and shared account ID at launch. Client JSON
cannot select a recipient. Completion/reconciliation creates one outbox row per
stable internal task ID after checking current ownership. Keep app availability
separate from actual VK receipts. Old tasks without recipient snapshots are not
automatically replayed; explicit authenticated owner-requested delivery can bind
a fresh acceptance with an audit record.

The existing audited typed preview policy manages community ID, delivery enable,
message template and bounded retry policy. Default delivery is disabled; existing
the signed public-account gate and server ownership ceilings stay in force. The group
token is a secret configuration value. Accepted jobs snapshot recipient, community,
result, message and random_id; later edits never rewrite accepted messages.
The credential also has server-only bound community metadata. Enabling routing
to a different community is rejected. A launch snapshots delivery intent; turning
the feature on later does not silently send results accepted without that intent.

Prepare a photo with bounded download/decoding/upload before the message send.
Reuse the public-at-connect resolver and redirect validation. A failure before
send may choose a link-only payload. Persist the exact attachment/text before
sending. CAS leases prevent concurrent sends; an expired preparing worker cannot
send. Persist sending before the network request. A lost send acknowledgement or
process crash in sending becomes uncertain, never an automatic alternate send.
Explicit rate-limit rejections alone permit bounded retry of the identical payload.
Stable random_id is an extra deduplication measure, not a promise of unlimited
exactly-once delivery. Permission denial does not block the native user, refund
a successfully generated image or route it to Telegram.

Primary contracts: VKCOM/vk-api-schema 5.199, messages.send (group token,
random_id), messages.isMessagesFromGroupAllowed, photos.getMessagesUploadServer
and photos.saveMessagesPhoto. Actual external messages and paid generation are
excluded from automated tests. Validate signed launch→snapshot, ownership,
SQLite/PostgreSQL outbox/reconciliation/CAS, fake VK API media/permission/flood/
timeout contracts, client status/retry and unchanged provider/refund behavior.

Setup, HTTP contract and rollback: [VK result delivery](../integrations/vk-result-delivery.md).
