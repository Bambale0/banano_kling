# Shared accounts: isolated administrator preview

Status: initial implementation, draft only. Parent: #408; E1: #409.
Baseline: tanyapi@03a9918db303b8ac075115fde8cbccecf6d10aeb.

## Release constraint

Igor authorized implementation on 2026-11-05, with no merge/deploy to production
until the complete feature is finished. Initial access is strictly for admins.
Use a Draft PR; do not arm auto-merge. Do not modify production data or deploy a
preview into the production process. Admin visibility is implemented in code and
verified in isolated tests, not claimed as available in the live application.

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
Only the authenticated administrator may use the preview; client flags are
ignored. Telegram admins use the current server configuration. VK admins must be
explicitly assigned by a verified Telegram admin. An identical number across
platforms has no authority. VK application secret is VK_MINI_APP_SECRET in secret
configuration; app ID and admin IDs are non-secret managed policy.

Sessions use random 256-bit bearer credentials, hashes at rest, expiry and
revocation. Credentials are never accepted via URL. Every request re-evaluates
current administrator membership and the enabled flag. Account state and identity
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
| POST /session | platform + signed launch_data; enabled admin policy | Account, random session token and expiry |
| GET /me | Authorization: Bearer; current enabled admin policy | Own account and source identity |
| POST /logout | Authorization: Bearer; current enabled admin policy | Revoke current session |

Disabled feature returns 404 for session/profile/logout. Invalid credentials
return 401; verified non-admin 403; malformed policy 400; revision conflict 409;
unexpected storage failure returns a redacted 503. Missing/bad VK secret fails
closed. No wallet value is returned until migration and finance work is done.

Policy is a typed JSON value in existing bot_settings under
`shared_accounts.preview`; no per-process policy cache. Administrator screen in
the own-profile view manages enabled, VK app/admin IDs, session TTL and launch
max age. Revision is server-managed; policy and audit commit together. Default
enabled=false, VK admins empty. The enabled flag cannot authorize ordinary users.

## Migration and remaining decisions

Runtime audit found floating Telegram credits despite NUMERIC in the schema file;
VK balance and balance_units differ. Read-only aggregate preflight is available
as scripts/audit_shared_account_migration.py. Never interpret units divergence as
permission to change customer balances. Before wallet cutover: exact scale,
snapshot, legacy writer barrier, idempotent opening entry, reconciliation and
single financial authority. Historical payment transactions are not a complete
wallet ledger. Bananas and partner rubles stay separate.

This slice does not merge identities, move balances, issue magic links, enable
VK generations, migrate histories or alter roles/tariffs. Those are tracked in
E2–E8 and must satisfy the parent plan. Account-link conflicts, grandfathered
referrals, bonus provenance and unlink recovery require explicit policy before
cutover. General launch credentials are not reusable account-link consent.

## Verification seams

- HTTP: admin-only flag, signature/freshness, source-scoped admin membership,
  settings CAS/audit failure, concurrent login, session revoke/expiry and legacy
  balance preservation, run on both SQLite and an isolated PostgreSQL schema.
- UI: ordinary user makes no preview request; admin save, test login and stale
  configuration feedback. Existing profile/browser-auth regressions stay green.
- Migration diagnostic: synthetic SQLite with known fractional/drift cases,
  unchanged database bytes; output is aggregate only.

Production credentials, paid providers and real chat sends are not used by tests.

Protocol references: [Telegram launch validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app),
[VK launch-signature example](https://github.com/VKCOM/vk-apps-launch-params).
The latter is an archived official example; real VK-client launch and cabinet
configuration remain an acceptance gate for the later VK entrypoint slice.


## Admin-only production preview authorization — 06.11.2026

The owner explicitly authorized merge and production deployment of the current administrator preview. This supersedes the earlier no-deploy hold only for the signed, server-enforced admin surface. Ordinary VK and Telegram users remain denied; the sandbox wallet cannot become live funds. Public rollout, live financial cutover, payments, generation/history/feed parity and offer changes remain out of scope and blocked.

Release additions after exact-head review: magic-link launch data is removed from the application cache, launch snapshot and Telegram SDK session key; the authenticated `/me` response supplies the configured Telegram bot username so the standalone VK root can create a VK→Telegram invitation without a hardcoded client value. Production requires `VK_MINI_APP_SECRET` and `TELEGRAM_BOT_USERNAME` in secret/runtime configuration. Rollback is the isolated PR revert plus restoration of the maintenance vhost; preview policy can be disabled independently.
