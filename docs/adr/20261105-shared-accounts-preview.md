# Shared accounts: public signed linking and administrator control plane

Status: public signed-account rollout authorized on 2026-11-08. Parent: #408.
Initial baseline: tanyapi@03a9918db303b8ac075115fde8cbccecf6d10aeb.

## Release constraint

The owner authorized production rollout for all users on 2026-11-08. Public
session, own-profile and two-sided link routes require a valid fresh Telegram or
VK launch signature. Settings, sandbox wallet and commercial administration
remain server-authorized administrator surfaces. The existing revisioned
`enabled` flag is the emergency public-access kill switch.

## Existing system and decision

Telegram uses PostgreSQL; VK uses a separate SQLite wallet. Existing Telegram
Mini App APIs and file/task ownership use telegram_id. Account IDs must not be
invented Telegram IDs. Public generation routes remain unchanged in this slice.

Add separate accounts, identities, legacy links, sessions and settings audit
tables. They are created only after an authorized preview settings change or
authorized preview login; registering routes does not run DDL. Creating a
Telegram preview identity may attach an existing legacy user, but never creates
a legacy user or modifies credits. VK identities do not create Telegram users.

Launch authentication is separate from application sessions. Verify Telegram
HMAC or VK sign, application ID, timestamp, positive ID and unique parameters.
Every verified Telegram or VK identity may use public session/profile/link
routes; client flags are ignored. Telegram administrator authority comes from
current server configuration. VK administrator tools additionally require the
source VK ID in the audited allowlist. An identical number across platforms has
no authority. VK application secret is VK_MINI_APP_SECRET in secret
configuration; app ID and admin IDs are non-secret managed policy.

Sessions use random 256-bit bearer credentials, hashes at rest, expiry and
revocation. Credentials are never accepted via URL. Every request re-evaluates the public kill switch; administrator routes also
re-evaluate source-scoped administrator membership. Account state and identity
ownership are checked on session lookup. No session credentials appear in logs.
Sessions are bound to the policy revision: disabling/re-enabling preview or
changing the VK app/allowlist cannot resurrect previously issued credentials.
The admin UI probe retains a token in operation-local memory, verifies the
profile, then revokes the token; no local/session storage is used for this token.

## API, version 1

All routes are below the configured Mini App root + `/api/account-preview`.
They return `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

| Method/path | Authentication | Result |
|---|---|---|
| GET /settings | X-Telegram-Init-Data; current Telegram admin | Typed non-secret policy |
| PUT /settings | Signed Telegram admin; expected_revision | Audited atomic settings change or 409 |
| POST /session | platform + signed launch_data; enabled public policy | Own account, random session token and expiry |
| GET /me | Authorization: Bearer; current enabled public policy | Own account, link status and source identity |
| POST /logout | Authorization: Bearer | Revoke current session |
| POST/GET /links... | Authorization: Bearer; current enabled public policy | Two-sided invitation lifecycle |
| /wallet, /commerce | Authorization: Bearer; current administrator policy | Sandbox/admin tools only |

Disabled feature returns 404 for public account routes. Invalid credentials
return 401; a verified ordinary user receives 403 only from administrator routes;
malformed policy returns 400; revision conflict returns 409;
unexpected storage failure returns a redacted 503. Missing/bad VK secret fails
closed. No wallet value is returned until migration and finance work is done.

Policy is a typed JSON value in existing bot_settings under
`shared_accounts.preview`; no per-process policy cache. Administrator screen in
the own-profile view manages enabled, VK app/admin IDs, session TTL and launch
max age. Revision is server-managed; policy and audit commit together. Default
enabled=false, VK admins empty. The enabled flag authorizes public signed-account
routes only and never grants administrator tools.

## Migration and remaining decisions

Runtime audit found floating Telegram credits despite NUMERIC in the schema file;
VK balance and balance_units differ. Read-only aggregate preflight is available
as scripts/audit_shared_account_migration.py. Never interpret units divergence as
permission to change customer balances. Before wallet cutover: exact scale,
snapshot, legacy writer barrier, idempotent opening entry, reconciliation and
single financial authority. Historical payment transactions are not a complete
wallet ledger. Bananas and partner rubles stay separate.

The implemented two-sided link can merge shared identities and their isolated
shared-account ledger state atomically. Live product balance/history/referral and
generation ownership continue to use the linked legacy Telegram user; no VK-only
financial authority or synthetic Telegram user is created. Account-link conflicts, grandfathered
referrals, bonus provenance and unlink recovery require explicit policy before
cutover. General launch credentials are not reusable account-link consent.

## Verification seams

- HTTP: public kill switch, signature/freshness, source-scoped administrator
  membership, settings CAS/audit failure, concurrent login/link replacement,
  session revoke/expiry and legacy balance preservation on SQLite and isolated
  PostgreSQL.
- UI: ordinary users see only own link state; unlinked VK is gated before
  bootstrap; linked ordinary VK opens the shared studio. Administrator settings
  remain hidden and server-denied for ordinary users.
- Migration diagnostic: synthetic SQLite with known fractional/drift cases,
  unchanged database bytes; output is aggregate only.

Production credentials, paid providers and real chat sends are not used by tests.

Protocol references: [Telegram launch validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app),
[VK launch-signature example](https://github.com/VKCOM/vk-apps-launch-params).
The latter is an archived official example; real VK-client launch and cabinet
configuration remain an acceptance gate for the later VK entrypoint slice.


## Historical admin-only production preview authorization — 06.11.2026 (superseded 08.11.2026)

The owner explicitly authorized merge and production deployment of the current administrator preview. This supersedes the earlier no-deploy hold only for the signed, server-enforced admin surface. Ordinary VK and Telegram users remain denied; the sandbox wallet cannot become live funds. Public rollout, live financial cutover, payments, generation/history/feed parity and offer changes remain out of scope and blocked.

Release additions after exact-head review: magic-link launch data is removed from the application cache, launch snapshot and Telegram SDK session key; the authenticated `/me` response supplies the configured Telegram bot username so the standalone VK root can create a VK→Telegram invitation without a hardcoded client value. Production requires `VK_MINI_APP_SECRET` and `TELEGRAM_BOT_USERNAME` in secret/runtime configuration. Rollback is the isolated PR revert plus restoration of the maintenance vhost; preview policy can be disabled independently.


## Public signed-account rollout — 08.11.2026

The owner explicitly authorized opening the shared application to all users. This
supersedes the administrator-only admission rule above for signed
`POST /session`, `GET /me`, `POST /logout` and the two-sided link routes.
Telegram and VK launch signatures, freshness, policy revision, account status,
opaque hashed session tokens, expiry and revocation remain mandatory.

Administrator authorization is still required for settings, sandbox wallet and
commercial administration. Ordinary users receive only their own account
metadata and link state. A VK user must link an existing Telegram account before
the main Mini App bootstrap; the Telegram legacy user remains the canonical live
balance, history, referral and generation owner. The rollout does not create
synthetic Telegram users, match equal numeric IDs automatically, expose a VK-only
balance, change prices/payments/providers, or modify the text bot.

The existing revisioned `enabled` setting is now the public admission kill
switch. `vk_admin_ids` grants VK administrative tools only; removing an ID no
longer blocks a newly signed public session, while the policy revision still
invalidates previously issued sessions. Session creation deletes only rows whose
expiry has already passed, using the existing expiry index, so public traffic
does not grow the session table without bound. Active and unexpired revoked rows
retain their prior audit and revocation behavior.
