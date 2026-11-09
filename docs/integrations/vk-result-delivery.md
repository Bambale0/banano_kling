# VK result chat delivery

This capability is available to the verified owner of a VK-origin task when the
audited delivery switch is enabled. It supplements the existing Mini App result
and preserves the Telegram-origin delivery path. It does not create a VK-only
wallet, synthetic Telegram user or native VK task.

## Configuration and activation

The common backend owns the Mini App generation and its delivery outbox. Its
transport uses the existing community credential; it does not call native VK
financial code or extend the native read-only internal API.

Configure these protected environment values on the common backend:

- `VK_GROUP_TOKEN`: the existing VK community token, with messaging/photo access.
- `VK_GROUP_TOKEN_COMMUNITY_ID`: the actual community ID belonging to that
  credential, copied together with it. This binds a credential to its community;
  it is not the mutable routing control.

`compose.backend.yml` already reads the protected `.env`; no secret belongs in
Git, frontend, API responses, logs or an environment dump. Do not rotate or copy
credentials as a side effect of tests. No production credential was configured
by this implementation.

After release authorization, use normal protected `tanyapi` CI/autodeploy and
verify the exact image/frontend SHA and health. In the authenticated Telegram
administrator profile, open shared-account settings and configure:

- `vk_community_id`: community receiving these result conversations;
- `vk_result_delivery_enabled`: opt-in control, initially false;
- `vk_delivery_max_attempts`: 1–10 automatic attempts;
- `vk_delivery_retry_seconds`: 1–3600 seconds between explicit retryable failures;
- `vk_result_message_template`: up to 1024 characters, with a real `{result_url}`
  field and optional `{task_id}`. Escaped placeholders do not satisfy this rule.

Enabling requires the credential bound to the same community. Settings use the
existing typed revision/CAS and audit; they grant no public administrator role.
Delivery fields are stored in `shared_accounts.vk_delivery`, separate from the
legacy-readable `shared_accounts.preview` authentication JSON. Both update in one
revision-checked audited transaction; an old settings client preserves delivery.
Text is snapshotted at delivery acceptance, so later edits preserve accepted copy.
Policy edits revoke stale preview sessions; reopen the app if prompted.

## User flow and truthful states

A photo or video launch captures the verified VK recipient, account and delivery intent
from server authentication/policy. Client JSON cannot choose these values.
Completion makes the result available in the Mini App and idempotently enqueues
one chat delivery. A reconciler repairs a crash before enqueue, scans past invalid
old rows and wraps for later ownership/policy corrections.

Before sending, the server rechecks the public kill switch, verified VK identity,
canonical task ownership and actual `messages.isMessagesFromGroupAllowed`
permission. The result is downloaded with
public-at-connect DNS/redirect checks, byte/time/pixel bounds and a unique temporary
file. A photo is prepared through VK's upload/save protocol. Generated videos
are delivered as the durable public result link; they are never downloaded and
decoded by the photo transport. A photo preparation failure may also select a
link-only payload before any message send; the exact payload and random_id are
persisted. The UI distinguishes photo and link-only receipts.

The result view can open the native VK permission dialog with
`VKWebAppAllowMessagesFromGroup`. Opening this dialog does not claim permission
or send a message. The user confirms in VK and explicitly checks/requests delivery;
the server repeats its permission probe. A plain browser offers the configured
community chat instead. No Telegram redirect is involved.

Old results without recipient/intent snapshots are never automatically replayed.
An explicit owner action in a newly verified VK session can accept their delivery.
Only the owner's existing completed VK-origin photo or video is eligible. POST accepts an
empty object, not a recipient, result URL or platform selector.

The outbox has separate pending/preparing/sending/delivered/permission-required/
failed/uncertain states. Expired preparation can be leased again; a stale worker
cannot send. A crash or lost acknowledgement in sending becomes uncertain and is
not automatically resent. Only explicit VK rejection permits a bounded identical
retry. A later proven positive receipt can upgrade uncertainty under that same
lease. A positive receipt survives disabling future delivery. Stable random_id is
extra deduplication, not a guarantee of unlimited exactly-once delivery.
New outbox IDs use negative signed integers, separate from the native bot's
positive timestamps, with a unique constraint and bounded collision recovery.

Permission denial never blocks the whole native user, refunds a completed result,
or routes the result to Telegram. Delivery never submits a new provider task.

Kling callback variants and the dedicated Kling 4 lifecycle use the saved origin
snapshot before considering Telegram delivery. Successful VK completion runs the
normal idempotent acceptance and feed-author reward hooks; a repeated callback
can retry a missed reward without replacing the first durable result. Provider
failure retains the existing one-time refund semantics and stays in task history,
without notifying the linked Telegram account. Kling 4 marks its lifecycle
availability as `available_in_app`; actual VK chat delivery is still represented
only by the outbox receipt. Reconciliation after a worker restart uses persisted
origin and recipient metadata, not a reconstructed actor's Telegram identity.

Concurrent Kling success callbacks reserve result preparation through a durable
owner/expiry claim before downloading. A busy callback receives a retryable
response without another download. Preparation is bounded by the lease budget;
only the current owner may commit, and expired/stale workers cannot replace the
canonical result or clear a successor's claim. A completed VK result is immutable
from the first saved URL, before chat availability is finalized. A crashed claim
can expire and be retried; this never creates a Telegram delivery lease.

## Private HTTP seam

Under `/mini-app/api/account-preview`:

- `GET /vk-deliveries/{task_id}`: authenticated owner-only status/capability;
- `POST /vk-deliveries/{task_id}` with `{}`: explicit acceptance or safe retry.

Both require an active verified VK owner session in an Authorization header. Tokens in query strings are not accepted. Missing/foreign results share
neutral unavailable recovery text. Responses expose status, community ID and
representation, never the VK credential, attachment access key or recipient ID.

## Verification and rollback

Tests cover signed recipient provenance for photos and videos, completion races,
SQLite/PostgreSQL outbox/reconciliation/leases, permission denial, explicit flood retry, lost/late
acknowledgements, blocked ownership, random-ID collision, old owner acceptance,
secret redaction, actual synthetic PNG upload and browser consent/status/retry.
Fake VK HTTP and intercepted media replace all real sends and paid generation.

Operational logs correlate `vk_delivery_accepted`, `vk_result_delivery`,
`vk_photo_prepare_failed`, and `vk_delivery_explicit_acceptance` by stable task ID.
Errors record phase/type/numeric VK code without remote response bodies or tokens.

To stop delivery, disable it through audited settings. Keep durable results,
outbox rows and receipts. Do not drop the table or restore Telegram routing for
VK-origin tasks. Uncertain sends need receipt/chat review rather than replay.
Disable delivery before downgrading code. The previous release can still parse
the authentication row and safely ignores the separate delivery row.

Primary contracts: [VK messages schema](https://github.com/VKCOM/vk-api-schema/blob/master/messages/methods.json),
[VK photo schema](https://github.com/VKCOM/vk-api-schema/blob/master/photos/methods.json),
[official Bridge transport](https://github.com/VKCOM/vk-bridge/blob/master/packages/core/src/bridge.ts).
