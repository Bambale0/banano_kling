# Public two-sided Telegram/VK account linking

Status: public signed-account rollout authorized on 2026-11-08.
Plan lineage: #408, E1 #409, wallet E2 #410, link E4 #411, initial PR #415.

## Consent and authentication

An invitation is a 256-bit random, URL-safe token; only its SHA-256 digest is
stored. Its configurable lifetime is `shared_accounts.preview.link_ttl_seconds`
(default 600, accepted 60–86400). A policy revision invalidates pending links.
URLs use `link_<43-character token>` in Telegram startapp or the VK fragment.
The token is neither a login credential nor permission to merge accounts.

GET never accepts, confirms or merges an invitation. The recipient first logs
in using the signed launch of the other platform, then explicitly accepts the
token with POST. A different recipient cannot replace the bound identity.
Both authenticated identities must subsequently confirm, using the current
invitation revision. Both parties see the server-verified platform and external
ID of the sender and recipient before confirmation. The source can cancel.
Expired or cancelled invitations cannot be committed; the UI can start again.

### Linked accounts card

Every user's own profile and the mandatory VK linking gate share a compact
«Связанные аккаунты» card. Telegram and VKontakte each show their persisted connection
status and a check mark or «Привязать» action. The authenticated `/me` preview
metadata includes `linked_platforms`, read from `shared_account_identities`;
the existing `telegram_linked` legacy application-access check is unchanged.
The invitation form opens only after a linking action or an incoming link.
Opening the form does not create, accept or confirm an invitation. A failed or
15-second timed-out status read offers retry rather than inventing an unlinked
identity. Both check marks appear only after server-proven membership or a
committed link receipt. Administrator settings remain available in a separate
disclosure below the card. All existing access, financial and rollout boundaries
still apply.

Settings loading and authentication failure never remove the card from the
administrator profile. Linking obtains destinations from its own authenticated
profile metadata; settings have bounded loading and explicit retry. Expired
Telegram login offers a configured Mini App relaunch link. The ordinary Mini
App's longer login window does not relax the configurable, shorter linking
freshness policy. Policy revisions refresh metadata without remounting an
in-progress invitation or discarding its consent state. Authentication rejection
logs include only the request path and constant failure reason, never credentials.

Every valid signed Telegram or VK identity may use session, own-profile and link
routes. The VK entry verifies a VK launch directly and does not mount the shared
studio until an existing Telegram account is linked. Settings management remains
restricted to Telegram administrators; wallet and commercial preview tools also
require source-scoped administrator authorization. All account routes are exact
`/mini-app/api/account-preview/...` routes.

Session and invitation credentials stay out of logs, storage and analytics.
Session tokens exist only for one API operation and are revoked in finally.
Logout can revoke its own opaque token even after a merge or preview shutdown.
All responses set no-store and no-referrer. A committed receipt can be replayed
by the same verified participant without repeating the monetary transfer.

## Atomic merge and late operations

The link row is locked before confirmation. Account rows are then locked in
sorted order. The canonical account is deterministic; an account cannot acquire
two different identities on one platform. The second account remains as an
alias (`merged_into`) rather than being deleted. Identities and legacy links
move to the canonical account; historical ledger entries remain immutable.

Available funds and active reserves transfer atomically with paired immutable
transfer_out/transfer_in entries, separately for sandbox/live. Reservation
ownership moves in the same transaction. Integer capacity checks roll back the
entire merge if the combined funds cannot fit. Client operation keys cannot use
the reserved `link:` or `opening:` namespaces.

Wallet operations follow aliases and lock the active canonical account. If a
concurrent merge wins while a wallet operation waits, the wallet transaction
restarts lock acquisition instead of reversing account lock order. Old provider
callbacks can replay their original operation keys; ownership is resolved through
aliases while the immutable request hash binds kind, amount and reference.
Refund totals include historical pre-merge refunds, so a merge cannot reopen a
previously refunded capture. Wallet history includes all merged account aliases.

## Validation and release

Tests run on isolated SQLite and disposable localhost PostgreSQL, including
reverse VK→TG linking, both confirmations, third-party rejection, wrong tokens,
expiry, cancellation, old callbacks, reservations, partial refunds, internal key
collisions, conflicting identities, and concurrent merge with wallet mutations.
Browser checks cover administrator/ordinary Telegram users and VK users.

Public linking does not create a second financial authority. Linked VK requests
reuse the existing Telegram legacy owner for live balance, history, referrals,
generation tasks and result delivery; VK-only financial import remains out of
scope. Production rollout is authorized after protected CI, exact-SHA deployment,
rotation of the previously exposed VK Mini App HMAC secret, policy-revision
invalidation and real signed VK acceptance.


## Public two-sided linking — 08.11.2026

The owner authorized this flow for every user with a valid Telegram or VK launch
signature. The cryptographic token, explicit recipient acceptance, confirmation
by both authenticated identities, expiry, policy revision, conflict checks and
atomic merge rules above are unchanged. Administrator membership is no longer a
precondition for session/profile/link operations.

The card is shown in every user's own profile. An unlinked VK identity sees the
mandatory link gate and cannot enter the studio until an existing Telegram
account completes both-sided consent. After commit, VK requests resolve the
linked legacy Telegram user for live balance, history, referrals, generation
ownership and result delivery. Administrative settings, sandbox wallet and
commercial editors remain administrator-only. No VK-only financial authority,
automatic ID matching or one-sided account merge is introduced.
